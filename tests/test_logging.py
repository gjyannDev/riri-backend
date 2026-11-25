import io
import json
import logging
import sys

import pytest
import structlog

from app.core.logging import configure_logging


def json_lines(text: str) -> list[dict]:
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def test_json_output_outside_local(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO", json_logs=True)

    structlog.get_logger("app.test").info("session_created", session_id="abc", duration_ms=42)

    [record] = json_lines(capsys.readouterr().out)
    assert record["event"] == "session_created"
    assert record["session_id"] == "abc"
    assert record["duration_ms"] == 42
    assert record["level"] == "info"
    assert "timestamp" in record


def test_console_output_locally(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO", json_logs=False)

    structlog.get_logger("app.test").info("session_created", session_id="abc")

    out = capsys.readouterr().out
    assert "session_created" in out
    assert "session_id=abc" in out
    with pytest.raises(json.JSONDecodeError):
        json.loads(out)


def test_logs_can_go_to_another_stream(capsys: pytest.CaptureFixture[str]) -> None:
    stream = io.StringIO()
    configure_logging("INFO", json_logs=True, stream=stream)

    structlog.get_logger("app.test").info("session_created")

    assert json_lines(stream.getvalue())[0]["event"] == "session_created"
    assert capsys.readouterr().out == ""


def test_configured_level_is_respected(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("WARNING", json_logs=True)
    log = structlog.get_logger("app.test")

    log.info("hidden")
    log.warning("shown")

    assert [r["event"] for r in json_lines(capsys.readouterr().out)] == ["shown"]


def test_sensitive_keys_are_redacted_at_any_depth(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO", json_logs=True)

    structlog.get_logger("app.test").info(
        "login",
        password="hunter2",
        Authorization="Bearer abc.def",
        payload={"token": "t0k3n", "items": [{"api_key": "sk-123"}, {"secret": "s3"}]},
        cookie="session=1",
        user="ok",
    )

    out = capsys.readouterr().out
    for value in ("hunter2", "abc.def", "t0k3n", "sk-123", "session=1"):
        assert value not in out
    [record] = json_lines(out)
    assert record["password"] == "[REDACTED]"
    assert record["Authorization"] == "[REDACTED]"
    assert record["payload"]["token"] == "[REDACTED]"
    assert record["payload"]["items"][0]["api_key"] == "[REDACTED]"
    assert record["payload"]["items"][1]["secret"] == "[REDACTED]"
    assert record["user"] == "ok"


def test_stdlib_loggers_use_the_same_format(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO", json_logs=True)

    logging.getLogger("uvicorn.error").warning("server %s", "starting")
    logging.getLogger("sqlalchemy.engine").warning("pool exhausted")

    records = json_lines(capsys.readouterr().out)
    assert [(r["logger"], r["event"], r["level"]) for r in records] == [
        ("uvicorn.error", "server starting", "warning"),
        ("sqlalchemy.engine", "pool exhausted", "warning"),
    ]


def test_uvicorn_access_log_is_disabled(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO", json_logs=True)

    logging.getLogger("uvicorn.access").info('127.0.0.1 - "GET / HTTP/1.1" 200')

    assert capsys.readouterr().out == ""


def test_exceptions_are_rendered_with_a_traceback(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO", json_logs=True)

    try:
        raise RuntimeError("boom")
    except RuntimeError:
        structlog.get_logger("app.test").exception("failed")

    [record] = json_lines(capsys.readouterr().out)
    assert "Traceback" in record["exception"]
    assert "RuntimeError: boom" in record["exception"]


def test_console_record_survives_a_legacy_code_page(monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirected stdout on Windows uses cp1252; a traceback's box characters must not drop
    the record (found in the real-server smoke test)."""
    buffer = io.BytesIO()
    monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(buffer, encoding="cp1252"))
    configure_logging("INFO", json_logs=False)

    try:
        raise RuntimeError("boom ☺")
    except RuntimeError:
        structlog.get_logger("app.test").exception("request_error", note="naïve ☺")
    sys.stdout.flush()

    out = buffer.getvalue().decode("cp1252")
    assert "request_error" in out
    assert "RuntimeError" in out


def test_console_traceback_omits_local_variable_values(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO", json_logs=False)
    user_text = "".join(["I feel hope", "less today"])  # built at runtime, not in this source

    def fails(transcript: str) -> None:
        raise RuntimeError("boom")

    try:
        fails(user_text)
    except RuntimeError:
        structlog.get_logger("app.test").exception("request_error")

    out = capsys.readouterr().out
    assert "RuntimeError: boom" in out
    assert user_text not in out
