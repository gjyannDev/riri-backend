import json

import pytest
import sentry_sdk
from fastapi import APIRouter
from pydantic import SecretStr

from app.core import observability
from app.core.config import settings

FAKE_DSN = "https://publickey@o0.ingest.sentry.io/1"


def json_lines(text: str) -> list[dict]:
    return [json.loads(line) for line in text.splitlines() if line.strip()]


@pytest.fixture
def sentry(monkeypatch: pytest.MonkeyPatch):
    """Record init and capture calls instead of talking to Sentry."""
    calls: dict[str, list] = {"init": [], "capture": []}
    monkeypatch.setattr(sentry_sdk, "init", lambda **kwargs: calls["init"].append(kwargs))
    monkeypatch.setattr(
        sentry_sdk,
        "capture_exception",
        lambda exc, **kwargs: calls["capture"].append((exc, kwargs)),
    )
    monkeypatch.setattr(observability, "_reporting", False)
    return calls


@pytest.fixture
def configure_sentry(monkeypatch: pytest.MonkeyPatch):
    def configure(*, dsn: str | None, enabled: bool = True) -> None:
        monkeypatch.setattr(settings.sentry, "dsn", SecretStr(dsn) if dsn else None)
        monkeypatch.setattr(settings.sentry, "enabled", enabled)

    return configure


def test_server_errors_are_reported_once_with_tags(
    sentry, configure_sentry, make_client, error_router
):
    configure_sentry(dsn=FAKE_DSN)
    client = make_client("staging", error_router)

    response = client.get("/test/unhandled")

    [(exc, kwargs)] = sentry["capture"]
    assert isinstance(exc, RuntimeError)
    assert kwargs["tags"] == {
        "error.category": "internal",
        "error.code": "INTERNAL_ERROR",
        "request_id": response.headers["X-Request-ID"],
    }


@pytest.mark.parametrize("path", ["/test/errors/external", "/test/db/down", "/test/db/notnull"])
def test_other_server_errors_are_reported(
    sentry, configure_sentry, make_client, error_router, path
):
    configure_sentry(dsn=FAKE_DSN)

    make_client("staging", error_router).get(path)

    assert len(sentry["capture"]) == 1


@pytest.mark.parametrize(
    "path",
    ["/test/errors/domain", "/test/errors/validation", "/test/errors/auth", "/test/db/unique"],
)
def test_client_errors_are_not_reported(sentry, configure_sentry, make_client, error_router, path):
    configure_sentry(dsn=FAKE_DSN)

    response = make_client("staging", error_router).get(path)

    assert response.status_code < 500
    assert sentry["capture"] == []


def test_sentry_starts_with_private_settings(sentry, configure_sentry, make_client) -> None:
    configure_sentry(dsn=FAKE_DSN)

    make_client("staging")

    [kwargs] = sentry["init"]
    assert kwargs["dsn"] == FAKE_DSN
    assert kwargs["environment"] == "staging"
    assert kwargs["send_default_pii"] is False
    assert kwargs["include_local_variables"] is False
    assert kwargs["default_integrations"] is False
    assert kwargs["auto_enabling_integrations"] is False


def test_no_dsn_means_no_sentry(sentry, configure_sentry, make_client, error_router) -> None:
    configure_sentry(dsn=None)

    make_client("staging", error_router).get("/test/unhandled")

    assert sentry["init"] == []
    assert sentry["capture"] == []


def test_missing_dsn_warns_once_outside_local(sentry, configure_sentry, make_client, capsys):
    configure_sentry(dsn=None)

    make_client("staging")

    warnings = [
        r for r in json_lines(capsys.readouterr().out) if r["event"] == "sentry_dsn_missing"
    ]
    assert len(warnings) == 1
    assert warnings[0]["level"] == "warning"


def test_missing_dsn_is_silent_locally(sentry, configure_sentry, make_client, capsys) -> None:
    configure_sentry(dsn=None)

    make_client("local")

    assert "sentry_dsn_missing" not in capsys.readouterr().out


def test_switched_off_with_a_dsn_sends_nothing_and_still_logs(
    sentry, configure_sentry, make_client, error_router, capsys
):
    configure_sentry(dsn=FAKE_DSN, enabled=False)
    client = make_client("staging", error_router)

    client.get("/test/unhandled")

    assert sentry["init"] == []
    assert sentry["capture"] == []
    records = json_lines(capsys.readouterr().out)
    assert not [r for r in records if r["event"] == "sentry_dsn_missing"]
    [error] = [r for r in records if r["event"] == "request_error"]
    assert error["level"] == "error"
    assert "Traceback" in error["exception"]


def test_sentry_failure_does_not_change_the_response(
    sentry, configure_sentry, make_client, error_router, monkeypatch
):
    configure_sentry(dsn=FAKE_DSN)

    def broken(exc, **kwargs):
        raise ConnectionError("sentry unreachable")

    monkeypatch.setattr(sentry_sdk, "capture_exception", broken)

    response = make_client("staging", error_router).get("/test/unhandled")

    assert response.status_code == 500
    assert response.json()["code"] == "INTERNAL_ERROR"


def test_local_variables_never_reach_the_event(configure_sentry, make_client, monkeypatch):
    """Real SDK, fake DSN, events captured in memory instead of sent."""
    configure_sentry(dsn=FAKE_DSN)
    events: list[dict] = []
    real_init = sentry_sdk.init
    monkeypatch.setattr(
        sentry_sdk, "init", lambda **kwargs: real_init(**kwargs, transport=events.append)
    )
    router = APIRouter()

    @router.post("/test/transcript")
    def fails_with_user_text_in_scope(body: dict[str, str]) -> None:
        # User text arrives at runtime, as it would from a client; it is not in this source,
        # so Sentry's source context (code lines around the error) can't contain it.
        transcript = body["transcript"]  # noqa: F841  (sits in the frame)
        raise RuntimeError("boom")

    user_text = "".join(["I feel hope", "less about work today"])
    try:
        make_client("staging", router).post("/test/transcript", json={"transcript": user_text})
        sentry_sdk.flush()
    finally:
        sentry_sdk.get_client().close()
        monkeypatch.setattr(observability, "_reporting", False)

    assert len(events) == 1
    frames = events[0]["exception"]["values"][0]["stacktrace"]["frames"]
    assert not any("vars" in frame for frame in frames)
    assert user_text not in json.dumps(events[0], default=str)
