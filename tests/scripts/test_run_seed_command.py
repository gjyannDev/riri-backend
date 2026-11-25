import datetime
from pathlib import Path

import pytest

from app.coach.coach_factory import CoachConfigError
from app.coach.conversation.coach import Coach
from app.coach.llm.model_factory import ModelInfo
from app.coach.prompts.prompt_registry import DEFAULT_REGISTRY_PATH, compile_active_set
from app.core.config import Settings
from app.scripts.run_seed import INTERRUPTED_EXIT, main
from tests.fakes.fake_tracing import FakeTracing
from tests.fakes.spy_chat_model import SpyChatModel

PROMPT = compile_active_set(DEFAULT_REGISTRY_PATH)
INFO = ModelInfo(name="gemini-test", temperature=0.7, thinking_level="minimal")
DAY = datetime.date(2026, 11, 26)


class Harness:
    def __init__(self, tmp_path: Path, *steps: str | BaseException) -> None:
        self.model = SpyChatModel.scripted(*steps)
        self.tracing = FakeTracing()
        self.builds = 0
        self.results_dir = tmp_path / "results"
        self.logs_dir = tmp_path / "logs"

    def build(self, _: Settings) -> Coach:
        self.builds += 1
        return Coach(self.model, PROMPT, INFO, tracing=self.tracing)

    def run(self, *argv: str, seed_path: Path | None = None, **overrides: object) -> int:
        kwargs: dict[str, object] = {
            "build": self.build,
            "sleep": lambda _: None,
            "today": lambda: DAY,
            "results_dir": self.results_dir,
            "logs_dir": self.logs_dir,
        }
        if seed_path is not None:
            kwargs["seed_path"] = seed_path
        kwargs.update(overrides)
        return main(list(argv), **kwargs)  # type: ignore[arg-type]


def test_a_full_run_prints_the_table_and_writes_both_files(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    harness = Harness(tmp_path, *["Okay."] * 30)

    code = harness.run("--pause-seconds", "0")

    out = capsys.readouterr().out
    stem = f"2026-11-26-{PROMPT.hash}"
    assert code == 0
    assert len(harness.model.received) == 30
    assert "| one_question | 30 | 30 |" in out
    assert f"prompt hash: {PROMPT.hash}" in out
    assert (harness.results_dir / f"{stem}.md").is_file()
    assert (harness.logs_dir / f"seed-{stem}.jsonl").is_file()
    assert harness.tracing.closed == 1


@pytest.mark.parametrize("value", ["-1", "abc", "nan", "inf"])
def test_a_bad_pause_value_stops_before_anything_runs(tmp_path: Path, value: str) -> None:
    harness = Harness(tmp_path)

    with pytest.raises(SystemExit) as stopped:
        harness.run("--pause-seconds", value)

    assert stopped.value.code == 2
    assert harness.builds == 0


def test_a_failing_build_stops_before_any_call_and_shows_no_secret(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:  # AC10, EC4
    def broken(_: Settings) -> Coach:
        raise CoachConfigError("LLM_API_KEY is not set. Add your Google AI Studio key to .env.")

    code = Harness(tmp_path).run(build=broken)

    err = capsys.readouterr().err
    assert code == 1
    assert err.startswith("Cannot run the seed evals: LLM_API_KEY is not set.")
    assert not (tmp_path / "results").exists()


def test_a_bad_seed_file_stops_before_the_coach_is_built(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:  # AC10, EC5
    seed = tmp_path / "seed.jsonl"
    seed.write_text("{not json\n", encoding="utf-8")
    harness = Harness(tmp_path)

    code = harness.run(seed_path=seed)

    assert code == 1
    assert harness.builds == 0
    assert "Line 1 is not valid JSON." in capsys.readouterr().err


def test_ctrl_c_closes_the_coach_writes_no_results_file_and_keeps_partial_runs(
    tmp_path: Path,
) -> None:  # AC11, EC12
    harness = Harness(tmp_path, "Okay.", KeyboardInterrupt())

    code = harness.run("--pause-seconds", "0")

    assert code == INTERRUPTED_EXIT
    assert harness.tracing.closed == 1
    assert not harness.results_dir.exists()
    (partial,) = harness.logs_dir.iterdir()
    assert len(partial.read_text(encoding="utf-8").splitlines()) == 1
