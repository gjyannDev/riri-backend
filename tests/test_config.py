from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from app.core.config import load_settings

APP_VARS = ("PROJECT_NAME", "ENVIRONMENT", "API_V1_PREFIX", "BACKEND_CORS_ORIGINS")
LLM_VARS = tuple(
    f"LLM_{name}"
    for name in (
        "PROVIDER",
        "MODEL",
        "API_KEY",
        "TIMEOUT_S",
        "MAX_TOKENS",
        "MAX_RETRIES",
        "TEMPERATURE",
        "THINKING_LEVEL",
    )
)
TEST_URL = "postgresql+psycopg://riri:secret@db.example:6543/riri_test"


@pytest.fixture
def env_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Temporary .env with real env vars cleared, so the real .env is never read."""
    for name in (*APP_VARS, *LLM_VARS, "DATABASE_URL", "LOG_LEVEL", "SENTRY_DSN", "SENTRY_ENABLED"):
        monkeypatch.delenv(name, raising=False)

    def write(**values: str) -> Path:
        values = {"DATABASE_URL": TEST_URL, **values}
        path = tmp_path / ".env"
        path.write_text("".join(f"{key}={value}\n" for key, value in values.items()))
        return path

    return write


def test_database_url_is_read_from_one_variable(env_file) -> None:
    settings = load_settings(env_file())

    assert str(settings.db.url) == TEST_URL


def test_missing_database_url_is_rejected_at_load(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    path = tmp_path / ".env"
    path.write_text("PROJECT_NAME=leak-canary\n")

    with pytest.raises(ValidationError, match="url") as error:
        load_settings(path)

    assert "leak-canary" not in str(error.value), "load errors must not echo .env values"


def test_non_postgres_database_url_is_rejected_at_load(env_file) -> None:
    with pytest.raises(ValidationError):
        load_settings(env_file(DATABASE_URL="mysql://riri:secret@localhost/riri"))


def test_app_level_settings_stay_on_the_root(env_file) -> None:
    path = env_file(
        PROJECT_NAME="Riri Test",
        ENVIRONMENT="staging",
        API_V1_PREFIX="/api/v2",
        BACKEND_CORS_ORIGINS='["http://localhost:3000"]',
    )

    settings = load_settings(path)

    assert settings.PROJECT_NAME == "Riri Test"
    assert settings.ENVIRONMENT == "staging"
    assert settings.API_V1_PREFIX == "/api/v2"
    assert settings.BACKEND_CORS_ORIGINS == ["http://localhost:3000"]


def test_database_password_stays_out_of_reprs(env_file) -> None:
    url = "postgresql+psycopg://riri:hunter2@localhost:5433/riri"
    settings = load_settings(env_file(DATABASE_URL=url))

    assert "hunter2" not in repr(settings)
    assert "hunter2" not in str(settings.db)


def test_env_with_only_a_database_url_loads_with_defaults(env_file) -> None:
    settings = load_settings(env_file())

    assert settings.ENVIRONMENT == "local"
    assert settings.log.level == "INFO"
    assert settings.sentry.dsn is None
    assert settings.sentry.enabled is True
    assert settings.sentry.active is False


def test_log_level_is_read_case_insensitively(env_file) -> None:
    assert load_settings(env_file(LOG_LEVEL="debug")).log.level == "DEBUG"


def test_invalid_log_level_is_rejected_at_load(env_file) -> None:
    with pytest.raises(ValidationError):
        load_settings(env_file(LOG_LEVEL="verbose"))


def test_sentry_is_active_when_a_dsn_is_set(env_file) -> None:
    settings = load_settings(env_file(SENTRY_DSN="https://key@o0.ingest.sentry.io/1"))

    assert isinstance(settings.sentry.dsn, SecretStr)
    assert settings.sentry.active is True
    assert "key@" not in repr(settings)


def test_sentry_can_be_switched_off_without_removing_the_dsn(env_file) -> None:
    path = env_file(SENTRY_DSN="https://key@o0.ingest.sentry.io/1", SENTRY_ENABLED="false")

    settings = load_settings(path)

    assert settings.sentry.dsn is not None
    assert settings.sentry.active is False


def test_llm_settings_are_read_from_the_env_file(env_file) -> None:
    path = env_file(
        LLM_PROVIDER="google_genai",
        LLM_MODEL="gemini-flash-test",
        LLM_API_KEY="test-key",
        LLM_TIMEOUT_S="12.5",
        LLM_MAX_TOKENS="300",
        LLM_MAX_RETRIES="1",
        LLM_TEMPERATURE="0.4",
        LLM_THINKING_LEVEL="low",
    )

    llm = load_settings(path).llm

    assert llm.provider == "google_genai"
    assert llm.model == "gemini-flash-test"
    assert llm.api_key is not None and llm.api_key.get_secret_value() == "test-key"
    assert llm.timeout_s == 12.5
    assert llm.max_tokens == 300
    assert llm.max_retries == 1
    assert llm.temperature == 0.4
    assert llm.thinking_level == "low"


def test_llm_settings_load_without_model_or_key(env_file) -> None:
    llm = load_settings(env_file()).llm

    assert llm.model is None
    assert llm.api_key is None
    assert llm.provider == "google_genai"


def test_llm_api_key_stays_out_of_reprs(env_file) -> None:
    settings = load_settings(env_file(LLM_API_KEY="leak-canary-key"))

    assert isinstance(settings.llm.api_key, SecretStr)
    assert "leak-canary-key" not in repr(settings)
    assert "leak-canary-key" not in str(settings.llm)


def test_thinking_level_defaults_to_minimal(env_file) -> None:
    assert load_settings(env_file()).llm.thinking_level == "minimal"
    assert load_settings(env_file(LLM_THINKING_LEVEL="")).llm.thinking_level == "minimal"


def test_unknown_thinking_level_is_rejected_at_load(env_file) -> None:
    with pytest.raises(ValidationError):
        load_settings(env_file(LLM_THINKING_LEVEL="max"))
