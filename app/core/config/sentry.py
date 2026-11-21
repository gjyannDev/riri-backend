from pydantic import SecretStr
from pydantic_settings import BaseSettings

from app.core.config.base import env_config


class SentrySettings(BaseSettings):
    """Read from SENTRY_DSN and SENTRY_ENABLED. SENTRY_ENABLED=false turns Sentry off, DSN kept."""

    model_config = env_config("SENTRY_")

    dsn: SecretStr | None = None
    enabled: bool = True

    @property
    def active(self) -> bool:
        return self.enabled and self.dsn is not None
