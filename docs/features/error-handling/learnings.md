# Learn: Structured error handling and logging

**Concepts:** error taxonomy, translating errors at the boundary, one global handler, RFC 9457 problem details, correlation IDs, structured logging, redaction, optional error tracking. **Status:** built and tested (104 tests, 2026-11-21); live Sentry check **pending** (user, step 11).

## 1. Why it exists
Before this, the API had one `AppError` with three subclasses returning `{"detail": "..."}`, no logs, no request IDs and no error tracking. A database outage, a bug and a "not found" all looked alike, and nothing tied a bug report to what happened on the server. The learning path adds LLM, speech-to-text and text-to-speech calls next, each of which fails in its own ways.

## 2. What it is
Every error belongs to one of six categories (validation, auth, domain, database, external, internal). One handler converts any exception into a categorized error, logs it once, reports 5xx to Sentry (when on), and returns `application/problem+json` with a stable `code`, `category`, `retryable` and `request_id`. Every log line is an event name plus fields, carries the request ID, and has secrets redacted.

```
request ─► CorrelationIdMiddleware (X-Request-ID) ─► AccessLogMiddleware ─► CatchUnhandledMiddleware ─► route
                                                                                     │ raises
                          fastapi-problem handler ◄──────────────────────────────────┘
                          convert ─► _finish: add request_id, log once, report 5xx ─► problem+json
```

## 3. When to use it
| Do this | When | Why / limit |
|---|---|---|
| Raise a category class (or a feature subclass in `errors.py`) | Any expected failure in a service | The handler picks status, log level and Sentry from the class |
| `raise MyError() from exc` | You catch a library error and know what it means | Keeps the cause in the traceback; the fallback table only guesses |
| Let it propagate | You can't recover or add meaning | Logged once at the edge; catching and re-logging creates duplicates |
| `log.info("event_name", key=value)` | Any app log | Searchable fields; never log bodies or headers |
| `SENTRY_ENABLED=false` | You want logs only | Nothing else changes; errors are still logged with tracebacks |

**I'd revisit this when** the first provider call lands (add a tenacity retry policy for `retryable` external errors), or if `fastapi-problem` stops being maintained (the custom fallback is about 30 lines).

## 4. How it works
| Option | Outcome |
|---|---|
| A. `fastapi-problem` for classes and the handler | **Chosen.** Spike passed all six checks (`task.md` → Spike Results) |
| B. Custom handler | Fallback only |
| C. One handler per exception type (old project) | Rejected: format and log level drift per handler |

One unhandled exception, walked through:
1. `app/core/debug.py:39` raises `RuntimeError`. No route handler matches, so it propagates.
2. `CatchUnhandledMiddleware.__call__` (`app/core/errors/handlers.py:206-210`) catches it before Starlette's outer layer would (that layer skips the request-ID header and re-raises, so uvicorn logs the error twice).
3. The `fastapi-problem` handler runs the pre-hook `_remember` (`handlers.py:118`), then the handler table in `register_exception_handlers` (`handlers.py:213`). `_unhandled` (`handlers.py:107`) returns `InternalError`, with `debug` details only when `ENVIRONMENT=local`.
4. The post-hook `_finish` (`handlers.py:122`) adds `request_id` from the correlation context var, re-renders the body, calls `_log` (one record, level by status and category, traceback for 5xx) and `report_error` (`app/core/observability.py:46`, 5xx only, never raises).
5. The response goes out through `CorrelationIdMiddleware`, which adds `X-Request-ID` once, and `AccessLogMiddleware` writes the `request` line.

Settings: `app/core/config/settings.py` composes groups (`db`, `log`, `sentry`), each reading its own prefix, so existing variable names keep working. `load_settings(env_file)` lets tests use a temporary `.env`.

## 5. What can go wrong
| Failure | What the user sees | What the code does | Proof (test name) |
|---|---|---|---|
| Unknown exception | Generic 500, request ID | Logged once with traceback, reported to Sentry | `test_unhandled_exception_is_generic_outside_local`, `test_no_other_error_records_for_an_unhandled_exception` |
| Database down | 503 `DATABASE_UNAVAILABLE`, retryable | No host or credentials in the body | `test_database_unreachable_returns_retryable_503` |
| Unhandled unique/FK violation | 409 `CONFLICT` | Constraint name in the log only, not in Sentry | `test_constraint_failures`, `test_unhandled_database_conflict_logs_the_constraint` |
| Not-null/check violation | 500 | Treated as a bug | `test_constraint_failures` |
| Password fails validation | 422 with field and issue | Submitted value never echoed or logged | `test_validation_lists_fields_without_echoing_input` |
| Secret in a log field | n/a | `[REDACTED]` at any depth | `test_sensitive_keys_are_redacted_at_any_depth` |
| User text in a local variable | n/a | Not sent to Sentry, not printed in console tracebacks | `test_local_variables_never_reach_the_event`, `test_console_traceback_omits_local_variable_values` |
| Sentry down | Same response | Capture error logged as a warning | `test_sentry_failure_does_not_change_the_response` |
| Windows redirected stdout (cp1252) | n/a | Unencodable characters escaped, record kept | `test_console_record_survives_a_legacy_code_page` |
| Two classes share a code | n/a | Test fails | `test_error_codes_are_unique` |

## 6. Try it yourself
1. Predict how many log lines one unhandled error produces locally, and at what levels. Then run `uv run fastapi dev` and call `GET /_debug/errors/unhandled`. Expect one `request_error` (error, with traceback) and one `request` line, sharing a `request_id`.
2. Send your own ID: `curl -H "X-Request-ID: 123e4567-e89b-12d3-a456-426614174000" localhost:8000/_debug/errors/domain`. Predict what comes back in the header and body.
3. Set `ENVIRONMENT=staging` and call `/_debug/errors/domain`. Predict the status (the route doesn't exist there).
4. Sentry: with your DSN in `.env`, call the `internal`, `database` and `external` kinds, then `domain`. Predict which appear in Sentry. Then set `SENTRY_ENABLED=false` and repeat.
5. Add `class EmailTakenError(ConflictError): code = "EMAIL_TAKEN"` in a feature's `errors.py`, run `uv run pytest tests/test_error_docs.py`, and predict the failure message.

## 7. What surprised me
- **The default 500 leaks.** `fastapi-problem` puts `str(exc)` in `detail` unless you replace the catch-all (spike, 2026-11-21).
- **The request-ID middleware doesn't cover 500s.** Starlette handles unknown exceptions outside all user middleware, so the header was missing and uvicorn logged a second traceback. Handling them one layer in fixed both.
- **The console's Rich traceback was the slow part.** With local variables shown, an unhandled 500 took **1,319 ms** and two errors wrote **1,796 log lines**. With a plain traceback: **9.6 ms** first call, **2.8 ms** after, **142 lines** (uvicorn on localhost, `curl`, Windows 11, 2026-11-21).
- **Windows redirected stdout is cp1252.** Box characters dropped whole log records until the stream escaped unencodable characters. Found only by the real-server smoke test, not the suite.
- **Sentry's source context isn't local variables.** The first leak test failed because the test's own literal appeared in the source lines Sentry attaches. Real user text arrives at runtime, so the test now sends it on the request.
- **The shell rewrote `API_V1_PREFIX`.** Git Bash turned `/api/v1` into `C:/Program Files/Git/api/v1`, which broke the baseline suite. `MSYS2_ENV_CONV_EXCL='*'` fixes it; it isn't a code issue.

## 8. Check your understanding
1. Why does an unhandled unique violation return 409 but a not-null violation return 500?
2. When should a service convert a library error itself instead of relying on the global fallback?
3. How does the `request_id` get into a log line written by SQLAlchemy, which knows nothing about requests?
4. What if a new route raises an exception after it has already started streaming a response?

<details>
<summary>Reference answers (write yours first)</summary>

1. A unique or foreign-key violation usually means the client asked for something that conflicts with existing data. A not-null or check violation means our code sent bad data, which is a bug.
2. Whenever it knows the meaning. `EmailTakenError` gives the client a precise code and message, while the fallback can only say `CONFLICT`.
3. `asgi-correlation-id` stores the ID in a context var. The `add_request_id` processor runs in the formatter's `foreign_pre_chain` for stdlib records, so every record emitted in that request's context gets it.
4. `CatchUnhandledMiddleware` re-raises, because a second response can't be sent once one has started. Starlette's outer layer and uvicorn then handle it, so that case isn't logged once.
</details>

## 9. Go deeper / Still open
- Spec: `docs/features/error-handling/spec.md`. Plan: `docs/features/error-handling/plan.md`. Error codes: `docs/error-codes.md`. Conventions: `docs/architecture.md`.
- **Pending:** live Sentry check against the real project (step 11).
- **Open:** a tenacity retry policy for `retryable` external errors (with the first provider call); SQLAlchemy `hide_parameters=True` so 5xx tracebacks never include SQL parameter values; moving from the deprecated `send_default_pii` to `data_collection`.
- Unlocks: `external` errors for slice 7 (Deepgram, LLM, ElevenLabs), and per-stage logging for slice 9.
