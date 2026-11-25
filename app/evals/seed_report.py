"""Turn run results into the pass table, the committed results file and the local JSONL."""

import datetime
import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from app.evals.seed_rules import RULES
from app.evals.seed_runner import RunResult


@dataclass(frozen=True)
class RunInfo:
    """What the run used, read from the built coach. Never a secret."""

    model: str
    prompt_version: str
    prompt_hash: str


def render_report(
    results: Sequence[RunResult], info: RunInfo, day: datetime.date
) -> tuple[str, str]:
    """Return (table, document). The terminal prints the table; the document holds it verbatim."""
    scored = [r for r in results if r.error is None]
    errors = [r for r in results if r.error is not None]
    lines = [
        f"Seed eval {day.isoformat()}",
        f"model: {info.model}",
        f"prompt: {info.prompt_version}",
        f"prompt hash: {info.prompt_hash}",
        f"runs: {len(results)} ({len(scored)} scored, {len(errors)} errors)",
        "",
        "| rule | passed | scored |",
        "| --- | --- | --- |",
    ]
    for name, _ in RULES:
        passed = sum(r.verdicts[name] for r in scored)
        lines.append(f"| {name} | {passed} | {len(scored)} |")
    table = "\n".join(lines) + "\n"

    failures = [
        f"| {r.message_id} | {r.run} | {name} | {_cell(r.reply or '')} |"
        for r in scored
        for name, _ in RULES
        if not r.verdicts[name]
    ]
    document = [f"# {table}", "## Failures", ""]
    document += (
        ["| message | run | rule | reply |", "| --- | --- | --- | --- |", *failures]
        if failures
        else ["No failures."]
    )
    document += ["", "## Errors", ""]
    document += (
        [
            "| message | run | error |",
            "| --- | --- | --- |",
            *(f"| {r.message_id} | {r.run} | {r.error} |" for r in errors),
        ]
        if errors
        else ["No errors."]
    )
    return table, "\n".join(document) + "\n"


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\r\n", "<br>").replace("\n", "<br>")


@dataclass(frozen=True)
class ReportPaths:
    document: Path
    runs: Path


def report_paths(
    info: RunInfo, day: datetime.date, results_dir: Path, logs_dir: Path
) -> ReportPaths:
    stem = f"{day.isoformat()}-{info.prompt_hash}"
    return ReportPaths(results_dir / f"{stem}.md", logs_dir / f"seed-{stem}.jsonl")


def write_runs(results: Sequence[RunResult], path: Path) -> None:
    """The local, gitignored record of every run, reply included (synthetic seed text only)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(_row(r), ensure_ascii=False) for r in results]
    path.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")


def write_report(
    results: Sequence[RunResult],
    info: RunInfo,
    day: datetime.date,
    results_dir: Path,
    logs_dir: Path,
) -> ReportPaths:
    """Write `<date>-<hash>.md` and `seed-<date>-<hash>.jsonl`; the same name is overwritten."""
    paths = report_paths(info, day, results_dir, logs_dir)
    _, document = render_report(results, info, day)
    results_dir.mkdir(parents=True, exist_ok=True)
    paths.document.write_text(document, encoding="utf-8")
    write_runs(results, paths.runs)
    return paths


def _row(result: RunResult) -> dict[str, Any]:
    row = asdict(result)
    if row["session_id"] is None:
        del row["session_id"]
    return row
