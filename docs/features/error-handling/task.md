# Implementation: Structured Error Handling and Logging

## Status
Ready for PR (11 of 11 steps). Pending: user's live Sentry check (step 11).
Health Check: missing: verification-before-completion -> fallback: gate-command rule; caveman (installed mid-session) -> plain concise chat

## Completed Steps
- [x] 1. Spike: verify the libraries
- [x] 2. Reorganize settings into groups
- [x] 3. Add logging and Sentry settings
- [x] 4. Error classes
- [x] 5. Structured logging
- [x] 6. Request ID and access log
- [x] 7. Global handler and cleanup
- [x] 8. Sentry
- [x] 9. Local debug route
- [x] 10. Error-code docs and conventions
- [x] 11. Final verification and graph update (automated part; live Sentry check is the user's)

## Spike Results (Step 1)
Versions: Python 3.14.7, FastAPI 0.165.0, Starlette 1.10.0, Pydantic 2.14.4, fastapi-problem 0.12.1 (rfc9457 0.4.1, starlette-problem 0.13.5), asgi-correlation-id 5.0.1, structlog 26.1.0, sentry-sdk 2.75.0. Script: scratchpad `spike.py` (throwaway).

| Check | Result | How |
|---|---|---|
| (a) `Content-Type: application/problem+json` | pass | hard-coded in `starlette_problem/handler.py:81`; observed on 404, 500 |
| (b) Python 3.14 / FastAPI 0.165 / Pydantic 2 | pass | spike ran on the project venv |
| (c) `type: about:blank` | pass | `documentation_uri_template="about:blank"` + `strict_rfc9457=True` |
| (d) extra fields in body | pass | constructor kwargs become top-level fields |
| (e) custom handlers for SQLAlchemy errors | pass | `isinstance` matching in dict order |
| (f) request ID on unhandled 500 | pass with a post-hook | context var still set in the outer layer |

Decision: approach A (keep `fastapi-problem`). Findings: default 500 leaks `str(exc)`; default validation handler echoes `input`; the outer layer skips the request-ID header and re-raises; handler order matters (catch-all last). All handled in step 7.

## Changes Made
User commits manually. Suggested commits (in order):
1. `build: add fastapi-problem, asgi-correlation-id, structlog and sentry-sdk` — `pyproject.toml`, `uv.lock`
2. `refactor(config): split settings into database, logging and sentry groups` — `app/core/config/`, `app/core/config.py` (deleted), `app/db/session.py`, `alembic/env.py`, `.env.example`, `tests/test_config.py`
3. `feat(errors): categorized errors, problem+json handler, request IDs and structured logs` — `app/core/errors/`, `app/core/exceptions.py` (deleted), `app/core/logging.py`, `app/core/middleware.py`, `app/main.py`, `tests/conftest.py`, `tests/test_error_classes.py`, `tests/test_logging.py`, `tests/test_request_id.py`, `tests/test_error_responses.py`
4. `feat(observability): optional Sentry reporting for server errors` — `app/core/observability.py`, `tests/test_sentry.py`
5. `feat(debug): local-only route to trigger each error kind` — `app/core/debug.py`, `tests/test_debug_route.py`
6. `docs: error codes page, error/logging/config conventions, feature docs` — `app/scripts/gen_error_docs.py`, `docs/error-codes.md`, `docs/architecture.md`, `README.md`, `tests/test_error_docs.py`, `docs/features/error-handling/`

Each message ends with:
`Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`

## Test Results
- Final: `uv run pytest` -> 104 passed, 2 warnings (Sentry deprecations, see Known Issues). `uv run ruff check .` -> All checks passed. `uv run ruff format --check .` -> 44 files already formatted. (Run with `MSYS2_ENV_CONV_EXCL='*'`, see Baseline Failures.)
- Type check (after user report of editor errors): `uv run --with pyright==1.1.408 pyright app tests alembic` -> 9 errors before (3 in `app/core/errors/handlers.py`: read-only `Mapping` headers passed where a dict was expected, and the handler table vs the library's `Handler` type; 4 in `app/core/config/settings.py`: `_env_file` not visible to type checkers; 2 in `tests/test_error_classes.py`: optional headers indexed), 0 after. No runtime behavior changed; suite still 104 passed. Remaining Pylance items are "not accessed" hints for parameters the handler signature requires.
- Real-server smoke test (uvicorn, `SENTRY_ENABLED=false`): one `request_error` and one `request` line per failure, single `X-Request-ID`, no duplicate uvicorn traceback; staging output is 100% JSON; debug route absent in staging.
- Per step: 2 -> 4 passed; 3 -> 9; 4 -> 27; 5 -> 34; 6 -> 43; 7 -> 74; 8 -> 89; 9 -> 100; 10 -> 102; 11 -> 104. Gates green after every step.

## Tests Pending
- Live Sentry check (user): with the real DSN, call `/_debug/errors/internal`, `/database`, `/external` (each should appear once, tagged `error.category`, `error.code`, `request_id`, environment `local`), then `/domain` and `/validation` (no event). Then `SENTRY_ENABLED=false`: nothing sent, logs unchanged.

## Test Cases
| ID | Step | Case | Tag | Source | Status |
|----|------|------|-----|--------|--------|
| T1 | 2 | existing POSTGRES_* names build the same URL | spec | AC21, EC20 | pass |
| T2 | 2 | app-level settings stay on the root | spec | AC21 | pass |
| T3 | 2 | DB password stays secret in repr | inferred | risk: secret leak | pass |
| T4 | 3 | pre-feature .env loads with new defaults | spec | EC20 | pass |
| T5 | 3 | LOG_LEVEL case-insensitive; invalid rejected | inferred | risk: config typo | pass |
| T6 | 3 | Sentry active with DSN; off switch keeps DSN | spec | AC20 | pass |
| T7 | 4 | every class has category/status/code; codes unique | spec | AC15, EC16 | pass |
| T8 | 4 | category/status/code/retryable table | spec | AC1 | pass |
| T9 | 4 | old classes importable, positional detail | spec | AC17 | pass |
| T10 | 4 | Bearer challenge, service name, Retry-After | code-derived | types.py | pass |
| T11 | 5 | JSON outside local, console locally, level | spec | AC11 | pass |
| T12 | 5 | redaction at any depth | spec | AC12, EC11 | pass |
| T13 | 5 | stdlib loggers same format; uvicorn access off | spec | AC9, plan step 5 | pass |
| T14 | 5 | cp1252 stdout keeps the record | code-derived | smoke test finding | pass |
| T15 | 5 | console traceback omits local values | inferred | smoke test finding, privacy | pass |
| T16 | 6 | request ID on every response; reuse/replace | spec | AC2, AC3, EC8, EC9 | pass |
| T17 | 6 | every record in a request has the ID | spec | AC9 | pass |
| T18 | 6 | one access line; query string not logged | spec | AC10 | pass |
| T19 | 6 | /health quiet on success, logged on failure | spec | EC10 | pass |
| T20 | 6 | CORS exposes X-Request-ID | spec | plan step 6 | pass |
| T21 | 7 | problem body per category | spec | AC1 | pass |
| T22 | 7 | 404/405 in the same format | spec | AC4, EC1, EC2 | pass |
| T23 | 7 | generic 500 outside local; debug locally | spec | AC5, EC3 | pass |
| T24 | 7 | DB down 503 retryable, no leak | spec | AC6, EC4 | pass |
| T25 | 7 | unique/FK 409, not-null/check 500, no leak | spec | AC6, EC5, EC6 | pass |
| T26 | 7 | validation lists fields, no input echoed/logged | spec | AC7, EC7 | pass |
| T27 | 7 | one error record per failure, level, traceback | spec | AC8 | pass |
| T28 | 7 | service error keeps its code; external names service | spec | EC15, EC17 | pass |
| T29 | 7 | old module gone | spec | AC17 | pass |
| T30 | 8 | 5xx reported once with tags; 4xx not | spec | AC13, EC5, EC15, EC17 | pass |
| T31 | 8 | init: private settings, env, no auto integrations | spec | AC13 | pass |
| T32 | 8 | no DSN: no Sentry; warning only outside local | spec | AC14, EC12, EC13 | pass |
| T33 | 8 | switched off: nothing sent, still logged | spec | AC20, EC19 | pass |
| T34 | 8 | Sentry failure leaves response unchanged | spec | EC14 | pass |
| T35 | 8 | local variables never reach the event (real SDK) | inferred | user decision at step 8 | pass |
| T36 | 9 | debug route per kind locally; 422 unknown; 404 elsewhere | spec | AC19, EC18 | pass |
| T37 | 10 | error-code page up to date and complete | spec | AC16 | pass |

AC18 (architecture docs) and the `.env.example` sections of AC21 verified by review, not tests.

## Open Questions
- none blocking. Recommended follow-ups listed under Known Issues.

## Baseline Failures
- Environment, not code: this machine's Git Bash has `API_V1_PREFIX=/api/v1` set in the shell environment, and MSYS rewrites it to `C:/Program Files/Git/api/v1` for Windows programs, so `uv run pytest` fails at import (`Routed paths must start with '/'`) before any change. Run commands with `MSYS2_ENV_CONV_EXCL='*'` (or from PowerShell). With it, the baseline was 1 passed.
- `uv run alembic current` reaches Postgres but fails authentication for user `riri`. The new database URL is identical to the old one (compared without printing it), so this is local credentials, not this change.

## Known Issues
- `send_default_pii` is deprecated in sentry-sdk 2.75 in favor of `data_collection` (DeprecationWarning). It still works; switching is a follow-up.
- A test uses a function transport for Sentry (deprecated, tests only).
- Recommended follow-up: `create_engine(..., hide_parameters=True)` in `app/db/session.py`, so 5xx tracebacks (logs and Sentry) never include SQL parameter values. Not done: outside the spec.
- `CatchUnhandledMiddleware` can't send an error response if one has already started (streaming); that case falls back to Starlette and uvicorn.

## Deviations from Plan
- Test loop granularity: tests written test-first per step (red verified before code) rather than strictly one test at a time. No test weakened or skipped. -> Approved by: pending user review.
- Step 7: `CatchUnhandledMiddleware` handles unknown exceptions inside the request-ID middleware (spike finding (f) and duplicate uvicorn logging). -> plan.md updated (Deviations During Implementation).
- Step 7: domain `ConflictError` code `RESOURCE_CONFLICT` (spec reserves `CONFLICT` for EC5); framework 404 -> `domain`, 405 and other 4xx -> `validation`. -> plan.md updated.
- Step 8: `include_local_variables=False` added. -> Approved by: user (step 8 question).
- Step 11 findings fixed in `app/core/logging.py`: plain console tracebacks; stdout escapes unencodable characters. -> plan.md updated.
- `app/main.py` now exposes `create_app()` (needed to test per environment); `app = create_app()` keeps the entrypoint.
- After step 11, user request: database settings read one required `DATABASE_URL` (`settings.db.url`, a `PostgresDsn` hidden from reprs) instead of the five `POSTGRES_*` names. This replaces AC21/EC20's "existing `POSTGRES_*` names keep working"; T1/T3/T4 rewritten accordingly. compose.yaml keeps `POSTGRES_PASSWORD` (user and db default to `postgres`/`cuewise`), since Compose can't split a URL. Also added `hide_input_in_errors=True` to every settings group: a missing-field error printed `.env` values (found while making this change; regression test `test_missing_database_url_is_rejected_at_load`). -> Approved by: user (request).

## Debug Log
- 2026-11-21, Step 7, `uv run pytest -q tests/test_error_responses.py -k "logged_once or no_other_error or logs_the_constraint"` -> H1: the log handler created during fixture setup holds the setup phase's stdout, which capsys doesn't read in the test body (confirmed by probe: handler stream is stdout = False when built in a fixture, True in the body) -> **fixed** (test wiring: `client` fixture returns a factory called in the test body; regression: the 9 tests, failing before and passing after).

## Review

## Skills Consulted During Implementation
| Step | Skill | Why |
|------|-------|-----|
| setup | find-skills | installed `getsentry/sentry-agent-skills@sentry-python-sdk` (official); structlog skills skipped (low installs, unknown authors) |
| setup, 11 | graphify | built the graph before coding (settings readers: `main.py`, `db/session.py`, `alembic/env.py`, `conftest.py`); `graphify update .` at the end (455 nodes, 843 edges) |
| all | lean-ctx | reads, search, shell, patches |
| 1 | (library sources) | read `fastapi_problem`, `starlette_problem`, `rfc9457`, `asgi_correlation_id` source instead of docs |
| 2-10 | tdd, test | test-first per step, red verified |
| all | ponytail | smallest code per step (no retry policy, no traces, no custom handler) |
| 7 | debug, systematic-debugging | fixture/capsys failure, one hypothesis confirmed |
| 8 | sentry-python-sdk (installed), SDK source | option names checked in `sentry_sdk/consts.py` |

## Links
- Spec: docs/features/error-handling/spec.md
- Plan: docs/features/error-handling/plan.md
- Learnings: docs/features/error-handling/learnings.md

---

## Validation Checklist (before PR)
- [x] All plan.md steps complete
- [x] Full test suite + build green (not just per-step tests)
- [x] Gate commands green on every step (or `gate: none found` recorded)
- [x] Every `/debug` invocation logged in Debug Log; no step left `blocked`
- [x] Every spec.md acceptance criterion met by actual code and covered by a passing spec test (or verification noted)
- [x] Open Questions resolved or explicitly surfaced to the user
- [x] No skipped, deleted, or loosened tests; baseline failures listed separately
- [x] task.md fully updated
- [x] learnings.md written (project template or `references/learnings-template.md`); pending measurements marked and matching Tests Pending
- [ ] Commits documented (suggestions above; user commits)
- [x] No open blockers
- [x] Code follows project .claude/rules (or N/A)
- [x] No unresolved plan deviations (one awaits user review: test loop granularity)
