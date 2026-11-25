# Architecture rules

Layered architecture with feature-driven modules. Every new feature follows these rules. If a rule doesn't fit, say so in the spec or plan; never work around it silently.

## Layout

```
app/
  main.py          Composition root for HTTP: create_app() wires middleware, handlers and routers. No logic.
  core/            Cross-cutting infrastructure: config, errors, logging, middleware, observability, security. Knows no feature.
  db/              SQLAlchemy Base, engine, session (SessionDep). models/__init__.py re-exports every module's models for Alembic.
  shared/          Helpers used by 2+ modules, one file per topic (time.py, ids.py, text.py). Create only when a second user appears.
  modules/         HTTP features, one package per feature.
    <feature>/
      <feature>_router.py        Paths, methods, status codes, response models, Depends. No logic.
      <feature>_controller.py    HTTP ↔ service mapping: takes request schemas, calls the service, returns response schemas.
      <feature>_service.py       Business rules. No FastAPI types. Raises categorized errors.
      <feature>_repository.py    Database access only. No business rules.
      <feature>_schemas.py       Pydantic request/response DTOs.
      <feature>_models.py        SQLAlchemy models (re-exported in app/db/models/__init__.py).
      <feature>_errors.py        Feature error classes (optional).
      <feature>_dependencies.py  Factory functions for DI (see below).
  coach/           The AI engine. No HTTP. See .claude/rules/ai-core.md.
  entrypoints/     Non-HTTP doors into the engine: cli.py (slice 1), voice_worker.py (slice 7).
  scripts/         One-off/admin scripts: uv run python -m app.scripts.<name>
```

Only create the files a feature needs. A module with no database has no repository or models.

## Layers

```
router → controller → service → repository → db
                         ↘ app/coach (through its public interface)
```

- Each layer calls only the layer directly below it. A router never calls a service or repository directly; a controller never touches the session.
- **Router:** declarative. Declares its own `prefix` and `tags`; `app/main.py` mounts it under `API_V1_PREFIX`.
- **Controller:** thin. No business rules, no database.
- **Service:** owns business rules and transactions. Never imports `fastapi` (no `Request`, `HTTPException`, `Depends`). Raises errors from `app.core.errors` or the module's `*_errors.py`, converting library errors where it knows their meaning.
- **Repository:** queries and persistence only. Returns models or plain values. No HTTP, no business decisions.

## Imports

- `app/core` imports no module, no `app/coach` and no `app/shared`.
- `app/shared` imports only `app/core`.
- `app/coach` never imports `fastapi` or `app/modules`. It may import `app/core` and `app/shared`.
- A module never imports another module's repository or models. It calls that module's service.
- Entry points and routers reach the engine only through `app.coach` factories and public interfaces.

## Dependency injection

- **Constructor injection everywhere.** Classes receive collaborators in `__init__` (`AuthService(repository)`, `Coach(model, prompt)`). No module-level singletons holding state, no hidden globals.
- **HTTP side:** FastAPI `Depends` is the container. Each module's `*_dependencies.py` holds the factory chain: `get_<feature>_repository(session)` → `get_<feature>_service(repository)` → `get_<feature>_controller(service)`. Routers depend on the controller factory only.
- **Engine side:** `app/coach/coach_factory.py` is the composition root (`build_coach(settings)`). Entry points call it; tests skip it and pass fakes to constructors.
- No DI library. Add one only if the factory functions stop being enough, and say why in a plan.

## Factories

Anything chosen by configuration (chat model, later embeddings, STT, TTS, tracing) is built by one factory function that reads its settings group. Vendor-specific code lives only in that factory and the small adapter next to it. Swapping a vendor touches only those files.

## Naming

- Module files are prefixed with the feature name: `auth_service.py`, not `service.py`. (Dots like `auth.service.py` are not valid Python module names.)
- Classes: `AuthService`, `AuthRepository`, `AuthController`. Factories: `get_auth_service`, `build_coach`.
- Engine subpackages are named by capability (`llm/`, `prompts/`, `conversation/`), with files prefixed the same way (`prompt_registry.py`, `model_factory.py`).

## Helpers

- Used by one module: a private function (`_name`) in the file that uses it.
- Used by 2+ modules: `app/shared/<topic>.py`, named by what it does.
- Infrastructure (logging, config, errors, security): `app/core/`.
- Never create `utils.py`, `helpers.py` or `common.py`.

## Tests

- Mirror the source tree: `tests/modules/<feature>/test_<feature>_service.py`, `tests/coach/<subpackage>/test_<thing>.py`.
- Reusable fakes (spy chat model, fake repositories) live in `tests/fakes/`.
- Services are tested with fake repositories; repositories against the database; routers through the FastAPI test client.
- Tests never call real external services.

## Adding a feature module

1. Create `app/modules/<feature>/` with only the files it needs.
2. Re-export its models in `app/db/models/__init__.py`.
3. Include its router in `create_app()`.
4. `uv run alembic revision --autogenerate -m "add <feature>"`, review the file, then `uv run alembic upgrade head`.
5. If it adds error classes, regenerate `docs/error-codes.md`.
