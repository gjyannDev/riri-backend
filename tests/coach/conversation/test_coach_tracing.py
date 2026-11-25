"""The privacy gate: a real Langfuse client and handler, a fake sink, a sentinel in all text.

Nothing the sink receives may contain conversation, reply, prompt or error text, whatever the
outcome. These tests go through the same path production uses; only the network sender is fake.
"""

import contextlib
import json
import threading
import time
import uuid
from collections.abc import Sequence
from typing import Any

import pytest
from langchain_core.exceptions import ModelRateLimitError
from langfuse import Langfuse
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExportResult
from pydantic import SecretStr

from app.coach.conversation.coach import Coach
from app.coach.llm.model_factory import ModelInfo
from app.coach.prompts.prompt_registry import DEFAULT_REGISTRY_PATH, compile_active_set
from app.coach.tracing import tracing_factory
from app.coach.tracing.tracing_factory import LangfuseTracing, build_tracing
from app.core.config.langfuse import LangfuseSettings
from app.core.errors import ExternalServiceError
from tests.fakes.memory_span_sink import MemorySpanSink
from tests.fakes.spy_chat_model import REFUSED, STOP, Reply, SpyChatModel

SENTINEL = "SENTINEL-7f3a"
PROMPT = compile_active_set(DEFAULT_REGISTRY_PATH)
INFO = ModelInfo(name="gemini-test", temperature=0.7, thinking_level="minimal")
PROMPT_TEXT_SNIPPETS = ("CONVERSATION PRINCIPLES", "You are Riri")


def _tracing(
    sink: MemorySpanSink, *, capture_text: bool = False, **options: Any
) -> LangfuseTracing:
    # The Langfuse client is shared per public key, so every test gets its own key.
    settings = LangfuseSettings.model_construct(
        enabled=True,
        public_key=SecretStr(f"pk-lf-{uuid.uuid4().hex}"),
        secret_key=SecretStr("sk-lf-test"),
        base_url="http://127.0.0.1:9",
    )
    tracing = build_tracing(settings, span_exporter=sink, capture_text=capture_text, **options)
    assert tracing is not None
    return tracing


def _coach(tracing: LangfuseTracing, *steps: Reply | str | BaseException) -> Coach:
    return Coach(SpyChatModel.scripted(*steps), PROMPT, INFO, tracing=tracing)


def _say(coach: Coach, text: str) -> None:
    with contextlib.suppress(ExternalServiceError):
        for _ in coach.respond(text):
            pass


def _assert_no_text_sent(sink: MemorySpanSink) -> None:
    sent = sink.everything_sent()
    assert sink.spans, "nothing was traced, so the check proves nothing"
    assert SENTINEL not in sent
    for snippet in PROMPT_TEXT_SNIPPETS:
        assert snippet not in sent


def _attribute(spans: Sequence[ReadableSpan], key: str) -> list[Any]:
    return [span.attributes[key] for span in spans if span.attributes and key in span.attributes]


def _metadata(spans: Sequence[ReadableSpan], name: str) -> set[Any]:
    """Langfuse stores metadata values as JSON text; decode them."""
    key = f"langfuse.observation.metadata.{name}"
    return {json.loads(value) for value in _attribute(spans, key)}


@pytest.fixture
def scores(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    recorded: list[dict[str, Any]] = []
    monkeypatch.setattr(Langfuse, "create_score", lambda self, **kwargs: recorded.append(kwargs))
    return recorded


def test_a_normal_turn_sends_the_allowed_fields_and_no_text(scores: list[dict[str, Any]]) -> None:
    sink = MemorySpanSink()
    tracing = _tracing(sink)
    coach = _coach(tracing, Reply(f"reply {SENTINEL}"), f"second {SENTINEL}")

    _say(coach, f"first {SENTINEL}")
    _say(coach, f"second {SENTINEL}")
    coach.close()

    _assert_no_text_sent(sink)
    assert _metadata(sink.spans, "prompt_hash") == {PROMPT.hash}
    assert _metadata(sink.spans, "turn") == {1, 2}
    assert len(set(_attribute(sink.spans, "session.id"))) == 1
    assert any(
        '"input": 100' in usage
        for usage in _attribute(sink.spans, "langfuse.observation.usage_details")
    )
    assert set(_attribute(sink.spans, "langfuse.observation.input")) == {"[masked]"}
    assert set(_attribute(sink.spans, "langfuse.observation.output")) <= {"[masked]"}


@pytest.mark.parametrize(
    ("step", "outcome"),
    [
        (f"reply {SENTINEL}", "ok"),
        (ModelRateLimitError(f"provider echoed {SENTINEL}"), "failed"),
        (Reply(f"partial {SENTINEL}", metadata=REFUSED), "blocked"),
        (Reply("", metadata=STOP), "blocked"),
    ],
)
def test_no_text_is_sent_whatever_the_outcome(
    scores: list[dict[str, Any]], step: Reply | str | BaseException, outcome: str
) -> None:
    sink = MemorySpanSink()
    coach = _coach(_tracing(sink), step)

    _say(coach, f"user {SENTINEL}")
    coach.close()

    _assert_no_text_sent(sink)
    assert [(score["name"], score["value"]) for score in scores] == [("outcome", outcome)]
    assert SENTINEL not in repr(scores)


def test_a_failed_call_is_marked_as_an_error_with_only_the_error_class(
    scores: list[dict[str, Any]],
) -> None:
    sink = MemorySpanSink()
    coach = _coach(_tracing(sink), ModelRateLimitError(f"provider echoed {SENTINEL}"))

    _say(coach, "hello")
    coach.close()

    errors = [span for span in sink.spans if span.status.status_code.name == "ERROR"]
    assert errors
    assert {span.status.description for span in errors} == {"ModelRateLimitError"}
    assert "ERROR" in _attribute(sink.spans, "langfuse.observation.level")


def test_a_cancelled_call_sends_no_text(scores: list[dict[str, Any]]) -> None:
    sink = MemorySpanSink()
    coach = _coach(_tracing(sink), f"a reply that is cut short {SENTINEL}")
    stream = coach.respond(f"user {SENTINEL}")

    next(stream)
    stream.close()
    coach.close()

    _assert_no_text_sent(sink)
    assert [score["value"] for score in scores] == ["cancelled"]


def test_a_reply_without_usage_numbers_is_still_traced(scores: list[dict[str, Any]]) -> None:
    sink = MemorySpanSink()
    coach = _coach(_tracing(sink), Reply(f"reply {SENTINEL}", usage=None))

    _say(coach, f"user {SENTINEL}")
    coach.close()

    _assert_no_text_sent(sink)
    assert _attribute(sink.spans, "langfuse.observation.usage_details") == []


def test_when_the_mask_itself_fails_nothing_is_sent_and_the_turn_is_fine(
    monkeypatch: pytest.MonkeyPatch, scores: list[dict[str, Any]]
) -> None:
    def broken(*, params: Any) -> Any:
        raise RuntimeError(f"mask bug {SENTINEL}")

    monkeypatch.setattr(tracing_factory, "mask_otel_spans", broken)
    sink = MemorySpanSink()
    coach = _coach(_tracing(sink), "Fine.", "Still fine.")

    replies = ["".join(coach.respond(text)) for text in ("one", "two")]
    coach.close()

    assert replies == ["Fine.", "Still fine."]
    assert sink.spans == []


class _BrokenSink(MemorySpanSink):
    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        self.entered.set()
        raise ConnectionError(f"Langfuse unreachable {SENTINEL}")


def test_a_sink_that_raises_never_changes_a_turn(scores: list[dict[str, Any]]) -> None:
    sink = _BrokenSink()
    coach = _coach(_tracing(sink, flush_interval_s=0.05), "One.", "Two.")

    first = "".join(coach.respond("a"))
    assert sink.entered.wait(timeout=5), "the sink was never asked to export"
    second = "".join(coach.respond("b"))
    coach.close()

    assert (first, second) == ("One.", "Two.")
    assert [message.text for message in coach.history[1:]] == ["a", "One.", "b", "Two."]


def test_a_blocked_sink_does_not_delay_the_turn(scores: list[dict[str, Any]]) -> None:
    release = threading.Event()
    sink = MemorySpanSink(block=release)
    coach = _coach(_tracing(sink, flush_interval_s=0.05, close_timeout_s=0.3), "One.", "Two.")

    first = "".join(coach.respond("a"))
    assert sink.entered.wait(timeout=5), "the sink was never asked to export"
    started = time.perf_counter()  # the sink is now blocked inside an export
    second = "".join(coach.respond("b"))
    turns_s = time.perf_counter() - started
    coach.close()
    release.set()

    assert (first, second) == ("One.", "Two.")
    assert turns_s < 1.0


def test_with_text_capture_messages_are_sent_but_nothing_else_widens(
    scores: list[dict[str, Any]],
) -> None:
    sink = MemorySpanSink()
    coach = _coach(
        _tracing(sink, capture_text=True),
        Reply(f"reply {SENTINEL}"),
        ModelRateLimitError(f"provider echoed {SENTINEL}-ECHO"),
    )

    _say(coach, f"user {SENTINEL}")
    _say(coach, "second")
    coach.close()

    texts = _attribute(sink.spans, "langfuse.observation.input") + _attribute(
        sink.spans, "langfuse.observation.output"
    )
    assert any(SENTINEL in text for text in texts), "positive control: text should be visible"
    assert any("You are Riri" in text for text in texts)
    assert f"{SENTINEL}-ECHO" not in sink.everything_sent()
    assert {span.status.description for span in sink.spans if span.status.description} == {
        "ModelRateLimitError"
    }
    assert _metadata(sink.spans, "prompt_hash") == {PROMPT.hash}
