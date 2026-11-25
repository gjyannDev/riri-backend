"""Chat model factory: the only place a chat model is built from settings."""

from dataclasses import dataclass
from typing import Any

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel

from app.core.config.llm import LLMSettings


@dataclass(frozen=True)
class ModelInfo:
    """What the model was configured with, for the llm_call event. Never a secret."""

    name: str
    temperature: float
    thinking_level: str | None


def model_info(llm: LLMSettings) -> ModelInfo:
    thinking_level = llm.thinking_level if llm.provider == "google_genai" else None
    return ModelInfo(
        name=llm.model or "", temperature=llm.temperature, thinking_level=thinking_level
    )


def build_chat_model(llm: LLMSettings) -> BaseChatModel:
    if llm.model is None or llm.api_key is None:
        raise ValueError("LLM model and API key are required; build_coach() checks them first.")
    # Gemini 3.x rejects thinking_budget and takes thinking_level; other vendors don't know it.
    vendor_options: dict[str, Any] = (
        {"thinking_level": llm.thinking_level} if llm.provider == "google_genai" else {}
    )
    return init_chat_model(
        llm.model,
        model_provider=llm.provider,
        api_key=llm.api_key.get_secret_value(),
        timeout=llm.timeout_s,
        max_tokens=llm.max_tokens,
        max_retries=llm.max_retries,
        temperature=llm.temperature,
        **vendor_options,
    )
