import pytest
from langchain_core.exceptions import ModelRateLimitError
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from structlog.testing import capture_logs

from app.coach.conversation.coach import GREETING, Coach
from app.coach.llm.model_factory import ModelInfo
from app.coach.prompts.prompt_registry import DEFAULT_REGISTRY_PATH, compile_active_set
from app.core.errors import ExternalBadResponseError, ExternalRateLimitedError
from app.evals.seed_messages import SeedMessage
from app.evals.seed_runner import RunResult, run_seed
from tests.fakes.spy_chat_model import REFUSED, STOP, Reply, SpyChatModel, usage

PROMPT = compile_active_set(DEFAULT_REGISTRY_PATH)
INFO = ModelInfo(name="gemini-test", temperature=0.7, thinking_level="minimal")
MESSAGES = tuple(SeedMessage(f"m{i:02}", "angry", f"synthetic message {i}") for i in range(1, 11))


class Recorder:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self.sleeps: list[float] = []

    def write(self, line: str) -> None:
        self.lines.append(line)

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)


def _run(
    *steps: Reply | str | BaseException,
    messages: tuple[SeedMessage, ...] = MESSAGES,
    runs: int = 3,
    pause_seconds: float = 0,
) -> tuple[list[RunResult], SpyChatModel, Recorder]:
    model = SpyChatModel.scripted(*steps)
    recorder = Recorder()
    results = run_seed(
        Coach(model, PROMPT, INFO),
        messages,
        runs=runs,
        pause_seconds=pause_seconds,
        sleep=recorder.sleep,
        write=recorder.write,
    )
    return results, model, recorder


def test_each_message_runs_three_times_in_a_fresh_conversation() -> None:
    results, model, _ = _run(*["Okay."] * 30)

    assert len(model.received) == 30
    assert [(r.message_id, r.run) for r in results[:4]] == [
        ("m01", 1),
        ("m01", 2),
        ("m01", 3),
        ("m02", 1),
    ]
    for index, sent in enumerate(model.received):
        assert [type(m) for m in sent] == [SystemMessage, AIMessage, HumanMessage]
        assert sent[1].text == GREETING
        assert sent[2].text == MESSAGES[index // 3].text


def test_each_reply_is_scored_on_all_three_rules_with_its_turn_numbers() -> None:
    one = (SeedMessage("m01", "angry", "synthetic"),)
    results, _, _ = _run(
        Reply("That sounds hard.", usage=usage(120, 15)),
        "What happened? Why now?",
        "- a list\nI understand exactly.",
        messages=one,
    )

    assert [r.verdicts for r in results] == [
        {"one_question": True, "no_markdown": True, "no_fake_empathy": True},
        {"one_question": False, "no_markdown": True, "no_fake_empathy": True},
        {"one_question": True, "no_markdown": False, "no_fake_empathy": False},
    ]
    assert (results[0].input_tokens, results[0].output_tokens) == (120, 15)
    assert results[0].error is None


def test_a_failed_blocked_or_empty_reply_is_an_error_run_and_the_loop_goes_on() -> None:
    one = (SeedMessage("m01", "angry", "synthetic"),)
    results, model, _ = _run(
        ModelRateLimitError("rate limited"),  # EC1, EC17: no retry
        Reply("", metadata=REFUSED),  # EC2
        Reply("   ", metadata=STOP),  # EC3
        "Still here.",
        messages=one,
        runs=4,
    )

    assert len(model.received) == 4
    assert [r.error for r in results] == [
        ExternalRateLimitedError.code,
        ExternalBadResponseError.code,
        ExternalBadResponseError.code,
        None,
    ]
    assert all(r.reply is None and r.verdicts == {} for r in results[:3])
    assert results[3].reply == "Still here."


def test_it_pauses_after_every_run_but_the_last_including_error_runs() -> None:
    steps: list[str | BaseException] = ["Okay."] * 29
    steps.insert(4, ModelRateLimitError("rate limited"))

    _, _, recorder = _run(*steps, pause_seconds=5)

    assert recorder.sleeps == [5] * 29


def test_a_zero_pause_never_sleeps() -> None:
    _, _, recorder = _run(*["Okay."] * 30, pause_seconds=0)

    assert recorder.sleeps == []


def test_ctrl_c_during_a_pause_stops_the_run() -> None:  # EC18
    model = SpyChatModel.scripted("Okay.", "Okay.")

    def interrupted(_: float) -> None:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run_seed(Coach(model, PROMPT, INFO), MESSAGES, pause_seconds=1, sleep=interrupted)

    assert len(model.received) == 1


def test_each_result_is_handed_over_as_soon_as_it_exists() -> None:  # EC12 partial results
    model = SpyChatModel.scripted("One.", KeyboardInterrupt())
    seen: list[RunResult] = []

    with pytest.raises(KeyboardInterrupt):
        run_seed(
            Coach(model, PROMPT, INFO),
            MESSAGES,
            pause_seconds=0,
            write=lambda _: None,
            on_result=seen.append,
        )

    assert [(r.message_id, r.run, r.reply) for r in seen] == [("m01", 1, "One.")]


def test_the_session_id_is_recorded_only_when_asked() -> None:  # AC8, EC13
    one = (SeedMessage("m01", "angry", "synthetic"),)
    coach = Coach(SpyChatModel.scripted("One.", "Two."), PROMPT, INFO)

    plain = run_seed(coach, one, runs=1, pause_seconds=0, write=lambda _: None)
    traced = run_seed(
        coach, one, runs=1, pause_seconds=0, write=lambda _: None, record_session=True
    )

    assert plain[0].session_id is None
    assert traced[0].session_id == coach.session_id


def test_progress_lines_and_logs_carry_ids_and_verdicts_never_text() -> None:  # AC9
    one = (SeedMessage("m03", "rambling", "private seed words"),)

    with capture_logs() as logs:
        _, _, recorder = _run(
            "Secret reply? Another?", ModelRateLimitError("x"), messages=one, runs=2
        )

    assert recorder.lines == [
        "m03 run 1: one_question=fail no_markdown=pass no_fake_empathy=pass",
        "m03 run 2: error EXTERNAL_RATE_LIMITED",
    ]
    seed_runs = [entry for entry in logs if entry["event"] == "seed_run"]
    assert [entry["outcome"] for entry in seed_runs] == ["scored", "error"]
    for text in ("private", "Secret", "Another"):
        assert text not in repr(logs)
