from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings

from app.core.config.base import env_config


class LogSettings(BaseSettings):
    """Read from LOG_LEVEL. Console vs JSON output follows ENVIRONMENT, not a setting."""

    model_config = env_config("LOG_")

    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    @field_validator("level", mode="before")
    @classmethod
    def _upper(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value
