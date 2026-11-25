from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings

from app.core.config.base import env_config


class LLMSettings(BaseSettings):
    """Read from LLM_*. Model and key may be absent at load; build_coach() requires them."""

    model_config = env_config("LLM_")

    provider: str = "google_genai"
    model: str | None = None
    api_key: SecretStr | None = None
    timeout_s: float = 30.0
    max_tokens: int = 512
    max_retries: int = 2
    temperature: float = 0.7
    # Gemini 3.x only. "minimal" keeps TTFT lowest; the factory sends it only for google_genai.
    thinking_level: Literal["minimal", "low", "medium", "high"] = "minimal"
