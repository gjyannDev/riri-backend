
"""Reads vendor-specific reply metadata and errors (Gemini today), shaped by the step 5 spike.

Everything returned here is numbers and short codes, never message text.
"""

from dataclasses import dataclass

import httpx2
from langchain_core.exceptions import ModelError, ModelRateLimitError, ModelTimeoutError
from langchain_core.messages import AIMessage
from langchain_google_genai.chat_models import ChatGoogleGenerativeAIError

from app.core.errors import (
    ExternalBadResponseError,
    ExternalRateLimitedError,
    ExternalServiceError,
    ExternalTimeoutError,
)

SERVICE = "llm"

# Exceptions a model call can raise for provider reasons. Anything else is a bug and propagates.
# google-genai surfaces timeouts and connection failures as raw httpx2 transport errors.
PROVIDER_ERRORS: tuple[type[Exception], ...] = (
    ModelError,
    ChatGoogleGenerativeAIError,
    httpx2.TransportError,
)

_BLOCKING_FINISH_REASONS = frozenset({"refusal", "content_filter"})


@dataclass(frozen=True)
class ReplyMeta:
    input_tokens: int | None
    output_tokens: int | None
    truncated: bool
    block_reason: str | None

    @property
    def blocked(self) -> bool:
        return self.block_reason is not None

    @property
    def usage_missing(self) -> bool:
        return self.input_tokens is None


def read_reply(message: AIMessage) -> ReplyMeta:
    """Usage, truncation and block signal from a complete (merged) streamed reply."""
    usage = message.usage_metadata
    meta = message.response_metadata
    finish = meta.get("normalized_finish_reason")
    prompt_block = (meta.get("prompt_feedback") or {}).get("block_reason")

    block_reason = None
    if finish in _BLOCKING_FINISH_REASONS:
        block_reason = str(meta.get("finish_reason") or finish)
    elif prompt_block:
        block_reason = str(getattr(prompt_block, "name", prompt_block))
    elif not message.text.strip():
        block_reason = "EMPTY"

    return ReplyMeta(
        input_tokens=usage["input_tokens"] if usage else None,
        output_tokens=usage["output_tokens"] if usage else None,
        truncated=finish == "length",
        block_reason=block_reason,
    )


def to_external_error(error: Exception) -> ExternalServiceError:
    """Map a provider exception to the app's `external` error. The detail names the type only."""
    detail = type(error).__name__
    if isinstance(error, (ModelTimeoutError, httpx2.TimeoutException, TimeoutError)):
        return ExternalTimeoutError(detail, service=SERVICE)
    if isinstance(error, ModelRateLimitError):
        return ExternalRateLimitedError(detail, service=SERVICE)
    return ExternalServiceError(detail, service=SERVICE)


def blocked_error(reply: ReplyMeta) -> ExternalServiceError:
    return ExternalBadResponseError(f"blocked: {reply.block_reason}", service=SERVICE)
