"""Composition root for the engine: every door (CLI, voice, HTTP) builds its coach here."""

from pathlib import Path

from app.coach.conversation.coach import Coach
from app.coach.llm.model_factory import build_chat_model, model_info
from app.coach.prompts.prompt_registry import DEFAULT_REGISTRY_PATH, compile_active_set
from app.core.config import Settings


class CoachConfigError(Exception):
    """A required setting is missing. The message names the setting, never its value."""


def build_coach(settings: Settings, registry_path: Path = DEFAULT_REGISTRY_PATH) -> Coach:
    """Validate settings, load and compile the prompt registry, build the model.

    Raises `CoachConfigError` or `PromptRegistryError` before any model call.
    """
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
    return Coach(build_chat_model(llm), prompt, model_info(llm))
