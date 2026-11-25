from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import Field
from pydantic_settings import BaseSettings

from app.core.config.base import ENV_FILE, env_config
from app.core.config.database import DatabaseSettings
from app.core.config.langfuse import LangfuseSettings
from app.core.config.llm import LLMSettings
from app.core.config.log import LogSettings
from app.core.config.sentry import SentrySettings


class Settings(BaseSettings):
    """App-level settings at the top, one group per concern below."""

    model_config = env_config()

    PROJECT_NAME: str = "Riri Backend"
    ENVIRONMENT: Literal["local", "staging", "production"] = "local"
    API_V1_PREFIX: str = "/api/v1"
    BACKEND_CORS_ORIGINS: list[str] = []

    # Required fields (DATABASE_URL) come from the environment, which type checkers can't see.
    db: DatabaseSettings = Field(default_factory=DatabaseSettings)  # pyright: ignore[reportArgumentType]
    log: LogSettings = Field(default_factory=LogSettings)
    sentry: SentrySettings = Field(default_factory=SentrySettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    langfuse: LangfuseSettings = Field(default_factory=LangfuseSettings)


def _from_env_file[T: BaseSettings](cls: type[T], env_file: Path | None, **values: Any) -> T:
    # `_env_file` is pydantic-settings' documented init argument, but type checkers only see the
    # field-based __init__ that pydantic generates for subclasses, so it can't be typed here.
    return cls(_env_file=env_file, **values)  # pyright: ignore[reportCallIssue]


def load_settings(env_file: Path | None = ENV_FILE) -> Settings:
    """Build settings with every group reading the same env file (tests pass a temporary one)."""
    return _from_env_file(
        Settings,
        env_file,
        db=_from_env_file(DatabaseSettings, env_file),
        log=_from_env_file(LogSettings, env_file),
        sentry=_from_env_file(SentrySettings, env_file),
        llm=_from_env_file(LLMSettings, env_file),
        langfuse=_from_env_file(LangfuseSettings, env_file),
    )


@lru_cache
def get_settings() -> Settings:
    return load_settings()


settings = get_settings()
