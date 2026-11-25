"""The coach: one respond operation over a streamed chat model, with in-memory history.

No web, terminal or audio code. Logs numbers only, never user, reply or prompt text.
"""

import time
import uuid
from collections.abc import Callable, Generator
from typing import Any, cast

import structlog
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, HumanMessage
from langchain_core.runnables import RunnableConfig

from app.coach.conversation.turn_stats import TurnStats
from app.coach.llm.llm_response import (
    PROVIDER_ERRORS,
    ReplyMeta,
    blocked_error,
    read_reply,
    to_external_error,
)
from app.coach.llm.model_factory import ModelInfo
from app.coach.prompts.prompt_registry import CompiledPrompt
from app.coach.tracing.tracing_call import TracedCall, Tracing, UntracedCall

GREETING = "Hi, I'm Riri, an AI skills coach, not a therapist. What's on your mind today?"
FALLBACK_LINE = "I'm having trouble right now. Give me a moment and try again."

log = structlog.get_logger("app.coach")


def _new_session_id() -> str:
    """Random, never derived from text or a user; groups one conversation's traces."""
    return uuid.uuid4().hex


def _ms(seconds: float) -> float:
    return round(seconds * 1000, 1)


class Coach:
    def __init__(
        self,
        model: BaseChatModel,
        prompt: CompiledPrompt,
        info: ModelInfo,
        clock: Callable[[], float] = time.perf_counter,
        tracing: Tracing | None = None,
    ) -> None:
        self._chain = prompt.template | model
        self._prompt = prompt
        self._info = info
        self._clock = clock
        self._tracing = tracing
        self._session_id = _new_session_id()
        self._history: list[BaseMessage] = [AIMessage(GREETING)]
        self._stats: list[TurnStats] = []

    @property
    def history(self) -> tuple[BaseMessage, ...]:
        return tuple(self._history)

    def stats(self) -> tuple[TurnStats, ...]:
        return tuple(self._stats)

    def reset(self) -> None:
        self._history = [AIMessage(GREETING)]
        self._stats = []
        self._session_id = _new_session_id()

    def close(self) -> None:
        """Send pending traces before the process exits. Safe to call without tracing."""
        if self._tracing is not None:
            self._tracing.close()

    def respond(self, text: str) -> Generator[str]:
        """Stream the reply. History changes only after the whole reply has arrived.

        Closing the iterator early (Ctrl-C) keeps nothing. Provider failures and blocked or
        empty replies raise an `external` error. Exactly one `llm_call` event is logged per call,
        with outcome ok, cancelled, failed, blocked, or error for an unexpected bug.
        """
        turn = len(self._stats) + 1
        call = self._start_call(turn)
        start = self._clock()
        # Anything that ends the call without setting its own outcome is a bug, not a cancel.
        level, event = "error", {"outcome": "error"}
        try:
            final, ttft = yield from self._stream(text, start, call.config)
            meta = read_reply(final)
            event = _reply_fields(meta)
            if meta.blocked:
                level, event["outcome"] = "warning", "blocked"
                raise blocked_error(meta)
            stats = TurnStats(
                turn=turn,
                ttft_ms=_ms(ttft) if ttft is not None else None,
                total_ms=_ms(self._clock() - start),
                input_tokens=meta.input_tokens,
                output_tokens=meta.output_tokens,
                truncated=meta.truncated,
            )
            self._history += [HumanMessage(text), AIMessage(final.text)]
            self._stats.append(stats)
            level, event = (
                "info",
                event
                | {
                    "outcome": "ok",
                    "ttft_ms": stats.ttft_ms,
                    "total_ms": stats.total_ms,
                },
            )
        except GeneratorExit, KeyboardInterrupt:
            level, event = "info", {"outcome": "cancelled"}
            raise
        except PROVIDER_ERRORS as error:
            external = to_external_error(error)
            level = "error"
            event = {
                "outcome": "failed",
                "error_code": external.code,
                "error_type": type(error).__name__,
                "category": external.category.value,
            }
            # `from None`: the provider's message never travels with the error to logs or Sentry.
            raise external from None
        finally:
            call.finish(event["outcome"])
            getattr(log, level)("llm_call", **self._call_fields(turn, len(text)), **event)

    def _start_call(self, turn: int) -> TracedCall:
        if self._tracing is None:
            return UntracedCall()
        fields = self._call_fields(turn, 0)
        metadata = {k: v for k, v in fields.items() if k != "input_chars" and v is not None}
        return self._tracing.start_call(session_id=self._session_id, metadata=metadata)

    def _stream(
        self, text: str, start: float, config: RunnableConfig
    ) -> Generator[str, None, tuple[AIMessage, float | None]]:
        """Yield reply text as it arrives; return the merged reply and the time to first token."""
        reply: AIMessageChunk | None = None
        ttft: float | None = None
        inputs = {"history": self._history, "user_text": text}
        for chunk in self._chain.stream(inputs, config=config or None):
            # Chunks are AIMessageChunk at runtime; LangChain types `+` and the chain output wider.
            reply = cast(AIMessageChunk, chunk if reply is None else reply + chunk)
            if chunk.text:
                if ttft is None:
                    ttft = self._clock() - start
                yield chunk.text
        return reply or AIMessage(""), ttft

    def _call_fields(self, turn: int, input_chars: int) -> dict[str, Any]:
        return {
            "prompt_version": self._prompt.version,
            "prompt_hash": self._prompt.hash,
            "model": self._info.name,
            "temperature": self._info.temperature,
            "thinking_level": self._info.thinking_level,
            "turn": turn,
            "input_chars": input_chars,
        }


def _reply_fields(meta: ReplyMeta) -> dict[str, Any]:
    return {
        "input_tokens": meta.input_tokens,
        "output_tokens": meta.output_tokens,
        "truncated": meta.truncated,
        "usage_missing": meta.usage_missing,
        "blocked": meta.blocked,
        "block_reason": meta.block_reason,
    }
