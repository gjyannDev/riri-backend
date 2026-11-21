# riri-backend

Backend for Riri, an AI voice skills coach: LangGraph session flow, RAG over CBT/DBT skills, tool calling, crisis safety gate, and Deepgram STT / ElevenLabs TTS via LiveKit.

Built with FastAPI, SQLAlchemy 2, Alembic and PostgreSQL. Managed with [uv](https://docs.astral.sh/uv/).

## Getting started

```bash
uv sync                          # install dependencies
cp .env.example .env             # then set POSTGRES_PASSWORD
docker compose up -d db          # start PostgreSQL
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
| New migration | `uv run alembic revision --autogenerate -m "message"` |
| Apply migrations | `uv run alembic upgrade head` |

## Project structure

```
alembic/            Database migrations
app/
  main.py           FastAPI application entry point
  core/             Config, security, exceptions
  db/               Engine/session, declarative base, models/
  modules/          Feature modules (one package per feature)
  scripts/          Application-specific scripts
docs/               Technical documentation
tests/              Automated tests
```

See [docs/architecture.md](docs/architecture.md) for conventions.
