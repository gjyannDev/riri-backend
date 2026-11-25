from urllib.parse import urlparse

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings

from app.core.config.base import env_config

_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


class LangfuseSettings(BaseSettings):
    """Read from LANGFUSE_*. Keys alone never start tracing: LANGFUSE_ENABLED must be true.

    Keys may be absent at load; build_coach() requires them when tracing is enabled.
    """

    model_config = env_config("LANGFUSE_")

    enabled: bool = False
    public_key: SecretStr | None = None
    secret_key: SecretStr | None = None
    base_url: str = "https://cloud.langfuse.com"
    # Text capture sends input and output text to Langfuse. Unset: on in local and staging, off in
    # production. false: off everywhere. true: refused in production (see build_coach()).
    capture_text: bool | None = None

    @field_validator("base_url")
    @classmethod
    def _https_unless_local(cls, value: str) -> str:
        """The keys and traces travel to this URL, so it must be encrypted (http only for local)."""
        parsed = urlparse(value)
        if parsed.hostname and (
            parsed.scheme == "https"
            or (parsed.scheme == "http" and parsed.hostname in _LOCAL_HOSTS)
        ):
            return value
        raise ValueError("must be an https URL (plain http only for localhost)")
