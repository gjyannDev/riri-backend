# riri-backend

Backend for Riri, an AI voice skills coach: LangGraph session flow, RAG over CBT/DBT skills, tool calling, crisis safety gate, and Deepgram STT / ElevenLabs TTS via LiveKit.

Built with FastAPI, SQLAlchemy 2, Alembic and PostgreSQL. Managed with [uv](https://docs.astral.sh/uv/).

## Getting started

```bash
uv sync                          # install dependencies
cp .env.example .env             # then set the password in DATABASE_URL and POSTGRES_PASSWORD
docker compose up -d db          # start PostgreSQL + pgvector on localhost:5434
uv run alembic upgrade head      # apply migrations
uv run fastapi dev               # http://127.0.0.1:8000/docs
```

## Common commands

| Task | Command |
| --- | --- |
| Run dev server | `uv run fastapi dev` |
| Run production server | `uv run fastapi run` |
| Tests | `uv run pytest` |
| Lint / format | `uv run ruff check . && uv run ruff format .` |
| Type check | `uv run pyright` |
| New migration | `uv run alembic revision --autogenerate -m "message"` |
| Apply migrations | `uv run alembic upgrade head` |
| Talk to the coach (terminal) | `uv run python -m app.entrypoints.cli` (logs go to `logs/cli.log`) |
| Check the prompt registry | `uv run python -m app.scripts.prompts check` |
| Add a prompt version | `uv run python -m app.scripts.prompts add <block> <file> --note "why"` |
| Use a prompt version | `uv run python -m app.scripts.prompts activate <set> <block> <version>` |

## Project structure

```
alembic/            Database migrations
app/
  main.py           FastAPI application entry point
  core/             Config, errors, logging, middleware, Sentry, security
  db/               Engine/session, declarative base, models/ (re-exports module models)
  shared/           Helpers used by two or more modules
  modules/          HTTP feature modules: router → controller → service → repository
  coach/            The AI engine (no HTTP): model factory, prompt registry, conversation
  entrypoints/      Non-HTTP doors into the engine (CLI, later the voice worker)
  scripts/          Application-specific scripts
docs/               Technical documentation
tests/              Automated tests
```

See [docs/architecture.md](docs/architecture.md) for conventions.
