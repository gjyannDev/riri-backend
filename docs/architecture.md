# Architecture

## Layout

| Path | Purpose |
| --- | --- |
| `app/main.py` | FastAPI app: middleware, exception handlers, router registration |
| `app/core/` | Settings (`config.py`), security helpers (`security.py`), domain errors (`exceptions.py`) |
| `app/db/` | SQLAlchemy `Base`, engine/session (`SessionDep`), ORM models in `models/` |
| `app/modules/<feature>/` | One package per feature: `router.py`, `schemas.py`, `service.py`, optional `dependencies.py` |
| `app/scripts/` | One-off/admin scripts, run with `uv run python -m app.scripts.<name>` |
| `alembic/` | Database migrations |
| `tests/` | Pytest suite (uses in-memory SQLite via a `get_db` override) |

## Conventions

- **Routers** declare their own `prefix` and `tags`; `app/main.py` mounts them under `API_V1_PREFIX`.
- **Services** hold business logic and take a `Session`; routers stay thin.
- **Errors**: raise subclasses of `AppError` from services; a global handler turns them into JSON responses.
- **Models**: add new models to `app/db/models/` and import them in `app/db/models/__init__.py` so Alembic sees them.

## Adding a feature module

1. Create `app/modules/<name>/` with `router.py`, `schemas.py`, `service.py`.
2. Add any ORM models under `app/db/models/` and export them from `__init__.py`.
3. Include the router in `app/main.py`.
4. `uv run alembic revision --autogenerate -m "add <name>"`, review the file, then `uv run alembic upgrade head`.
