import logging
import os
import subprocess
import sys
from pathlib import Path

import pytest
import structlog
from langchain_core.exceptions import ModelAPIError
from langchain_core.messages import UsageMetadata
from structlog.testing import capture_logs

from app.coach.coach_factory import CoachConfigError
from app.coach.conversation.coach import FALLBACK_LINE, GREETING, Coach
from app.coach.llm.model_factory import ModelInfo
from app.coach.prompts.prompt_registry import DEFAULT_REGISTRY_PATH, compile_active_set
from app.core.config.base import BASE_DIR
from app.core.logging import configure_logging
from app.entrypoints import cli
from app.entrypoints.cli import NO_TURNS, UNKNOWN_COMMAND, CliSession
from tests.fakes.spy_chat_model import Reply, SpyChatModel

PROMPT = compile_active_set(DEFAULT_REGISTRY_PATH)
INFO = ModelInfo(name="gemini-test", temperature=0.7, thinking_level="minimal")


class Screen:
    """Captures every write, so tests can see streaming as separate pieces."""

    def __init__(self, interrupt_on: int | None = None) -> None:
        self.writes: list[str] = []
        self._interrupt_on = interrupt_on

    def __call__(self, text: str) -> None:
        self.writes.append(text)
        if len(self.writes) == self._interrupt_on:
            raise KeyboardInterrupt

    @property
    def text(self) -> str:
        return "".join(self.writes)


def _session(*steps: Reply | str | BaseException, screen: Screen | None = None):
    model = SpyChatModel.scripted(*steps)
    coach = Coach(model, PROMPT, INFO, clock=lambda: 0.0)
    screen = screen or Screen()
    return CliSession(coach, screen), coach, model, screen


def test_greet_shows_the_fixed_greeting() -> None:
    session, _, _, screen = _session()

    session.greet()

    assert GREETING in screen.text


@pytest.mark.parametrize("line", ["", "   ", "\t"])
def test_blank_input_is_ignored(line: str) -> None:
    session, coach, model, screen = _session()

    assert session.handle(line) is True

    assert screen.writes == [] and model.received == []
    assert len(coach.history) == 1


def test_text_streams_to_the_screen_piece_by_piece() -> None:
    session, _, _, screen = _session("One two three.")

    assert session.handle("hello") is True

    assert screen.text.strip().endswith("One two three.")
    assert len(screen.writes) > 3


def test_reset_clears_the_coach_and_greets_again() -> None:
    session, coach, _, screen = _session("Okay.")
    session.handle("hello")

    assert session.handle("/reset") is True

    assert len(coach.history) == 1 and coach.stats() == ()
    assert screen.text.rstrip().endswith(GREETING)


def test_quit_ends_the_session() -> None:
    session, _, model, _ = _session()

    assert session.handle("/quit") is False
    assert model.received == []


def test_stats_before_any_turn() -> None:
    session, _, _, screen = _session()

    session.handle("/stats")

    assert screen.text.strip() == NO_TURNS


def test_stats_table_shows_each_turn_with_unknowns_as_question_marks() -> None:
    usage = UsageMetadata(input_tokens=812, output_tokens=4, total_tokens=816)
    session, _, _, screen = _session(Reply("A.", usage=usage), Reply("B.", usage=None))
    session.handle("first")
    session.handle("second")
    screen.writes.clear()

    session.handle("/stats")

    lines = screen.text.strip().splitlines()
    assert lines[0].split() == ["turn", "ttft_ms", "total_ms", "in_tok", "out_tok", "truncated"]
    assert lines[1].split() == ["1", "0.0", "0.0", "812", "4", "no"]
    assert lines[2].split() == ["2", "0.0", "0.0", "?", "?", "no"]


@pytest.mark.parametrize("line", ["/help", "/RESET", "/"])
def test_unknown_commands_are_not_sent_to_the_model(line: str) -> None:
    session, _, model, screen = _session()

    assert session.handle(line) is True

    assert screen.text.strip() == UNKNOWN_COMMAND
    assert model.received == []


def test_a_model_failure_shows_the_fallback_line_and_the_session_continues() -> None:
    session, coach, _, screen = _session(ModelAPIError("down"), "Back again.")

    assert session.handle("hello") is True
    assert screen.text == f"Riri: {FALLBACK_LINE}\n"
    assert FALLBACK_LINE not in [m.text for m in coach.history]

    session.handle("hello")
    assert screen.text.strip().endswith("Back again.")


def test_ctrl_c_mid_stream_cancels_the_turn() -> None:
    screen = Screen(interrupt_on=2)
    session, coach, _, _ = _session("Several words in this reply.", screen=screen)

    with capture_logs() as logs, pytest.raises(KeyboardInterrupt):
        session.handle("hello")

    assert len(coach.history) == 1 and coach.stats() == ()
    assert [e["outcome"] for e in logs if e["event"] == "llm_call"] == ["cancelled"]


def _fail_build(_settings: object) -> Coach:
    raise CoachConfigError("LLM_API_KEY is not set.")


@pytest.fixture
def failing_main(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "build_coach", _fail_build)
    monkeypatch.setattr(cli, "configure_cli_logging", lambda path: None)


@pytest.mark.usefixtures("failing_main")
def test_main_exits_before_the_greeting_when_settings_are_missing(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main() == 1

    out, err = capsys.readouterr()
    assert "LLM_API_KEY is not set." in err
    assert GREETING not in out + err


@pytest.mark.usefixtures("failing_main")
def test_main_turns_langsmith_tracing_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANGSMITH_TRACING", "true")

    cli.main()

    assert os.environ["LANGSMITH_TRACING"] == "false"


def test_an_invalid_setting_prints_one_clear_line_instead_of_a_traceback() -> None:
    result = subprocess.run(
        [sys.executable, "-W", "ignore", "-m", "app.entrypoints.cli"],
        cwd=BASE_DIR,
        env={**os.environ, "LLM_THINKING_LEVEL": "max"},
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=90,
    )

    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert len(result.stderr.strip().splitlines()) == 1
    assert result.stderr.startswith("Cannot start the coach: ")
    assert "LLMSettings.thinking_level" in result.stderr
    assert "LLM_THINKING_LEVEL" in result.stderr
    assert result.stdout == ""


def test_cli_logs_go_to_a_file_and_library_noise_is_quieted(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    log_file = tmp_path / "logs" / "cli.log"

    cli.configure_cli_logging(log_file)
    try:
        structlog.get_logger("app.coach").info("llm_call", turn=1)
        logging.getLogger("httpx2").info("HTTP Request: POST https://example.invalid")
        for handler in logging.getLogger().handlers:
            handler.flush()

        written = log_file.read_text(encoding="utf-8")
        assert "llm_call" in written
        assert "HTTP Request" not in written
        assert "llm_call" not in capsys.readouterr().out
    finally:
        handler = logging.getLogger().handlers[-1]
        configure_logging("INFO", json_logs=True)
        handler.stream.close()  # type: ignore[attr-defined]
        for name in ("httpx", "httpx2", "google_genai"):
            logging.getLogger(name).setLevel(logging.NOTSET)
