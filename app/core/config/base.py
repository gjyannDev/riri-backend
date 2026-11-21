from pathlib import Path

from pydantic_settings import SettingsConfigDict

# Project root (riri-backend/), so .env is found regardless of the working directory.
BASE_DIR = Path(__file__).resolve().parents[3]
ENV_FILE = BASE_DIR / ".env"


def env_config(prefix: str = "") -> SettingsConfigDict:
    """Shared settings config. Real environment variables take precedence over values in .env."""
    return SettingsConfigDict(
        env_prefix=prefix,
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
        # Each group sees the whole .env; without this a load error prints every value in it.
        hide_input_in_errors=True,
    )
