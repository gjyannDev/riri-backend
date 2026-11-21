import os
from collections.abc import Callable, Generator

# Tests never report to the real Sentry project, even though .env holds a DSN.
# Real environment variables take precedence over .env, so this wins before settings load.
os.environ["SENTRY_ENABLED"] = "false"
# Tests use SQLite and never connect with this URL; it only lets settings load without a real .env.
os.environ["DATABASE_URL"] = "postgresql+psycopg://test:test@127.0.0.1:5433/test"

import pytest  # noqa: E402
from fastapi import APIRouter  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402
from sqlalchemy import create_engine, event  # noqa: E402
from sqlalchemy.exc import IntegrityError  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.core import errors  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.db import models  # noqa: E402, F401  (registers models on Base.metadata)
from app.db.base import Base  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.main import app, create_app  # noqa: E402

engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture
def session() -> Generator[Session]:
    Base.metadata.create_all(engine)
    with TestingSessionLocal() as session:
        yield session
    Base.metadata.drop_all(engine)


@pytest.fixture
def client(session: Session) -> Generator[TestClient]:
    app.dependency_overrides[get_db] = lambda: session
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


MakeClient = Callable[..., TestClient]


@pytest.fixture
def make_client(session: Session, monkeypatch: pytest.MonkeyPatch) -> MakeClient:
    """Build a fresh app for one environment, optionally with extra test-only routes.

    Server exceptions are not re-raised, so tests see the 500 response a client would.
    """

    def build(environment: str = "local", router: APIRouter | None = None) -> TestClient:
        monkeypatch.setattr(settings, "ENVIRONMENT", environment)
        built = create_app()
        if router is not None:
            built.include_router(router)
        built.dependency_overrides[get_db] = lambda: session
        return TestClient(built, raise_server_exceptions=False)

    return build


class _Diag:
    constraint_name = "uq_users_email"


class _PgUniqueViolation(Exception):
    """Stands in for psycopg's UniqueViolation (sqlstate + diag), which the suite can't trigger."""

    sqlstate = "23505"
    diag = _Diag()


def _violate(kind: str) -> None:
    """Trigger a real constraint failure on a throwaway SQLite database."""
    db = create_engine("sqlite://", poolclass=StaticPool)
    event.listen(db, "connect", lambda conn, _: conn.execute("PRAGMA foreign_keys=ON"))
    with db.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE parents (id INTEGER PRIMARY KEY)")
        conn.exec_driver_sql(
            "CREATE TABLE things (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, "
            "qty INTEGER CHECK (qty > 0), parent_id INTEGER REFERENCES parents(id))"
        )
        conn.exec_driver_sql("INSERT INTO things (name, qty) VALUES ('taken', 1)")
    statements = {
        "unique": "INSERT INTO things (name, qty) VALUES ('taken', 1)",
        "fk": "INSERT INTO things (name, qty, parent_id) VALUES ('orphan', 1, 99)",
        "notnull": "INSERT INTO things (name, qty) VALUES (NULL, 1)",
        "check": "INSERT INTO things (name, qty) VALUES ('zero', 0)",
    }
    with db.begin() as conn:
        conn.exec_driver_sql(statements[kind])


class SignUp(BaseModel):
    email: str
    password: str = Field(min_length=12)


@pytest.fixture
def error_router() -> APIRouter:
    """Test-only routes that raise each kind of error."""
    router = APIRouter(prefix="/test")
    app_errors = {
        "validation": lambda: errors.ValidationError("Bad thing"),
        "auth": lambda: errors.UnauthorizedError(),
        "forbidden": lambda: errors.ForbiddenError(),
        "domain": lambda: errors.NotFoundError("No session with that id"),
        "conflict": lambda: errors.ConflictError("An account with this email already exists"),
        "database": lambda: errors.DatabaseUnavailableError(),
        "external": lambda: errors.ExternalTimeoutError(service="stt"),
        "internal": lambda: errors.InternalError(),
    }

    @router.get("/errors/{kind}")
    def raise_app_error(kind: str) -> None:
        raise app_errors[kind]()

    @router.get("/unhandled")
    def raise_unhandled() -> None:
        raise RuntimeError("secret internals at /srv/riri")

    @router.get("/db/down")
    def database_down() -> None:
        unreachable = "postgresql+psycopg://dbuser:dbpass@127.0.0.1:1/riri"
        create_engine(unreachable, connect_args={"connect_timeout": 1}).connect()

    @router.get("/db/pg-unique")
    def postgres_unique_violation() -> None:
        raise IntegrityError("INSERT INTO users ...", {"email": "a@b.c"}, _PgUniqueViolation())

    @router.get("/db/{kind}")
    def constraint_violation(kind: str) -> None:
        _violate(kind)

    @router.post("/signup")
    def sign_up(body: SignUp) -> None:
        return None

    return router
