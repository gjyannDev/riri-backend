import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr

from app.coach import coach_factory
from app.coach.coach_factory import CoachConfigError, build_coach
from app.coach.conversation.coach import GREETING, Coach
from app.coach.prompts.prompt_registry import PromptRegistryError
from app.core.config import Settings, settings
from app.core.config.llm import LLMSettings
from tests.fakes.spy_chat_model import SpyChatModel

KEY = "leak-canary-api-key"


def _settings(**llm: Any) -> Settings:
    values: dict[str, Any] = {"model": "gemini-test", "api_key": SecretStr(KEY)} | llm
    return settings.model_copy(update={"llm": LLMSettings.model_construct(**values)})


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
