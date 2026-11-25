import datetime
import json
from pathlib import Path

from app.evals.seed_report import RunInfo, render_report, write_report
from app.evals.seed_runner import RunResult

INFO = RunInfo(model="gemini-test", prompt_version="coach_default:role@v1", prompt_hash="abc123")
DAY = datetime.date(2026, 11, 26)
ALL_PASS = {"one_question": True, "no_markdown": True, "no_fake_empathy": True}


def _scored(message_id: str, run: int, reply: str, **fails: bool) -> RunResult:
    return RunResult(message_id, run, reply, verdicts=ALL_PASS | fails, input_tokens=100)


RESULTS = [
    _scored("m01", 1, "Fine."),
    _scored("m01", 2, "What? Why?", one_question=False),
    _scored("m02", 1, "- a\n- b | c", no_markdown=False, one_question=False),
    RunResult("m02", 2, None, error="EXTERNAL_RATE_LIMITED"),
]


def test_the_table_counts_passes_over_scored_runs_with_errors_and_run_info() -> None:  # AC4
    table, _ = render_report(RESULTS, INFO, DAY)

    assert table == (
        "Seed eval 2026-11-26\n"
        "model: gemini-test\n"
        "prompt: coach_default:role@v1\n"
        "prompt hash: abc123\n"
        "runs: 4 (3 scored, 1 errors)\n"
        "\n"
        "| rule | passed | scored |\n"
        "| --- | --- | --- |\n"
        "| one_question | 1 | 3 |\n"
        "| no_markdown | 2 | 3 |\n"
        "| no_fake_empathy | 3 | 3 |\n"
    )


def test_the_file_has_one_row_per_failing_run_and_rule_and_lists_errors() -> None:  # AC5, EC14
    table, document = render_report(RESULTS, INFO, DAY)

    assert document.startswith(f"# {table}")
    assert document.split("## Failures\n", 1)[1] == (
        "\n"
        "| message | run | rule | reply |\n"
        "| --- | --- | --- | --- |\n"
        "| m01 | 2 | one_question | What? Why? |\n"
        "| m02 | 1 | one_question | - a<br>- b \\| c |\n"
        "| m02 | 1 | no_markdown | - a<br>- b \\| c |\n"
        "\n"
        "## Errors\n"
        "\n"
        "| message | run | error |\n"
        "| --- | --- | --- |\n"
        "| m02 | 2 | EXTERNAL_RATE_LIMITED |\n"
    )


def test_a_clean_run_says_there_were_no_failures_or_errors() -> None:  # EC15
    _, document = render_report([_scored("m01", 1, "Fine.")], INFO, DAY)

    assert document.endswith("## Failures\n\nNo failures.\n\n## Errors\n\nNo errors.\n")


def test_files_are_named_by_date_and_hash_and_a_rerun_overwrites(tmp_path: Path) -> None:
    results_dir, logs_dir = tmp_path / "results", tmp_path / "logs"

    first = write_report(RESULTS, INFO, DAY, results_dir, logs_dir)
    second = write_report(RESULTS[:1], INFO, DAY, results_dir, logs_dir)  # EC10

    assert first == second
    assert first.document == results_dir / "2026-11-26-abc123.md"
    assert first.runs == logs_dir / "seed-2026-11-26-abc123.jsonl"
    assert "runs: 1 (1 scored, 0 errors)" in first.document.read_text(encoding="utf-8")
    assert len(first.runs.read_text(encoding="utf-8").splitlines()) == 1


def test_a_new_hash_or_date_keeps_the_old_files(tmp_path: Path) -> None:  # EC11
    results_dir, logs_dir = tmp_path / "results", tmp_path / "logs"
    other = RunInfo(model="gemini-test", prompt_version="v2", prompt_hash="def456")

    write_report(RESULTS, INFO, DAY, results_dir, logs_dir)
    write_report(RESULTS, other, DAY, results_dir, logs_dir)
    write_report(RESULTS, INFO, DAY + datetime.timedelta(days=1), results_dir, logs_dir)

    assert sorted(p.name for p in results_dir.iterdir()) == [
        "2026-11-26-abc123.md",
        "2026-11-26-def456.md",
        "2026-11-27-abc123.md",
    ]


def test_the_local_jsonl_has_every_run_with_reply_and_session_id_only_when_set(
    tmp_path: Path,
) -> None:  # AC8, EC13
    traced = RunResult("m03", 1, "Okay.", verdicts=ALL_PASS, session_id="a" * 32)

    paths = write_report([RESULTS[1], RESULTS[3], traced], INFO, DAY, tmp_path, tmp_path)

    rows = [json.loads(line) for line in paths.runs.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["reply"] == "What? Why?"
    assert rows[0]["verdicts"]["one_question"] is False
    assert rows[0]["input_tokens"] == 100
    assert "session_id" not in rows[0]
    assert rows[1]["error"] == "EXTERNAL_RATE_LIMITED" and rows[1]["reply"] is None
    assert rows[2]["session_id"] == "a" * 32
