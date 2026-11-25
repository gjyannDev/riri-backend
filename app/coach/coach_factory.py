"""Composition root for the engine: every door (CLI, voice, HTTP) builds its coach here."""

from pathlib import Path

import structlog

from app.coach.conversation.coach import Coach
from app.coach.llm.model_factory import build_chat_model, model_info
from app.coach.prompts.prompt_registry import DEFAULT_REGISTRY_PATH, compile_active_set
from app.coach.tracing.tracing_factory import (
    TracingConfigError,
    build_tracing,
    force_langsmith_off,
)
from app.core.config import Settings

_TEXT_CAPTURE_ENVIRONMENTS = ("local", "staging")

log = structlog.get_logger("app.coach")


class CoachConfigError(Exception):
    """A required setting is missing. The message names the setting, never its value."""


def text_capture_enabled(settings: Settings) -> bool:
    """Whether message text may reach the tracing tool: on in local and staging, off in production.

    `LANGFUSE_CAPTURE_TEXT` overrides the environment default in either direction.
    """
    explicit = settings.langfuse.capture_text
    if explicit is not None:
        return explicit
    return settings.ENVIRONMENT in _TEXT_CAPTURE_ENVIRONMENTS


def build_coach(settings: Settings, registry_path: Path = DEFAULT_REGISTRY_PATH) -> Coach:
    """Validate settings, load and compile the prompt registry, build the model and tracing.

    Raises `CoachConfigError` or `PromptRegistryError` before any model call. LangSmith is forced
    off first, on every path, so no door can leave it on.
    """
    force_langsmith_off()
    llm = settings.llm
    if not llm.model:
        raise CoachConfigError(
            "LLM_MODEL is not set. Add it to .env (.env.example shows an example)."
        )
    if llm.api_key is None or not llm.api_key.get_secret_value():
        raise CoachConfigError(
            "LLM_API_KEY is not set. Add your Google AI Studio key to .env as LLM_API_KEY."
        )
    prompt = compile_active_set(registry_path)
    langfuse = settings.langfuse
    capture_text = text_capture_enabled(settings)
    if langfuse.enabled and capture_text and settings.ENVIRONMENT not in _TEXT_CAPTURE_ENVIRONMENTS:
        raise CoachConfigError(
            "LANGFUSE_CAPTURE_TEXT=true is not allowed when ENVIRONMENT=production. "
            "Remove it or set it to false."
        )
    try:
        tracing = build_tracing(langfuse, capture_text=capture_text)
    except TracingConfigError as error:
        raise CoachConfigError(str(error)) from None
    if langfuse.enabled and capture_text:
        # Every door sees this, not only the CLI banner. Environment only: never any text.
        log.warning("tracing_text_capture_active", environment=settings.ENVIRONMENT)
    return Coach(build_chat_model(llm), prompt, model_info(llm), tracing=tracing)
