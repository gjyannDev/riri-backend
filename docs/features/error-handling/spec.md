# Feature: Structured Error Handling and Logging

## Problem
riri-backend has only a minimal `AppError` (3 subclasses) that returns a plain `{"detail": "..."}` body, with no logging, no request tracing and no error tracking. As feature modules and AI provider calls get added, errors can't be told apart by origin (client mistake, business rule, database, outside service, bug), responses are inconsistent, and failures can't be traced to a request or monitored.

## Goal
Every error the API produces is categorized, returned in one consistent machine-readable format with a stable code, logged exactly once with a request ID, and server-side failures (status 500 and above) are reported to Sentry. The mobile app can decide what to do from the response alone (`code`, `category`, `retryable`).

## User Flow
Actors: the Expo mobile app (API client) and the developer/operator reading logs and Sentry.

1. The app sends a request, optionally with an `X-Request-ID` header.
2. The backend assigns the request an ID (reusing the client's if it is a valid UUID) and returns it in the `X-Request-ID` response header.
3. On success, one access-log line is written for the request.
4. On failure, the response uses the standard error format (see Requirements), including `code`, `category`, `retryable` and `request_id`. The app branches on those fields, never on the message text.
5. The developer takes the `request_id` from a bug report, finds every log line for that request, and for 5xx failures finds the matching Sentry event.

## Requirements

### Functional

**Error categories.** Every error belongs to exactly one category:

| Category | Meaning | Typical status |
| --- | --- | --- |
| `validation` | Bad input from the client | 422 |
| `auth` | Not authenticated, or not allowed | 401 / 403 |
| `domain` | Business rule: not found, conflict, rule violation | 404 / 409 / 422 |
| `database` | Database unavailable, timed out, or an unhandled constraint failure | 409 / 503 |
| `external` | Outside service (LLM, speech, payments) failed | 502 / 503 / 504 |
| `internal` | Bug or unknown exception | 500 |

**Error format.**
- All error responses use RFC 9457 Problem Details (`application/problem+json`), with `type` set to `about:blank`.
- Each response also carries: `code` (stable, unique, upper snake case), `category`, `retryable` (boolean) and `request_id`.
- Validation errors list each failing field with its location, a message and an error type. The submitted input value is never echoed back.
- Every error class defines its own category, status, code, safe public message and retryable flag.
- Messages are safe to show users. Internal detail (SQL, constraint names, provider responses, stack traces) never appears in a response outside `ENVIRONMENT=local`.
- In `ENVIRONMENT=local` only, unexpected (500) errors include the exception type and message in the response.

**Conversion and fallback.**
- Services raise categorized errors. Errors a service expects from the database or a library are converted into its own error, keeping the original as the cause.
- Anything not converted is handled by a global fallback:
  - Framework HTTP errors (unknown route 404, wrong method 405, etc.) use the same error format with codes such as `NOT_FOUND` and `METHOD_NOT_ALLOWED`.
  - Database unreachable or timed out: 503 `DATABASE_UNAVAILABLE`, `retryable: true`, no `Retry-After` header.
  - Unique or foreign-key violation: 409 `CONFLICT` with a generic message.
  - Not-null or check violation: 500 `INTERNAL_ERROR`.
  - Any other exception: 500 `INTERNAL_ERROR` with a generic message.
- The `external` category and its classes (timeout, rate limited, bad response, with a service name) exist and carry `retryable`, but nothing raises them yet.

**Request ID.**
- A valid incoming `X-Request-ID` (UUID) is reused. Otherwise a new one is generated.
- The ID is in the `X-Request-ID` response header on every response, including 4xx and 5xx, and in the `request_id` field of every error body.
- The ID is attached to every log line written during the request and to the Sentry event.

**Logging.**
- Logs are structured (an event name plus key/value fields), written to stdout.
- Local: human-readable console format. Staging/production: one JSON object per line. Log level is configurable.
- Logs from uvicorn and SQLAlchemy use the same format and carry the request ID.
- One access-log line per request: method, path, status, duration in milliseconds, request ID. Successful `GET /health` requests are not logged; failed ones are.
- An error is logged once, at the global handler, not at each layer. Level by outcome: info for expected 4xx (validation, domain), warning for auth failures and unhandled database conflicts, error for 5xx. Unexpected 500s include the traceback; database and external errors include the original cause.
- Request/response bodies and headers are never logged. As a second layer, any log field named `password`, `token`, `authorization`, `cookie`, `api_key` or `secret`, at any depth, is replaced with `[REDACTED]`.

**Error tracking (Sentry).**
- Only errors with status 500 or above are reported, with tags for category, code and request ID. Validation, auth, domain and 4xx database conflicts are logged only.
- Each error is reported once.
- Personal data is not sent by default.
- Sentry is optional: with no DSN configured (local, tests) nothing is sent and the app behaves normally. In staging/production, a missing DSN produces one startup warning, not a startup failure.
- A setting turns Sentry on or off without removing the DSN. It defaults to on (Sentry is active whenever a DSN is set). When off, Sentry is not initialized, nothing is sent, and no missing-DSN warning is logged; structured logs still record every error exactly as before.
- Sentry being unreachable or rejecting events never changes a request's response.

**Replacing the old handler.**
- `app/core/exceptions.py` is removed; the new error package replaces it. The old `{"detail": ...}` body is replaced outright, with no compatibility shim (no clients exist yet).
- Existing error classes (`NotFoundError`, `ConflictError`, `UnauthorizedError`) are kept under the new categories, still importable by services.

**Configuration.**
- Settings are organized into groups by concern (database, logging, Sentry), reachable through the existing `settings` import, with app-level settings staying at the top level.
- Every existing environment variable name keeps working unchanged. A `.env` written before this feature loads with identical values, and the new settings take their defaults (`LOG_LEVEL` INFO, no Sentry DSN, Sentry switch on).
- `.env.example` has one commented section per group, and the architecture docs say where a new group goes.

**Local error trigger.**
- When `ENVIRONMENT=local`, a debug route lets the developer raise each kind of error on demand (a `kind` value picks the category, including an unhandled exception), so responses, logs and Sentry can be explored without touching real code.
- The route does not exist in staging or production.

**Documentation.**
- `docs/architecture.md` Errors convention is updated, and a short logging convention is added.
- A docs page lists every error code with its category, status, retryable flag and meaning, so the mobile app can rely on them.

### Non-Functional
- **Security:** no secrets, personal data, SQL text or constraint names in any response; no request/response bodies in logs.
- **Reliability:** logging or Sentry failures must not change a request's response.
- **Performance:** access logging and request-ID handling add no more than negligible overhead per request (assumption: no measurable change in the existing health test; no numeric threshold set).
- **Stability:** error codes are a contract. Renaming or removing a code is a breaking change.

## UX Requirements
- The mobile app can decide behavior from `category`, `code` and `retryable` alone (for example, offer a retry for `retryable: true`).
- Validation errors identify the failing field so forms can show per-field messages.
- Messages are user-safe and readable; they are not required to be translated.

## Constraints
- Libraries chosen by the user: `fastapi-problem`, `asgi-correlation-id`, `structlog`, `sentry-sdk[fastapi]`. Check each against the repo's versions (Python >=3.14, FastAPI >=0.165, Pydantic 2) before use.
- Existing stack: FastAPI, SQLAlchemy 2 with psycopg, pytest, ruff (line length 100). Tests run on in-memory SQLite with a `get_db` override.
- Sentry settings and log settings come from environment configuration through the grouped settings (`app/core/config`), as the existing settings do.
- Follow the layout in `docs/architecture.md`: services raise errors, routers stay thin.

## Blockers
- No unresolved decisions. Items marked "assumption — verify" in Edge Cases and Constraints need checking against the installed library versions during planning.

## Edge Cases

- **EC1:** Request to an unknown route -> 404, `code: NOT_FOUND`, standard error format, `request_id` present; logged at info.
- **EC2:** Wrong HTTP method on an existing route -> 405, `code: METHOD_NOT_ALLOWED`, standard error format.
- **EC3:** Unhandled exception in a route -> 500 `INTERNAL_ERROR`, generic message, `X-Request-ID` header and `request_id` body field present (assumption — verify: the request ID is still available when the response is produced by the outermost server-error layer); traceback in logs; reported to Sentry; exception details in the body only when `ENVIRONMENT=local`.
- **EC4:** Database unreachable or query times out, not handled by a service -> 503 `DATABASE_UNAVAILABLE`, `retryable: true`, no `Retry-After`, no connection details in the body; logged at error; reported to Sentry.
- **EC5:** Unhandled unique or foreign-key violation -> 409 `CONFLICT`, generic message; constraint name appears only in the log (warning); not reported to Sentry.
- **EC6:** Unhandled not-null or check violation -> 500 `INTERNAL_ERROR`; logged at error; reported to Sentry.
- **EC7:** Request validation fails on a field containing a password or token -> 422 `VALIDATION_ERROR` listing field, message and type; the submitted value is not in the response or the logs.
- **EC8:** Client sends a malformed `X-Request-ID` (not a UUID) -> it is ignored and a new ID is generated and returned.
- **EC9:** Client sends a valid `X-Request-ID` -> the same ID is returned in the header and body, and appears on all log lines for the request.
- **EC10:** Successful `GET /health` -> no access-log line. Failed `GET /health` -> access-log line written.
- **EC11:** A log call includes a field named `password`/`token`/`authorization`/`cookie`/`api_key`/`secret`, including nested inside another object -> value written as `[REDACTED]`.
- **EC12:** No Sentry DSN configured (local or tests) -> app runs normally, nothing sent, no warning when `ENVIRONMENT=local`.
- **EC13:** No Sentry DSN in staging/production -> app starts, one warning logged at startup.
- **EC14:** Sentry is unreachable or rejects an event at runtime -> the request's response and status are unchanged.
- **EC15:** A service raises a categorized error for a handled case (for example, an email already registered) -> response uses that error's own code, category and status; not reported to Sentry if status is below 500.
- **EC16:** Two error classes defined with the same `code` -> an automated test fails.
- **EC17:** An `external`-category error with `retryable: true` is raised (no caller yet; verified via a test route) -> response is 502/503/504 as defined for that class, includes `retryable: true`, and is reported to Sentry.

- **EC18:** The debug trigger route is called in staging or production -> 404 `NOT_FOUND` in the standard error format (the route is not mounted). An unknown `kind` in local -> 422 `VALIDATION_ERROR`.
- **EC19:** Sentry is switched off while a DSN is set -> app starts without initializing Sentry, no events are sent, no missing-DSN warning, and 5xx errors are still logged at error level with tracebacks.
- **EC20:** A `.env` containing only the variables that exist today (no `LOG_*` or `SENTRY_*`) -> app starts, the database URL is identical to before, `LOG_LEVEL` is INFO and Sentry is inactive for lack of a DSN.

## Acceptance Criteria

- [ ] **AC1:** For each of the six categories, a request that raises a representative error returns the expected status, `Content-Type: application/problem+json`, and a body with `type: "about:blank"`, `code`, `category`, `retryable` and `request_id`.
- [ ] **AC2:** Every response (success or error) includes an `X-Request-ID` header; for error responses the body's `request_id` equals that header.
- [ ] **AC3:** A valid UUID sent as `X-Request-ID` is returned unchanged; a malformed value is replaced with a new UUID (EC8, EC9).
- [ ] **AC4:** Unknown route and wrong method return the standard error format with `NOT_FOUND` / `METHOD_NOT_ALLOWED` (EC1, EC2).
- [ ] **AC5:** An unhandled exception returns 500 `INTERNAL_ERROR` with a generic message and no exception details when `ENVIRONMENT` is staging or production; the exception type and message are present when `local` (EC3).
- [ ] **AC6:** Database-unavailable, unique/FK violation and not-null/check violation produce the statuses, codes and retryable values in EC4–EC6, and no response body contains SQL text, table names or constraint names.
- [ ] **AC7:** Validation errors return 422 with per-field `field`, `issue` and `type`, and never include the submitted input value (EC7).
- [ ] **AC8:** Each failing request produces exactly one error log record from the error handler (not one per layer), at the level defined above; 5xx records include a traceback.
- [ ] **AC9:** Every log record emitted during a request, including from uvicorn and SQLAlchemy, contains the request ID.
- [ ] **AC10:** Exactly one access-log record is written per request, with method, path, status, duration in ms and request ID; successful `GET /health` writes none (EC10).
- [ ] **AC11:** Logs are console format when `ENVIRONMENT=local` and one JSON object per line otherwise; the configured log level is respected.
- [ ] **AC12:** Fields named `password`, `token`, `authorization`, `cookie`, `api_key`, `secret` are `[REDACTED]` in log output at any nesting depth, and request/response bodies are not logged (EC11).
- [ ] **AC13:** With Sentry mocked, a 500 error produces exactly one captured event tagged with category, code and request ID; 4xx errors (including 409 database conflicts) produce none (EC5, EC15).
- [ ] **AC14:** With no DSN set, the app starts and handles requests with no Sentry calls; in staging/production it logs one startup warning (EC12, EC13). A failing Sentry client does not change the response (EC14).
- [ ] **AC15:** An automated test fails if any two error classes share a `code`, or if a class lacks a category, status or code (EC16).
- [ ] **AC16:** A docs page lists every error code with category, status, retryable flag and meaning, and a test or check confirms it matches the defined classes.
- [ ] **AC17:** `app/core/exceptions.py` is gone, `NotFoundError`, `ConflictError` and `UnauthorizedError` remain importable from the new package, and the existing test suite still passes.
- [ ] **AC18:** `docs/architecture.md` describes the error and logging conventions (who raises, where errors are converted, log-once rule, level meanings).
- [ ] **AC19:** With `ENVIRONMENT=local`, the debug route raises an error of each category when given its `kind` and the response matches that category's format; in staging/production the route returns 404 (EC18).
- [ ] **AC20:** With Sentry switched off and a DSN set, no Sentry client is initialized and no events are captured, a 500 is still logged at error level with a traceback, and switching it back on restores reporting without any other change (EC19).
- [ ] **AC21:** Settings are grouped (database, logging, Sentry) behind the existing `settings` import, every existing environment variable name still loads the same value, a pre-existing `.env` still starts the app with the same database URL (EC20), and `.env.example` has one commented section per group.

## Out of Scope
- **Retry policy (tenacity):** nothing calls an outside service yet; the policy is specced with the first AI provider call. The `retryable` flag and `external` classes are in scope so that work can plug in.
- **Metrics and dashboards, alerting rules:** logs and Sentry cover this stage; revisit with production traffic.
- **Translating error messages into other languages:** the app branches on `code`, not text.
- **Logging request/response bodies or per-user context:** deferred until the auth module exists and a privacy decision is made.
- **Compatibility with the old `{"detail": ...}` body:** no clients exist yet.
- **Log shipping/aggregation setup:** the app only writes to stdout; the hosting platform collects it.
