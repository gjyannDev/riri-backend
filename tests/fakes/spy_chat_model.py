"""A scripted chat model that records every message list it receives. No network, no key."""

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, UsageMetadata
from langchain_core.outputs import ChatGenerationChunk
from pydantic import Field

STOP = {"finish_reason": "STOP", "normalized_finish_reason": "stop"}
TRUNCATED = {"finish_reason": "MAX_TOKENS", "normalized_finish_reason": "length"}
REFUSED = {"finish_reason": "SAFETY", "normalized_finish_reason": "refusal"}


def usage(input_tokens: int = 100, output_tokens: int = 20) -> UsageMetadata:
    return UsageMetadata(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
    )


@dataclass
class Reply:
    """One scripted model reply, shaped like Gemini's stream (see step 5 spike findings)."""

    text: str = "That sounds really hard."
    usage: UsageMetadata | None = field(default_factory=usage)
    metadata: dict[str, Any] = field(default_factory=lambda: dict(STOP))


class SpyChatModel(GenericFakeChatModel):
    """Streams each scripted step in order: a `Reply`, a plain string, or an exception to raise."""

    messages: Iterator[AIMessage | str] = Field(default_factory=lambda: iter([]))
    script: list[Any] = Field(default_factory=list)
    received: list[list[BaseMessage]] = Field(default_factory=list)

    @classmethod
    def scripted(cls, *steps: Reply | str | BaseException) -> SpyChatModel:
        return cls(script=list(steps))

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        self.received.append(list(messages))
        step = self.script.pop(0)
        if isinstance(step, BaseException):
            raise step
        reply = step if isinstance(step, Reply) else Reply(step)
        self.messages = iter([AIMessage(reply.text)])
        if reply.text:
            yield from super()._stream(messages, stop, run_manager, **kwargs)
        # Gemini sends usage and the finish reason on a trailing chunk with no text.
        # model_validate, not keyword arguments: Pylance rejects AIMessageChunk(content=...).
        trailer = AIMessageChunk.model_validate(
            {
                "content": "",
                "usage_metadata": reply.usage,
                "response_metadata": reply.metadata,
            }
        )
        yield ChatGenerationChunk(message=trailer)
