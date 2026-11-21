import importlib
import json

import pytest


def json_lines(text: str) -> list[dict]:
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def error_records(text: str) -> list[dict]:
    return [r for r in json_lines(text) if r["event"] == "request_error"]


@pytest.fixture
def client(make_client, error_router):
    """Factory: call it inside the test body. A logging handler created during fixture setup
    holds the setup phase's stdout, which capsys does not read during the test."""
    return lambda: make_client("staging", error_router)


def assert_problem(response, status: int, code: str, category: str, retryable: bool) -> dict:
    assert response.status_code == status
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert body["type"] == "about:blank"
    assert body["status"] == status
    assert body["code"] == code
    assert body["category"] == category
    assert body["retryable"] is retryable
    assert body["request_id"] == response.headers["X-Request-ID"]
    assert len(response.headers.get_list("X-Request-ID")) == 1
    return body


@pytest.mark.parametrize(
    ("kind", "status", "code", "category", "retryable"),
    [
        ("validation", 422, "VALIDATION_ERROR", "validation", False),
        ("auth", 401, "UNAUTHORIZED", "auth", False),
        ("forbidden", 403, "FORBIDDEN", "auth", False),
        ("domain", 404, "NOT_FOUND", "domain", False),
        ("database", 503, "DATABASE_UNAVAILABLE", "database", True),
        ("external", 504, "EXTERNAL_TIMEOUT", "external", True),
        ("internal", 500, "INTERNAL_ERROR", "internal", False),
    ],
)
def test_each_category_returns_a_problem_body(client, kind, status, code, category, retryable):
    assert_problem(client().get(f"/test/errors/{kind}"), status, code, category, retryable)


def test_unauthorized_keeps_bearer_challenge(client) -> None:
    assert client().get("/test/errors/auth").headers["WWW-Authenticate"] == "Bearer"


def test_unknown_route_uses_the_same_format(client) -> None:
    assert_problem(client().get("/nope"), 404, "NOT_FOUND", "domain", False)


def test_wrong_method_uses_the_same_format(client) -> None:
    assert_problem(client().post("/health"), 405, "METHOD_NOT_ALLOWED", "validation", False)


def test_unhandled_exception_is_generic_outside_local(client) -> None:
    response = client().get("/test/unhandled")

    body = assert_problem(response, 500, "INTERNAL_ERROR", "internal", False)
    assert body["title"] == "An unexpected error occurred"
    assert "secret internals" not in response.text
    assert "RuntimeError" not in response.text
    assert "debug" not in body


def test_unhandled_exception_shows_debug_detail_locally(make_client, error_router) -> None:
    response = make_client("local", error_router).get("/test/unhandled")

    body = assert_problem(response, 500, "INTERNAL_ERROR", "internal", False)
    assert body["debug"] == {"type": "RuntimeError", "message": "secret internals at /srv/riri"}


def test_database_unreachable_returns_retryable_503(client) -> None:
    response = client().get("/test/db/down")

    assert_problem(response, 503, "DATABASE_UNAVAILABLE", "database", True)
    assert "Retry-After" not in response.headers
    for leak in ("127.0.0.1", "dbuser", "dbpass", "psycopg", "connection"):
        assert leak not in response.text


@pytest.mark.parametrize(
    ("kind", "status", "code", "category"),
    [
        ("unique", 409, "CONFLICT", "database"),
        ("fk", 409, "CONFLICT", "database"),
        ("pg-unique", 409, "CONFLICT", "database"),
        ("notnull", 500, "INTERNAL_ERROR", "internal"),
        ("check", 500, "INTERNAL_ERROR", "internal"),
    ],
)
def test_constraint_failures(client, kind, status, code, category) -> None:
    response = client().get(f"/test/db/{kind}")

    assert_problem(response, status, code, category, False)
    for leak in ("things", "users", "INSERT", "constraint", "uq_", "a@b.c"):
        assert leak not in response.text


def test_validation_lists_fields_without_echoing_input(client, capsys) -> None:
    capsys.readouterr()

    response = client().post("/test/signup", json={"email": "a@b.c", "password": "short-pw"})

    body = assert_problem(response, 422, "VALIDATION_ERROR", "validation", False)
    assert body["errors"] == [
        {
            "field": "body.password",
            "issue": "String should have at least 12 characters",
            "type": "string_too_short",
        }
    ]
    assert "short-pw" not in response.text
    assert "short-pw" not in capsys.readouterr().out


def test_service_raised_error_keeps_its_own_code(client) -> None:
    response = client().get("/test/errors/conflict")

    body = assert_problem(response, 409, "RESOURCE_CONFLICT", "domain", False)
    assert body["detail"] == "An account with this email already exists"


def test_external_error_names_the_service(client) -> None:
    body = assert_problem(
        client().get("/test/errors/external"), 504, "EXTERNAL_TIMEOUT", "external", True
    )
    assert body["service"] == "stt"


@pytest.mark.parametrize(
    ("path", "level", "has_traceback"),
    [
        ("/test/errors/domain", "info", False),
        ("/test/errors/validation", "info", False),
        ("/test/errors/auth", "warning", False),
        ("/test/db/unique", "warning", False),
        ("/test/db/down", "error", True),
        ("/test/errors/external", "error", True),
        ("/test/unhandled", "error", True),
    ],
)
def test_each_failure_is_logged_once(client, capsys, path, level, has_traceback) -> None:
    capsys.readouterr()

    response = client().get(path)

    [record] = error_records(capsys.readouterr().out)
    assert record["level"] == level
    assert record["code"] == response.json()["code"]
    assert record["category"] == response.json()["category"]
    assert record["request_id"] == response.headers["X-Request-ID"]
    assert ("exception" in record) is has_traceback


def test_no_other_error_records_for_an_unhandled_exception(client, capsys) -> None:
    capsys.readouterr()

    client().get("/test/unhandled")

    errors = [r for r in json_lines(capsys.readouterr().out) if r["level"] == "error"]
    assert [r["event"] for r in errors] == ["request_error"]


def test_unhandled_database_conflict_logs_the_constraint(client, capsys) -> None:
    capsys.readouterr()

    client().get("/test/db/pg-unique")

    [record] = error_records(capsys.readouterr().out)
    assert record["constraint"] == "uq_users_email"
    assert "a@b.c" not in json.dumps(record)


def test_old_exceptions_module_is_gone() -> None:
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("app.core.exceptions")
