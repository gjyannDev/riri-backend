import httpx2
import pytest
from langchain_core.exceptions import ModelAPIError, ModelRateLimitError, ModelTimeoutError
from langchain_core.messages import AIMessage, UsageMetadata
from langchain_google_genai.chat_models import (
    ChatGoogleGenerativeAIError,
    GoogleInvalidRequestError,
)

from app.coach.llm.llm_response import PROVIDER_ERRORS, read_reply, to_external_error
from app.core.errors import ExternalRateLimitedError, ExternalServiceError, ExternalTimeoutError

# Shapes observed in the step 5 spike (gemini-3.5-flash-lite), with synthetic text.
USAGE = UsageMetadata(input_tokens=11, output_tokens=9, total_tokens=20)


def _reply(
    text: str = "A reply.", usage: UsageMetadata | None = USAGE, **meta: object
) -> AIMessage:
    response_metadata = {"model_provider": "google_genai", "safety_ratings": [], **meta}
    return AIMessage(content=text, usage_metadata=usage, response_metadata=response_metadata)


def test_normal_reply() -> None:
    meta = read_reply(_reply(finish_reason="STOP", normalized_finish_reason="stop"))

    assert (meta.input_tokens, meta.output_tokens) == (11, 9)
    assert not meta.truncated and not meta.blocked and not meta.usage_missing


def test_max_tokens_is_truncated_not_blocked() -> None:
    meta = read_reply(_reply(finish_reason="MAX_TOKENS", normalized_finish_reason="length"))

    assert meta.truncated and not meta.blocked


def test_missing_usage_is_flagged() -> None:
    meta = read_reply(_reply(usage=None, normalized_finish_reason="stop"))

    assert meta.usage_missing
    assert (meta.input_tokens, meta.output_tokens) == (None, None)


@pytest.mark.parametrize(
    ("meta", "reason"),
    [
        ({"finish_reason": "SAFETY", "normalized_finish_reason": "refusal"}, "SAFETY"),
        (
            {"finish_reason": "RECITATION", "normalized_finish_reason": "content_filter"},
            "RECITATION",
        ),
        ({"prompt_feedback": {"block_reason": "PROHIBITED_CONTENT"}}, "PROHIBITED_CONTENT"),
    ],
)
def test_provider_blocks_are_detected_with_their_reason(meta: dict, reason: str) -> None:
    result = read_reply(_reply(**meta))

    assert result.blocked and result.block_reason == reason


def test_an_unset_prompt_block_reason_is_not_a_block() -> None:
    meta = read_reply(_reply(prompt_feedback={"block_reason": 0}, normalized_finish_reason="stop"))

    assert not meta.blocked


@pytest.mark.parametrize("text", ["", "   "])
def test_an_empty_reply_is_blocked(text: str) -> None:
    meta = read_reply(_reply(text=text, normalized_finish_reason="stop"))

    assert meta.blocked and meta.block_reason == "EMPTY"


def test_list_content_from_gemini_is_read_as_text() -> None:
    message = AIMessage(content=[{"type": "text", "text": "Hi."}], usage_metadata=USAGE)

    assert not read_reply(message).blocked


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (ModelTimeoutError("t"), ExternalTimeoutError),
        (httpx2.ConnectTimeout("t"), ExternalTimeoutError),
        (ModelRateLimitError("r"), ExternalRateLimitedError),
        (GoogleInvalidRequestError("bad key"), ExternalServiceError),
        (ModelAPIError("5xx"), ExternalServiceError),
        (ChatGoogleGenerativeAIError("other"), ExternalServiceError),
        (httpx2.ConnectError("down"), ExternalServiceError),
    ],
)
def test_provider_errors_map_to_external_errors(error: Exception, expected: type) -> None:
    assert isinstance(error, PROVIDER_ERRORS)

    mapped = to_external_error(error)

    assert type(mapped) is expected
    body = mapped.marshal()
    assert body["service"] == "llm"
    assert body["detail"] == type(error).__name__


def test_programming_errors_are_not_provider_errors() -> None:
    assert not isinstance(KeyError("user_text"), PROVIDER_ERRORS)
