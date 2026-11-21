# Architecture

## Layout

| Path | Purpose |
| --- | --- |
| `app/main.py` | `create_app()`: logging, Sentry, middleware, exception handlers, router registration |
| `app/core/config/` | Settings: app-level values in `settings.py`, one group per concern (`database.py`, `log.py`, `sentry.py`) |
| `app/core/errors/` | Error categories and classes (`base.py`, `types.py`) and the global handler (`handlers.py`) |
| `app/core/logging.py` | Structured logging setup (structlog + stdlib), redaction, request ID on every record |
| `app/core/middleware.py` | Access log: one line per request |
| `app/core/observability.py` | Optional Sentry reporting |
| `app/core/debug.py` | Local-only route that triggers each kind of error |
| `app/core/security.py` | Security helpers |
| `app/db/` | SQLAlchemy `Base`, engine/session (`SessionDep`), ORM models in `models/` |
| `app/modules/<feature>/` | One package per feature: `router.py`, `schemas.py`, `service.py`, optional `dependencies.py`, `errors.py` |
| `app/scripts/` | One-off/admin scripts, run with `uv run python -m app.scripts.<name>` |
| `alembic/` | Database migrations |
| `tests/` | Pytest suite (uses in-memory SQLite via a `get_db` override) |

## Conventions

- **Routers** declare their own `prefix` and `tags`; `app/main.py` mounts them under `API_V1_PREFIX`.
- **Services** hold business logic and take a `Session`; routers stay thin.
- **Models**: add new models to `app/db/models/` and import them in `app/db/models/__init__.py` so Alembic sees them.

### Errors

- **Services raise categorized errors** from `app.core.errors`; routers don't catch or format them. Every error belongs to one category:

  | Category | Meaning | Typical status |
  | --- | --- | --- |
  | `validation` | Bad input from the client | 400 / 405 / 422 |
  | `auth` | Not authenticated, or not allowed | 401 / 403 |
  | `domain` | Business rule: not found, conflict, rule violation | 404 / 409 / 422 |
  | `database` | Database unavailable, or an unhandled constraint failure | 409 / 503 |
  | `external` | An outside service (LLM, speech, payments) failed | 502 / 503 / 504 |
  | `internal` | A bug or unknown exception | 500 |

- **Feature-specific errors** live in `app/modules/<feature>/errors.py` and subclass a category class, setting their own `code` (stable, unique, upper snake case), `status`, `title` (safe to show users) and `retryable`. Example: `class EmailTakenError(ConflictError): code = "EMAIL_TAKEN"`.
- **Convert where you know the meaning.** A service that expects a library error converts it and keeps the cause: `except IntegrityError as exc: raise EmailTakenError() from exc`. Anything not converted falls back to the global handler: unknown route/method keep their status, database unreachable is `503 DATABASE_UNAVAILABLE`, unique/foreign-key violations are `409 CONFLICT`, not-null/check violations and unknown exceptions are `500 INTERNAL_ERROR`.
- **One handler** (`app/core/errors/handlers.py`) turns every exception into `application/problem+json` (RFC 9457) with `code`, `category`, `retryable` and `request_id`, logs it once, and reports 5xx to Sentry. Clients branch on `code`, never on message text.
- **Never put internals in a response.** SQL, constraint names, provider responses and stack traces go to logs and Sentry only. With `ENVIRONMENT=local`, a 500 also includes the exception type and message under `debug`.
- **Codes are a contract.** `docs/error-codes.md` is generated from the classes (`uv run python -m app.scripts.gen_error_docs`); a test fails if it is stale or if two classes share a code.
- **Try it locally:** `GET /_debug/errors/{kind}` (`validation`, `auth`, `domain`, `database`, `external`, `internal`, `unhandled`) exists only when `ENVIRONMENT=local`.

### Logging

- Use `log = structlog.get_logger(__name__)` and log an event name with fields: `log.info("session_created", session_id=..., duration_ms=...)`, not a sentence.
- Output goes to stdout: readable console lines when `ENVIRONMENT=local`, one JSON object per line otherwise. `LOG_LEVEL` sets the level.
- Every record written during a request carries `request_id` (from `X-Request-ID`, reused if the client sends a valid UUID). Bind more request-wide fields with `structlog.contextvars.bind_contextvars(...)`.
- **Log an error once, at the edge.** The global handler logs every failed request; don't log-and-reraise in services.
- **Levels:** `debug` developer detail; `info` normal events and expected 4xx; `warning` handled but unusual (auth failures, unhandled database conflicts, retries); `error` a request failed because of us or a dependency (5xx, with traceback); `critical` the app can't run.
- **Never log request/response bodies or headers.** Fields named `password`, `token`, `authorization`, `cookie`, `api_key` or `secret` are replaced with `[REDACTED]` at any depth, as a second layer.
- One access line per request (`event=request`: method, path, status, duration). The query string is not logged; successful `GET /health` is skipped.

### Error tracking (Sentry)

- Optional. Active only when `SENTRY_DSN` is set and `SENTRY_ENABLED` is true (the default). `SENTRY_ENABLED=false` turns it off and keeps the DSN; structured logs still record everything.
- Only errors with status 500 or above are reported, once each, tagged with `error.category`, `error.code` and `request_id`. No personal data and no local variable values are sent.
- Tests force `SENTRY_ENABLED=false` (`tests/conftest.py`), so test runs never reach the real project.

### Configuration

- Read settings only through `from app.core.config import settings`, never `os.getenv`.
- App-level values stay on the root (`settings.ENVIRONMENT`). Each concern is a group with its own env prefix: `settings.db` (`DATABASE_URL`), `settings.log` (`LOG_*`), `settings.sentry` (`SENTRY_*`).
- **Adding a group:** create `app/core/config/<name>.py` with a `BaseSettings` subclass using `env_config("<PREFIX>_")`, add it as a field on `Settings` and in `load_settings()`, and add a commented section to `.env.example`. Secrets use `SecretStr`.

## Adding a feature module

1. Create `app/modules/<name>/` with `router.py`, `schemas.py`, `service.py`, and `errors.py` if it has its own errors.
2. Add any ORM models under `app/db/models/` and export them from `__init__.py`.
3. Include the router in `create_app()` in `app/main.py`.
4. `uv run alembic revision --autogenerate -m "add <name>"`, review the file, then `uv run alembic upgrade head`.
5. If you added error classes, regenerate `docs/error-codes.md`.
