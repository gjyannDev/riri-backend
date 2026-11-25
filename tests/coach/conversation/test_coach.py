import contextlib
import logging
from collections.abc import Sequence

import pytest
from langchain_core.exceptions import ModelRateLimitError
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, UsageMetadata
from structlog.testing import capture_logs
from structlog.typing import EventDict

from app.coach.conversation.coach import GREETING, Coach
from app.coach.llm.model_factory import ModelInfo
from app.coach.prompts.prompt_registry import DEFAULT_REGISTRY_PATH, compile_active_set
from app.core.errors import ExternalBadResponseError, ExternalRateLimitedError, ExternalServiceError
from tests.fakes.fake_tracing import FakeTracing
from tests.fakes.spy_chat_model import REFUSED, STOP, TRUNCATED, Reply, SpyChatModel

PROMPT = compile_active_set(DEFAULT_REGISTRY_PATH)
INFO = ModelInfo(name="gemini-test", temperature=0.7, thinking_level="minimal")


class FakeClock:
    """Returns the given times (seconds) in order, then keeps returning the last one."""

    def __init__(self, *times: float) -> None:
        self._times = list(times)

    def __call__(self) -> float:
        return self._times.pop(0) if len(self._times) > 1 else self._times[0]


def _coach(*steps: Reply | str | BaseException, clock: FakeClock | None = None):
    model = SpyChatModel.scripted(*steps)
    return Coach(model, PROMPT, INFO, clock=clock or FakeClock(0.0)), model


def _say(coach: Coach, text: str) -> str:
    return "".join(coach.respond(text))


def _llm_calls(logs: Sequence[EventDict]) -> list[EventDict]:
    return [entry for entry in logs if entry["event"] == "llm_call"]


def test_system_message_is_the_compiled_prompt_role_and_constraints_first() -> None:
    coach, model = _coach("Okay.")

    _say(coach, "hello")

    system = model.received[0][0]
    assert isinstance(system, SystemMessage)
    assert system.text.startswith("ROLE\nYou are Riri, an AI skills coach")
    assert system.text.index("CONSTRAINTS") < system.text.index("TASK")
    expected = PROMPT.template.invoke({"history": [], "user_text": "x"}).to_messages()[0]
    assert system.text == expected.text


def test_greeting_is_the_first_history_message() -> None:
    coach, _ = _coach()

    assert coach.history == (AIMessage(GREETING),)


def test_turn_two_receives_greeting_then_turn_one_in_order() -> None:
    coach, model = _coach("Reply one.", "Reply two.")

    assert _say(coach, "first message") == "Reply one."
    _say(coach, "second message")

    sent = model.received[1]
    assert sent[1:] == [
        AIMessage(GREETING),
        HumanMessage("first message"),
        AIMessage("Reply one."),
        HumanMessage("second message"),
    ]


def test_one_llm_call_event_with_every_field() -> None:
    coach, _ = _coach(
        Reply(
            "Okay then.", usage=UsageMetadata(input_tokens=812, output_tokens=4, total_tokens=816)
        )
    )

    with capture_logs() as logs:
        _say(coach, "hello")

    assert _llm_calls(logs) == [
        {
            "event": "llm_call",
            "log_level": "info",
            "outcome": "ok",
            "prompt_version": PROMPT.version,
            "prompt_hash": PROMPT.hash,
            "model": "gemini-test",
            "temperature": 0.7,
            "thinking_level": "minimal",
            "turn": 1,
            "ttft_ms": 0.0,
            "total_ms": 0.0,
            "input_tokens": 812,
            "output_tokens": 4,
            "input_chars": 5,
            "truncated": False,
            "usage_missing": False,
            "blocked": False,
            "block_reason": None,
        }
    ]


def test_ttft_and_total_come_from_the_clock() -> None:
    coach, _ = _coach("Three word reply.", clock=FakeClock(10.0, 10.25, 11.5))

    with capture_logs() as logs:
        _say(coach, "hello")

    event = _llm_calls(logs)[0]
    assert (event["ttft_ms"], event["total_ms"]) == (250.0, 1500.0)
    assert coach.stats()[0].ttft_ms == 250.0
    assert coach.stats()[0].total_ms == 1500.0


def test_model_error_raises_external_keeps_history_and_logs_one_failure() -> None:
    coach, _ = _coach(ModelRateLimitError("quota"), "Fine.")

    with capture_logs() as logs, pytest.raises(ExternalRateLimitedError) as raised:
        _say(coach, "hello")

    assert raised.value.__cause__ is None
    assert raised.value.__suppress_context__ is True
    assert coach.history == (AIMessage(GREETING),)
    assert coach.stats() == ()
    (event,) = _llm_calls(logs)
    assert event["outcome"] == "failed"
    assert event["log_level"] == "error"
    assert event["error_code"] == "EXTERNAL_RATE_LIMITED"
    assert event["error_type"] == "ModelRateLimitError"
    assert event["category"] == "external"
    assert len([e for e in logs if e["log_level"] == "error"]) == 1

    assert _say(coach, "hello again") == "Fine."
    assert coach.stats()[0].turn == 1


def test_a_bug_inside_respond_is_logged_as_an_error_not_a_cancel() -> None:
    coach, _ = _coach(KeyError("user_text"))

    with capture_logs() as logs, pytest.raises(KeyError):
        _say(coach, "hello")

    (event,) = _llm_calls(logs)
    assert (event["outcome"], event["log_level"]) == ("error", "error")
    assert coach.history == (AIMessage(GREETING),)


def test_ctrl_c_while_waiting_for_the_model_is_logged_as_cancelled() -> None:
    coach, _ = _coach(KeyboardInterrupt())

    with capture_logs() as logs, pytest.raises(KeyboardInterrupt):
        _say(coach, "hello")

    assert [(e["outcome"], e["log_level"]) for e in _llm_calls(logs)] == [("cancelled", "info")]
    assert coach.history == (AIMessage(GREETING),)


def test_closing_the_stream_early_keeps_nothing_and_logs_cancelled() -> None:
    coach, _ = _coach("Several words in this reply.")

    with capture_logs() as logs:
        stream = coach.respond("hello")
        first = next(stream)
        stream.close()

    assert first == "Several"
    assert coach.history == (AIMessage(GREETING),)
    assert coach.stats() == ()
    assert [e["outcome"] for e in _llm_calls(logs)] == ["cancelled"]


def test_truncated_reply_is_kept_and_flagged() -> None:
    coach, _ = _coach(Reply("Cut off mid", metadata=TRUNCATED))

    with capture_logs() as logs:
        _say(coach, "hello")

    assert coach.history[-1] == AIMessage("Cut off mid")
    assert coach.stats()[0].truncated is True
    assert _llm_calls(logs)[0]["truncated"] is True


def test_missing_usage_still_succeeds_and_is_flagged() -> None:
    coach, _ = _coach(Reply("Okay.", usage=None))

    with capture_logs() as logs:
        assert _say(coach, "hello") == "Okay."

    event = _llm_calls(logs)[0]
    assert event["usage_missing"] is True
    assert (event["input_tokens"], event["output_tokens"]) == (None, None)
    assert coach.stats()[0].input_tokens is None


@pytest.mark.parametrize(
    ("reply", "reason"),
    [(Reply("", metadata=STOP), "EMPTY"), (Reply("Partial", metadata=REFUSED), "SAFETY")],
)
def test_blocked_or_empty_reply_raises_keeps_nothing_and_logs_blocked(
    reply: Reply, reason: str
) -> None:
    coach, _ = _coach(reply)

    with capture_logs() as logs, pytest.raises(ExternalBadResponseError):
        _say(coach, "hello")

    assert coach.history == (AIMessage(GREETING),)
    assert coach.stats() == ()
    (event,) = _llm_calls(logs)
    assert (event["outcome"], event["blocked"], event["block_reason"]) == ("blocked", True, reason)
    assert event["log_level"] == "warning"


def test_long_input_is_sent_as_is_and_only_its_length_is_logged() -> None:
    long_text = "word " * 1000
    coach, model = _coach("Okay.")

    with capture_logs() as logs:
        _say(coach, long_text)

    assert model.received[0][-1] == HumanMessage(long_text)
    assert _llm_calls(logs)[0]["input_chars"] == 5000


def test_reset_restores_the_greeting_and_restarts_turns() -> None:
    coach, _ = _coach("One.", "Two.", "Three.")
    _say(coach, "a")
    _say(coach, "b")

    coach.reset()

    assert coach.history == (AIMessage(GREETING),)
    assert coach.stats() == ()
    _say(coach, "c")
    assert [s.turn for s in coach.stats()] == [1]


def test_no_log_record_contains_conversation_or_prompt_text(
    caplog: pytest.LogCaptureFixture,
) -> None:
    user_texts = ["canary-user-alpha", "canary-user-beta", "canary-user-gamma", "canary-user-delta"]
    replies = [
        "canary-reply-one",
        ModelRateLimitError("x"),
        Reply("", metadata=STOP),
        "canary-reply-four",
    ]
    coach, _ = _coach(*replies)
    prompt_snippet = "CONVERSATION PRINCIPLES"

    with capture_logs() as logs, caplog.at_level(logging.DEBUG):
        for text in user_texts:
            with contextlib.suppress(ExternalServiceError):
                _say(coach, text)

    assert len(_llm_calls(logs)) == 4
    everything = [repr(entry) for entry in logs] + [r.getMessage() for r in caplog.records]
    for line in everything:
        assert "canary" not in line
        assert prompt_snippet not in line
        assert GREETING not in line


def _traced(*steps: Reply | str | BaseException) -> tuple[Coach, FakeTracing]:
    tracing = FakeTracing()
    coach = Coach(
        SpyChatModel.scripted(*steps), PROMPT, INFO, clock=FakeClock(0.0), tracing=tracing
    )
    return coach, tracing


def test_each_call_starts_a_trace_with_version_hash_model_and_turn_only() -> None:
    coach, tracing = _traced("One.", "Two.")

    _say(coach, "private words")
    _say(coach, "more private words")

    assert [start["metadata"] for start in tracing.starts] == [
        {
            "prompt_version": PROMPT.version,
            "prompt_hash": PROMPT.hash,
            "model": "gemini-test",
            "thinking_level": "minimal",
            "temperature": 0.7,
            "turn": turn,
        }
        for turn in (1, 2)
    ]
    assert "private" not in repr(tracing.starts)


def test_the_calls_config_reaches_the_chain() -> None:
    coach, tracing = _traced("One.")

    _say(coach, "hello")

    (seen,) = tracing.chain_metadata
    assert seen["langfuse_session_id"] == tracing.starts[0]["session_id"]
    assert seen["prompt_hash"] == PROMPT.hash


def test_session_id_is_stable_within_a_conversation_and_new_after_reset() -> None:
    coach, tracing = _traced("One.", "Two.", "Three.")

    _say(coach, "a")
    _say(coach, "b")
    coach.reset()
    _say(coach, "c")

    first, second, third = (start["session_id"] for start in tracing.starts)
    assert first == second != third
    assert all(len(session) == 32 and session.isalnum() for session in (first, third))


@pytest.mark.parametrize(
    ("step", "outcome"),
    [
        ("Okay.", "ok"),
        (ModelRateLimitError("x"), "failed"),
        (Reply("", metadata=STOP), "blocked"),
    ],
)
def test_every_call_records_how_it_ended(step: Reply | str | BaseException, outcome: str) -> None:
    coach, tracing = _traced(step)

    with contextlib.suppress(ExternalServiceError):
        _say(coach, "hello")

    assert tracing.outcomes == [outcome]


def test_a_cancelled_call_records_cancelled() -> None:
    coach, tracing = _traced("A reply that is cut short.")
    stream = coach.respond("hello")

    next(stream)
    stream.close()

    assert tracing.outcomes == ["cancelled"]


def test_close_closes_the_tracing_and_is_harmless_without_one() -> None:
    coach, tracing = _traced()
    coach.close()
    plain, _ = _coach()
    plain.close()

    assert tracing.closed == 1


def test_a_coach_without_tracing_sends_no_config() -> None:
    coach, model = _coach("Okay.")

    assert _say(coach, "hello") == "Okay."
    assert len(model.received) == 1
