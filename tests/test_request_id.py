import json
import logging
from uuid import UUID

import pytest
import structlog
from fastapi import APIRouter, FastAPI, Response
from fastapi.testclient import TestClient

from app.core.logging import configure_logging
from app.core.middleware import AccessLogMiddleware

router = APIRouter()


@router.get("/test/logs")
def emit_logs() -> dict[str, str]:
    structlog.get_logger("app.test").info("inside_request")
    logging.getLogger("sqlalchemy.engine").warning("library_record")
    return {"ok": "yes"}


def json_lines(text: str) -> list[dict]:
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def test_every_response_has_a_request_id(make_client) -> None:
    client = make_client()

    for response in (client.get("/health"), client.get("/missing")):
        assert UUID(response.headers["X-Request-ID"])


def test_valid_incoming_request_id_is_reused(make_client) -> None:
    request_id = "123e4567-e89b-12d3-a456-426614174000"

    response = make_client().get("/health", headers={"X-Request-ID": request_id})

    assert response.headers["X-Request-ID"] == request_id


def test_malformed_incoming_request_id_is_replaced(make_client) -> None:
    response = make_client().get("/health", headers={"X-Request-ID": "not-a-uuid"})

    assert response.headers["X-Request-ID"] != "not-a-uuid"
    assert UUID(response.headers["X-Request-ID"])


def test_error_response_header_appears_once(make_client) -> None:
    response = make_client().get("/missing")

    assert len(response.headers.get_list("X-Request-ID")) == 1


def test_every_log_record_in_a_request_carries_its_id(make_client, capsys) -> None:
    client = make_client("staging", router)
    capsys.readouterr()

    response = client.get("/test/logs")

    # The test's HTTP client logs after the response, outside the request; ignore it.
    records = [
        r for r in json_lines(capsys.readouterr().out) if not r["logger"].startswith("httpx")
    ]
    events = {r["event"] for r in records}
    assert {"inside_request", "library_record", "request"} <= events
    assert {r["request_id"] for r in records} == {response.headers["X-Request-ID"]}


def test_one_access_line_per_request(make_client, capsys) -> None:
    client = make_client("staging", router)
    capsys.readouterr()

    response = client.get("/test/logs?token=abc")

    [line] = [r for r in json_lines(capsys.readouterr().out) if r["event"] == "request"]
    assert line["method"] == "GET"
    assert line["path"] == "/test/logs"
    assert line["status"] == 200
    assert isinstance(line["duration_ms"], float)
    assert line["request_id"] == response.headers["X-Request-ID"]
    assert "abc" not in json.dumps(line)


def test_successful_health_check_is_not_access_logged(make_client, capsys) -> None:
    client = make_client("staging")
    capsys.readouterr()

    client.get("/health")

    assert [r for r in json_lines(capsys.readouterr().out) if r["event"] == "request"] == []


def test_failed_health_check_is_access_logged(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO", json_logs=True)
    app = FastAPI()
    app.add_middleware(AccessLogMiddleware)

    @app.get("/health")
    def failing_health() -> Response:
        return Response(status_code=503)

    TestClient(app).get("/health")

    [line] = [r for r in json_lines(capsys.readouterr().out) if r["event"] == "request"]
    assert line["status"] == 503


def test_cors_exposes_request_id_to_the_app(make_client, monkeypatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "BACKEND_CORS_ORIGINS", ["http://localhost:8081"])

    response = make_client().get("/health", headers={"Origin": "http://localhost:8081"})

    assert "x-request-id" in response.headers["Access-Control-Expose-Headers"].lower()
