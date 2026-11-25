# Riri backend

Backend for Riri, an AI voice CBT/DBT skills coach (a skills coach, not a therapist). Python 3.14, FastAPI, SQLAlchemy 2, Alembic, Postgres + pgvector, LangChain/LangGraph, managed with `uv`.

The project is also a learning path: `docs/ai-engineering-learning-path-v2.md` defines the build order (slices 1-12). Feature work follows `/feature` → `/create-plan` → `/implement`, with specs in `docs/features/<slug>/`.

## Commands

| Task | Command |
| --- | --- |
| Install | `uv sync` |
| Start the database | `docker compose up -d db` (Postgres + pgvector on localhost:5434) |
| Dev server | `uv run fastapi dev` |
| Tests | `uv run pytest` |
| Lint / format | `uv run ruff check . && uv run ruff format .` |
| Type check | `uv run pyright` |
| New migration | `uv run alembic revision --autogenerate -m "message"` |
| Apply migrations | `uv run alembic upgrade head` |
| Regenerate error docs | `uv run python -m app.scripts.gen_error_docs` |
| Talk to the coach (terminal) | `uv run python -m app.entrypoints.cli` (logs go to `logs/cli.log`) |
| Check the prompt registry | `uv run python -m app.scripts.prompts check` |
| Run the seed evals (real model, by hand) | `uv run python -m app.scripts.run_seed [--pause-seconds 5]` (results in `docs/features/slice-1c-seed-evals/results/`, every run in `logs/seed-*.jsonl`) |
| Add / use a prompt version | `uv run python -m app.scripts.prompts add <block> <file> --note "why"`, then `... activate <set> <block> <version>` |

## Rules

Read these before planning or writing code. They override generic defaults.

- `.claude/rules/architecture.md`: layers, feature modules, dependency injection, factories, imports, naming, where helpers go, tests.
- `.claude/rules/ai-core.md`: rules for the AI engine (`app/coach/`): model factory, prompt registry, privacy of conversation text, safety.
- `docs/architecture.md`: the long-form explanation, plus the error, logging, Sentry and configuration conventions.

## Non-negotiables

- **Conversation text is health data.** Never log, trace or store user or coach text unless a spec says so explicitly, with consent.
- **Safety is code, not a prompt.** From slice 2 on, the safety gate runs before any model call, and its invariant test must pass in every slice.
- **Settings only through `app.core.config`**, never `os.getenv`. Secrets use `SecretStr`.
- **Tests never reach real external services** (LLM, STT, TTS, tracing). Use fakes.
