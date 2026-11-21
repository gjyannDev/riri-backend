from pydantic import Field, PostgresDsn
from pydantic_settings import BaseSettings

from app.core.config.base import env_config


class DatabaseSettings(BaseSettings):
    """Read from DATABASE_URL, e.g. postgresql+psycopg://user:password@127.0.0.1:5433/dbname."""

    model_config = env_config("DATABASE_")

    # Required: no safe default holds a password. repr=False keeps it out of reprs and logs.
    url: PostgresDsn = Field(repr=False)
