import json
import os
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr
from structlog.testing import capture_logs

from app.coach import coach_factory
from app.coach.coach_factory import CoachConfigError, build_coach, text_capture_enabled
from app.coach.conversation.coach import GREETING, Coach
from app.coach.prompts.prompt_registry import PromptRegistryError
from app.coach.tracing import tracing_factory
from app.coach.tracing.tracing_masking import mask_otel_spans, mask_otel_spans_keeping_text
from app.core.config import Settings, settings
from app.core.config.langfuse import LangfuseSettings
from app.core.config.llm import LLMSettings
from tests.fakes.fake_tracing import FakeTracing
from tests.fakes.spy_chat_model import SpyChatModel

KEY = "leak-canary-api-key"
LANGFUSE_SECRET = "sk-leak-canary-langfuse"


def _settings(langfuse: dict[str, Any] | None = None, **llm: Any) -> Settings:
    values: dict[str, Any] = {"model": "gemini-test", "api_key": SecretStr(KEY)} | llm
    tracing: dict[str, Any] = {"enabled": False} | (langfuse or {})
    return settings.model_copy(
        update={
            "llm": LLMSettings.model_construct(**values),
            "langfuse": LangfuseSettings.model_construct(**tracing),
        }
    )


@pytest.fixture
def spy_model(monkeypatch: pytest.MonkeyPatch) -> SpyChatModel:
    model = SpyChatModel.scripted("Hello.")
    monkeypatch.setattr(coach_factory, "build_chat_model", lambda llm: model)
    return model


@pytest.mark.parametrize(
    ("llm", "setting"),
    [
        ({"model": None}, "LLM_MODEL"),
        ({"model": ""}, "LLM_MODEL"),
        ({"api_key": None}, "LLM_API_KEY"),
        ({"api_key": SecretStr("")}, "LLM_API_KEY"),
    ],
)
def test_missing_setting_is_named_without_the_key(
    spy_model: SpyChatModel, llm: dict, setting: str
) -> None:
    with pytest.raises(CoachConfigError, match=setting) as error:
        build_coach(_settings(**llm))

    assert KEY not in str(error.value)
    assert spy_model.received == []


def test_a_broken_registry_stops_the_build(spy_model: SpyChatModel, tmp_path: Path) -> None:
    broken = tmp_path / "prompt_registry.json"
    broken.write_text(json.dumps({"active_set": "missing", "blocks": {}, "sets": {}}))

    with pytest.raises(PromptRegistryError, match="missing"):
        build_coach(_settings(), registry_path=broken)


def test_valid_settings_give_a_working_coach(spy_model: SpyChatModel) -> None:
    coach = build_coach(_settings())

    assert isinstance(coach, Coach)
    assert coach.history[0].text == GREETING
    assert "".join(coach.respond("hi")) == "Hello."


ENABLED = {
    "enabled": True,
    "public_key": SecretStr("pk-lf-test"),
    "secret_key": SecretStr(LANGFUSE_SECRET),
    "base_url": "http://127.0.0.1:9",
}


@pytest.mark.parametrize("value", ["true", "1", "false"])
def test_building_a_coach_forces_langsmith_off(
    spy_model: SpyChatModel, monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    for name in ("LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2"):
        monkeypatch.setenv(name, value)

    build_coach(_settings())

    assert os.environ["LANGSMITH_TRACING"] == "false"
    assert os.environ["LANGCHAIN_TRACING_V2"] == "false"


def test_langsmith_is_forced_off_even_when_the_build_fails(
    spy_model: SpyChatModel, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")

    with pytest.raises(CoachConfigError):
        build_coach(_settings(model=None))

    assert os.environ["LANGSMITH_TRACING"] == "false"
    assert os.environ["LANGCHAIN_TRACING_V2"] == "false"


def test_tracing_is_not_built_when_disabled_even_with_keys(
    spy_model: SpyChatModel, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("a Langfuse client was created while tracing is disabled")

    monkeypatch.setattr(tracing_factory, "Langfuse", boom)

    coach = build_coach(_settings(langfuse=ENABLED | {"enabled": False}))

    assert "".join(coach.respond("hi")) == "Hello."


@pytest.mark.parametrize(
    ("environment", "expected_mask"),
    [("production", mask_otel_spans), ("local", mask_otel_spans_keeping_text)],
)
def test_enabled_tracing_is_built_with_the_mask_for_its_environment(
    spy_model: SpyChatModel,
    monkeypatch: pytest.MonkeyPatch,
    environment: str,
    expected_mask: Any,
) -> None:
    created: list[dict[str, Any]] = []

    class RecordingClient:
        def __init__(self, **kwargs: Any) -> None:
            created.append(kwargs)

    monkeypatch.setattr(tracing_factory, "Langfuse", RecordingClient)

    build_coach(_settings(langfuse=ENABLED).model_copy(update={"ENVIRONMENT": environment}))

    (kwargs,) = created
    assert kwargs["public_key"] == "pk-lf-test"
    assert kwargs["secret_key"] == LANGFUSE_SECRET
    assert kwargs["base_url"] == "http://127.0.0.1:9"
    assert kwargs["mask_otel_spans"] is expected_mask


def test_the_built_coach_traces_through_what_the_factory_built(
    spy_model: SpyChatModel, monkeypatch: pytest.MonkeyPatch
) -> None:
    tracing = FakeTracing()
    monkeypatch.setattr(coach_factory, "build_tracing", lambda langfuse, **options: tracing)

    coach = build_coach(_settings(langfuse=ENABLED))
    "".join(coach.respond("hi"))
    coach.close()

    assert len(tracing.starts) == 1
    assert tracing.closed == 1


@pytest.mark.parametrize(
    ("langfuse", "setting"),
    [
        ({"public_key": None}, "LANGFUSE_PUBLIC_KEY"),
        ({"secret_key": SecretStr("")}, "LANGFUSE_SECRET_KEY"),
        ({"secret_key": SecretStr("  ")}, "LANGFUSE_SECRET_KEY"),
    ],
)
def test_enabled_tracing_with_a_missing_key_stops_the_build_without_values(
    spy_model: SpyChatModel, langfuse: dict[str, Any], setting: str
) -> None:
    with pytest.raises(CoachConfigError, match=setting) as error:
        build_coach(_settings(langfuse=ENABLED | langfuse))

    assert LANGFUSE_SECRET not in str(error.value)
    assert KEY not in str(error.value)
    assert spy_model.received == []


def test_explicit_text_capture_is_refused_in_production(spy_model: SpyChatModel) -> None:
    built = _settings(langfuse=ENABLED | {"capture_text": True})
    production = built.model_copy(update={"ENVIRONMENT": "production"})

    with pytest.raises(CoachConfigError, match="LANGFUSE_CAPTURE_TEXT") as error:
        build_coach(production)

    assert "ENVIRONMENT" in str(error.value)
    assert LANGFUSE_SECRET not in str(error.value)
    assert spy_model.received == []


@pytest.mark.parametrize(
    ("environment", "capture_text", "expected"),
    [
        ("local", None, True),
        ("staging", None, True),
        ("production", None, False),
        ("local", False, False),
        ("staging", False, False),
        ("local", True, True),
        ("staging", True, True),
    ],
)
def test_text_capture_follows_the_environment_unless_set_explicitly(
    spy_model: SpyChatModel,
    monkeypatch: pytest.MonkeyPatch,
    environment: str,
    capture_text: bool | None,
    expected: bool,
) -> None:
    seen: list[bool] = []

    def record(langfuse: Any, *, capture_text: bool = False) -> None:
        seen.append(capture_text)

    monkeypatch.setattr(coach_factory, "build_tracing", record)
    langfuse = ENABLED | ({} if capture_text is None else {"capture_text": capture_text})
    built = _settings(langfuse=langfuse).model_copy(update={"ENVIRONMENT": environment})

    build_coach(built)

    assert seen == [expected]
    assert text_capture_enabled(built) is expected


def test_text_capture_without_tracing_is_harmless_in_any_environment(
    spy_model: SpyChatModel,
) -> None:
    quiet = _settings(langfuse={"enabled": False, "capture_text": True}).model_copy(
        update={"ENVIRONMENT": "production"}
    )

    assert isinstance(build_coach(quiet), Coach)


@pytest.mark.parametrize(
    ("environment", "capture_text", "warned"),
    [
        ("local", None, True),
        ("staging", None, True),
        ("local", True, True),
        ("production", None, False),
        ("local", False, False),
    ],
)
def test_active_text_capture_is_announced_once_on_every_door_without_text(
    spy_model: SpyChatModel,
    monkeypatch: pytest.MonkeyPatch,
    environment: str,
    capture_text: bool | None,
    warned: bool,
) -> None:
    monkeypatch.setattr(coach_factory, "build_tracing", lambda langfuse, **options: None)
    langfuse = ENABLED | ({} if capture_text is None else {"capture_text": capture_text})
    built = _settings(langfuse=langfuse).model_copy(update={"ENVIRONMENT": environment})

    with capture_logs() as logs:
        build_coach(built)

    events = [entry for entry in logs if entry["event"] == "tracing_text_capture_active"]
    assert len(events) == (1 if warned else 0)
    if warned:
        assert events[0]["environment"] == environment
        assert events[0]["log_level"] == "warning"
    assert LANGFUSE_SECRET not in str(logs)


def test_no_announcement_when_tracing_is_off(
    spy_model: SpyChatModel, monkeypatch: pytest.MonkeyPatch
) -> None:
    with capture_logs() as logs:
        build_coach(_settings(langfuse={"enabled": False}))

    assert [e for e in logs if e["event"] == "tracing_text_capture_active"] == []
