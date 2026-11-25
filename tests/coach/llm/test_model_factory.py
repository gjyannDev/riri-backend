import pytest
from pydantic import SecretStr

from app.coach.llm import model_factory
from app.core.config.llm import LLMSettings


def _settings(**overrides: object) -> LLMSettings:
    values = {"model": "gemini-test", "api_key": SecretStr("test-key"), **overrides}
    return LLMSettings.model_construct(**(LLMSettings().model_dump() | values))


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    recorded: list[dict] = []

    def fake_init_chat_model(model: str, **kwargs: object) -> str:
        recorded.append({"model": model, **kwargs})
        return "model"

    monkeypatch.setattr(model_factory, "init_chat_model", fake_init_chat_model)
    return recorded


def test_gemini_gets_every_setting_plus_thinking_level(calls: list[dict]) -> None:
    model_factory.build_chat_model(_settings(thinking_level="low", temperature=0.3))

    assert calls == [
        {
            "model": "gemini-test",
            "model_provider": "google_genai",
            "api_key": "test-key",
            "timeout": 30.0,
            "max_tokens": 512,
            "max_retries": 2,
            "temperature": 0.3,
            "thinking_level": "low",
        }
    ]


def test_other_vendors_do_not_get_thinking_level(calls: list[dict]) -> None:
    model_factory.build_chat_model(_settings(provider="openai"))

    assert "thinking_level" not in calls[0]
    assert calls[0]["model_provider"] == "openai"


def test_a_real_gemini_model_builds_without_network() -> None:
    model = model_factory.build_chat_model(_settings())

    assert type(model).__name__ == "ChatGoogleGenerativeAI"
    assert model.thinking_level == "minimal"  # type: ignore[attr-defined]


def test_missing_model_or_key_is_refused(calls: list[dict]) -> None:
    with pytest.raises(ValueError, match="required"):
        model_factory.build_chat_model(_settings(api_key=None))
    assert calls == []
