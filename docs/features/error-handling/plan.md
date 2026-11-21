# Implementation Plan: Structured Error Handling and Logging

## Overview
Replace the minimal `AppError` handler with categorized errors, RFC 9457 responses, request IDs, structured logs and Sentry reporting, as specified in `spec.md` (AC1-AC21, EC1-EC20). Settings are first reorganized into groups so the new logging and Sentry settings have a clean home.

## Architecture & Design
A new `app/core/errors/` package holds the categorized error classes and one global handler that converts every exception into a problem response, logs it once, and reports 5xx to Sentry when Sentry is on. Logging (structlog) and request-ID/access-log middleware live beside it in `app/core/`. Settings become a package of small groups (database, logging, Sentry) composed into one root `settings`, with environment variable names unchanged. A spike step first checks the `fastapi-problem` library against this repo; if it fails, a small custom handler replaces it and nothing else in the plan changes. Retry policy (tenacity) is out of scope per the spec.

## Approaches Considered

| Approach | Trade-offs | Chosen? |
|----------|-----------|---------|
| A. `fastapi-problem` for classes, handler and hooks | Less code. Beta, single maintainer, thin docs; content type, FastAPI 0.165 support and `about:blank` setup are unverified. | **Yes**, gated by the spike (step 1), as the user chose it |
| B. Small custom handler (about 30 lines) producing the same body | One dependency fewer, full control of content type and fields. We own the code. | Fallback if the spike fails; same file layout |
| C. One handler per exception type (the old project's pattern) | Familiar, but each handler decides format and log level itself, which is the problem the spec fixes. | No |

Settings layout:z

| Approach | Trade-offs | Chosen? |
|----------|-----------|---------|
| S1. Keep one flat `Settings` class | No change now, but every later feature adds to one long list. | No |
| S2. Group classes, each with its own env prefix, composed into a root `settings` | Env variable names stay as they are; grouped access (`settings.sentry.enabled`); more files. | **Yes**, user choice |
| S3. Nested variables with a delimiter (`SENTRY__DSN`) | One class tree, but renames every variable and breaks the existing `.env`. | No |

Logging library (structlog), request ID library (asgi-correlation-id) and Sentry were chosen by the user; the spec settles them.

## Spec Requirements -> Implementation
- Library verification (spec Constraints) -> Step 1
- Grouped settings, unchanged variable names, new logging and Sentry settings (AC21, EC20) -> Steps 2, 3
- Categories, codes, retryable flag, error classes (AC1, AC15, EC16) -> Step 4
- Structured logging, console/JSON, redaction (AC11, AC12) -> Step 5
- Request ID and access log (AC2, AC3, AC9, AC10) -> Step 6
- Problem+json format, framework/DB/unknown fallbacks, validation, debug detail (AC1, AC4-AC8, AC17) -> Step 7
- Sentry reporting, optional DSN and on/off switch (AC13, AC14, AC20) -> Step 8
- Local debug route (AC19) -> Step 9
- Error-code docs and architecture docs (AC16, AC18) -> Step 10

## Implementation Steps
Checkpoint interval: none (user choice). The spike result in step 1 is still reported before step 2 starts.

1. **Spike: verify the libraries** — Files: none in `app/`; a throwaway script in the scratchpad; `pyproject.toml` and `uv.lock` (add `fastapi-problem`, `asgi-correlation-id`, `structlog`, `sentry-sdk[fastapi]`) — Verify: run the script and `uv run pytest` — Test: after (depends on library behavior). Check and record in `task.md`: (a) the response `Content-Type` is `application/problem+json`; (b) it imports and works on Python 3.14 with FastAPI 0.165 and Pydantic 2; (c) `type` can be `about:blank` (via `strict_rfc9457` with a documentation template, or an explicit type on every class); (d) extra fields (`code`, `category`, `retryable`, `request_id`) appear in the body; (e) custom handlers for `IntegrityError` and `OperationalError` run; (f) an unhandled exception still returns the problem body with an `X-Request-ID` header when `CorrelationIdMiddleware` is installed (EC3). Decision rule: if any of (a)-(f) fails and cannot be configured away, use approach B for steps 4 and 7 and remove `fastapi-problem` from dependencies.

2. **Reorganize settings into groups (no behavior change)** — Files: replace `app/core/config.py` with the package `app/core/config/` (`__init__.py` exporting `settings`, `base.py` for the shared env-file setup, `database.py`, `settings.py` for the root class); update the files that read database settings (`app/db/session.py`, and `alembic/env.py` if it reads them); add `tests/test_config.py` — Verify: `uv run pytest` + gate commands, plus confirm `uv run alembic current` still reads the database URL — Test: first. Seam: the public `settings` object. Slices: a `.env` using only today's variable names loads with the same database URL as before (AC21, EC20); app-level settings (`PROJECT_NAME`, `ENVIRONMENT`, `API_V1_PREFIX`, `BACKEND_CORS_ORIGINS`) stay on the root; the database group reads the existing `POSTGRES_*` names through a group prefix and keeps the password a secret. `app/main.py` call sites stay valid because those settings stay on the root. Never read or print `.env`.

3. **Add logging and Sentry settings** — Files: `app/core/config/log.py`, `app/core/config/sentry.py`, `app/core/config/settings.py`, `.env.example` (one commented section per group), `tests/test_config.py` — Verify: `uv run pytest tests/test_config.py` + gate commands — Test: first. Seam: the public `settings` object. Slices: `LOG_LEVEL` default INFO and invalid values rejected at load; `SENTRY_DSN` optional secret, unset by default; `SENTRY_ENABLED` default true, so Sentry is active whenever a DSN is set and can be switched off without deleting the DSN (AC20 setting only); a `.env` without the new variables still loads with those defaults (EC20). Console vs JSON logs derive from `ENVIRONMENT`, with no separate setting. The user already created the Sentry project and set `SENTRY_DSN` in their local `.env`; this step only adds the settings and empty placeholders in `.env.example`.

4. **Error classes** — Files: `app/core/errors/__init__.py`, `app/core/errors/base.py`, `app/core/errors/types.py`, `tests/test_error_classes.py` — Verify: `uv run pytest tests/test_error_classes.py` + gate commands — Test: first. Seam: the base error class and its subclasses (registry of all defined errors). Slices: AC15/EC16 (every class has category, status, code; codes unique), then category/status/retryable per class, then existing `NotFoundError`, `ConflictError`, `UnauthorizedError` still importable (AC17). Includes the six categories, `external` classes with a service name, and the database classes. Follow the layout in `docs/architecture.md`.

5. **Structured logging** — Files: `app/core/logging.py`, `tests/test_logging.py` — Verify: `uv run pytest tests/test_logging.py` + gate commands — Test: first. Seam: captured log records from the configured logger. Slices: console renderer local and JSON otherwise (AC11); the configured log level respected; redaction of the listed keys at any depth (AC12, EC11); standard-library loggers (uvicorn, SQLAlchemy) use the same format; uvicorn's own access log is disabled.

6. **Request ID and access log** — Files: `app/core/middleware.py`, `app/main.py`, `tests/test_request_id.py` — Verify: `uv run pytest tests/test_request_id.py tests/test_health.py` + gate commands — Test: first. Seam: HTTP API through `TestClient`. Slices: header returned on every response; valid UUID reused, malformed replaced (AC2, AC3, EC8, EC9); every log record in a request carries the ID, including uvicorn/SQLAlchemy records (AC9); one access-log line per request with method, path, status, duration, ID; successful `GET /health` not logged, failed one logged (AC10, EC10); CORS exposes `X-Request-ID` to the app.

7. **Global handler and cleanup** — Files: `app/core/errors/handlers.py`, `app/main.py`, `tests/conftest.py` (test-only router that raises each error), `tests/test_error_responses.py`; delete `app/core/exceptions.py` — Verify: `uv run pytest` + gate commands — Test: first. Seam: HTTP API through `TestClient` against the test-only router. Slices, one behavior each: category happy paths with the problem body (AC1); 404/405 in the same format (AC4, EC1, EC2); unhandled exception returns generic 500 and, in `local` only, exception details (AC5, EC3); database unavailable and constraint cases (AC6, EC4-EC6); validation without the submitted input (AC7, EC7); one error log record per failure at the right level with traceback for 5xx, auth as warning (AC8); a service-raised handled error keeps its own code and status (EC15); external errors return their status and `retryable` (EC17); old classes still importable and existing suite green (AC17). Tests change `settings.ENVIRONMENT` at call time, so the handler must read settings per request, not at import.

8. **Sentry** — Files: `app/core/observability.py`, `app/core/errors/handlers.py`, `app/main.py`, `tests/test_sentry.py` — Verify: `uv run pytest tests/test_sentry.py` + gate commands — Test: first. Seam: the Sentry capture call, mocked. Slices: status 500+ captured once with category, code and request ID tags (AC13, EC17); 4xx and 409 database conflicts not captured (EC5, EC15); no DSN means no init and no calls (AC14, EC12); staging/production without DSN logs one startup warning (EC13); switched off with a DSN set: no init, no capture, no warning, and 5xx still logged with traceback (AC20, EC19); capture raising an error leaves the response unchanged (EC14). Sentry's automatic error capture and logging-event integrations are turned off so each error is reported only by the handler. Events carry the app's `ENVIRONMENT` as Sentry's environment, so local experiments can be filtered out. Because the real DSN is in `.env` and settings load it, a test fixture must force the Sentry settings to unset (and use the mocked capture) so test runs never send events to the real project.

9. **Local debug route** — Files: `app/core/debug.py`, `app/main.py`, `tests/test_debug_route.py` — Verify: `uv run pytest tests/test_debug_route.py` + gate commands — Test: first. Seam: HTTP API. Slices: in `local`, each `kind` raises the matching category (AC19); unknown `kind` returns 422 (EC18); in staging/production the route is not mounted and returns the standard 404 (EC18). Route is mounted only when `ENVIRONMENT=local` at startup.

10. **Error-code docs and conventions** — Files: `app/scripts/gen_error_docs.py`, `docs/error-codes.md`, `docs/architecture.md`, `README.md`, `tests/test_error_docs.py` — Verify: `uv run python -m app.scripts.gen_error_docs`, then `uv run pytest tests/test_error_docs.py` + gate commands — Test: first for the generator and staleness test (seam: the generator's output compared to the committed file, AC16), skip for prose docs (AC18). Update the Errors convention, add the Logging convention (who raises, where conversion happens, log-once rule, level meanings) and a Configuration convention (grouped settings, prefixes, where to add a new group), and fix the README structure line.

11. **Final verification and graph update** — Files: none — Verify: `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`, then `graphify update .` if `graphify-out/` exists — Test: skip (runs the full suite). Then a live check against the user's real Sentry project (the DSN is already in `.env`): start `uv run fastapi dev`, call the debug route for an internal, a database and an external `kind`, and confirm in the Sentry UI that each appears once with the category, code and request ID tags and the `local` environment, and that a domain or validation `kind` produces no event. Also confirm that with `SENTRY_ENABLED=false` the same calls send nothing and the logs still show the errors. The user does the Sentry UI check; the steps are reported to them.

## Affected Files & Patterns
- `app/core/config.py` — replaced by the package `app/core/config/` (`base.py`, `database.py`, `log.py`, `sentry.py`, `settings.py`); `from app.core.config import settings` keeps working.
- `app/db/session.py` (and `alembic/env.py` if it reads settings) — database URL moves to the database group.
- `app/core/exceptions.py` — deleted; replaced by `app/core/errors/` (`base.py`, `types.py`, `handlers.py`).
- `app/core/logging.py`, `app/core/middleware.py`, `app/core/observability.py`, `app/core/debug.py` (new).
- `app/main.py` — currently imports `register_exception_handlers`; gains middleware, Sentry init, debug route mount, new handler registration.
- `tests/conftest.py` — gains the test-only router; the existing `client` fixture with the `get_db` override is kept.
- `.env.example` — one commented section per settings group.
- `docs/architecture.md`, `README.md`, `docs/error-codes.md`, `app/scripts/gen_error_docs.py`.
- Patterns to follow: services raise errors, routers stay thin (`docs/architecture.md`); scripts run as `uv run python -m app.scripts.<name>`; settings are read only through `settings`, never `os.getenv`.
- Risks: `fastapi-problem` is Beta with one maintainer (spike gate); the outermost server-error layer may build 500 responses without the request ID (step 1f); Sentry may double-report unless its automatic capture is off; adding global middleware changes every response, so the existing `test_health` must stay green; Python 3.14 compatibility of the four libraries; each settings group must load the same `.env` file, which the shared base handles; a missed call site in the settings reorganization would only show at import or migration time, so step 2 checks Alembic too.

## Testing Strategy
- Framework & command: pytest, `uv run pytest` (config in `pyproject.toml`, `tests/` with in-memory SQLite via the `get_db` override).
- Gate commands: `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .` (from README Common commands; the project has no CLAUDE.md or rules file).
- Coverage map:

| Spec ID | Step | Test mode | Notes |
|---------|------|-----------|-------|
| AC1 | 4, 7 | first | classes in 4, HTTP bodies in 7; content type per spike |
| AC2, AC3 | 6 | first | |
| AC4 | 7 | first | |
| AC5 | 7 | first | change `settings.ENVIRONMENT` in the test |
| AC6, AC7 | 7 | first | assert no SQL or constraint text in body |
| AC8 | 7 | first | log level per category |
| AC9 | 6 | first | needs a request context, so it follows step 5 |
| AC10 | 6 | first | |
| AC11, AC12 | 5 | first | |
| AC13, AC14 | 8 | first | Sentry mocked |
| AC15 | 4 | first | |
| AC16 | 10 | first | |
| AC17 | 4, 7 | first | existing suite green |
| AC18 | 10 | skip | read-through review; gate commands still pass |
| AC19 | 9 | first | |
| AC20 | 3, 8 | first | setting in 3; behavior with a DSN set and switch off in 8; logs unchanged |
| AC21 | 2, 3 | first | grouped access, unchanged variable names, `.env.example` sections |
| EC1, EC2 | 7 | first | |
| EC3 | 1, 7 | after, first | spike confirms the request ID reaches the outermost layer |
| EC4-EC7 | 7 | first | |
| EC8, EC9, EC10 | 6 | first | |
| EC11 | 5 | first | |
| EC12, EC13, EC14 | 8 | first | |
| EC15 | 7 | first | |
| EC16 | 4 | first | |
| EC17 | 4, 7, 8 | first | test route raises an external error |
| EC18 | 9 | first | |
| EC19 | 8 | first | |
| EC20 | 2, 3 | first | old-style `.env` loads with the same values and new defaults |

- Test seams (user-confirmed): HTTP API via `TestClient` against a test-only router; captured log records; the error base class's subclasses; the mocked Sentry capture call. Added by the settings steps and not yet confirmed: the public `settings` object as the seam for configuration behavior. No private helpers tested directly.
- Must verify, not assume: `fastapi-problem` content type, version compatibility and `about:blank` setup (step 1); request ID present on unhandled 500 responses (step 1f, EC3); Sentry reports each error once, checked in the live Sentry project (step 11); tests never send events to the real project even though `.env` holds the DSN (step 8); the database URL is identical before and after the settings reorganization, including for Alembic (step 2).
- Open questions: none (no EC lacks an expected outcome).
- Known baseline failures: none seen; `tests/test_health.py` is the only existing test.

## Blockers & Resolutions
- `fastapi-problem` unverified -> spike step 1 with decision rule and fallback to a custom handler.
- Spec had no criterion for the Sentry-trigger route -> spec amended with AC19 and EC18 (approved in the planning questions).
- `tenacity` was in the original idea but nothing calls an outside service -> excluded by the spec's Out of Scope.
- Sentry account and DSN -> already done by the user (project created, DSN in `.env`); the live check in step 11 uses it.
- The real DSN in `.env` is loaded by tests -> step 8 fixture forces it unset.
- Request ID on unhandled 500 -> checked in the spike, covered by a test in step 7.
- Messy flat settings would grow with this feature -> steps 2 and 3 group them first; spec amended with AC21 and EC20 (user request).
- The `settings` object as a test seam was not confirmed with the user -> confirm at `/implement` before writing the step 2 tests, or accept it as the public interface.

## Trade-offs & Rationale
- Gate the dependency with a spike rather than commit to a Beta library blindly; the fallback is small.
- One global handler (log, report, respond) instead of per-type handlers, so the log-once and report-once rules live in one place.
- Console vs JSON logs derive from `ENVIRONMENT`, so no extra setting to misconfigure.
- Generate the error-code docs from the classes so the page cannot drift.
- Debug route mounted only in `local` (not just guarded), so production has no surface to protect.
- Sentry traces/performance monitoring left off (YAGNI; the spec covers errors only).
- Settings are grouped with per-group prefixes so existing variable names and the user's `.env` keep working; the reorganization is its own behavior-preserving step before any new settings are added.

## Project Rules Applied
- `docs/architecture.md` -> errors are raised from services, routers stay thin, files follow the `app/core/` layout, scripts live in `app/scripts/`.
- `pyproject.toml` ruff config (line length 100, rules E, F, I, B, UP, SIM) -> gate command.

## Skills Consulted
| Skill | Contribution |
|-------|-------------|
| lean-ctx | affected files, existing handler, test fixtures |
| ponytail | kept to one handler, one new test router, no tenacity, no traces; fallback for the beta library |
| grilling | test seams, debug route shape, docs sync approach, checkpoints |
| tdd | seam rules for `Test: first` steps |
| security-review | skipped: no auth or user-data surface; leak prevention is covered by AC6, AC7, AC12 |

## Ready to Implement
- All spec requirements mapped to steps
- Every step has a Test tag; every AC and EC mapped in Testing Strategy (no uncovered IDs)
- Gate commands listed
- Every step names exact files and a verification command
- Approaches Considered filled, checkpoint interval set (none)
- Affected files identified
- Blockers resolved; the only open risk is the spike, with a defined fallback
- Approved deviations from spec: AC19 and EC18 (debug route), AC20 and EC19 (Sentry on/off switch), AC21 and EC20 (grouped settings)

## Deviations During Implementation
Recorded in `task.md` → Deviations from Plan; the plan's steps and coverage are unchanged.
- Step 7: unknown exceptions are handled by a small `CatchUnhandledMiddleware` inside the request-ID middleware, instead of Starlette's outer layer (which skipped the header and re-raised, logging twice).
- Step 7: the domain `ConflictError` code is `RESOURCE_CONFLICT`, since the spec reserves `CONFLICT` for unhandled database conflicts (EC5). Framework 404 maps to `domain`, 405 and other 4xx to `validation`.
- Step 8: Sentry also sets `include_local_variables=False` (user-approved during step 8) and keeps only the process-level integrations (atexit, dedupe, excepthook).
- Step 11 (smoke test findings, fixed in step 5's file): local console tracebacks are plain (the Rich default printed local variable values and took about 1.3 s per error), and stdout escapes characters a legacy Windows code page can't encode instead of dropping the record.
