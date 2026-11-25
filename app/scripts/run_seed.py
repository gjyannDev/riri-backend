"""Run the seed evals against the real model, by hand. Never run by pytest or CI.

  uv run python -m app.scripts.run_seed [--pause-seconds 5]

Builds the coach through `build_coach`, like every door. Writes the pass table and failing replies
to docs/features/slice-1c-seed-evals/results/<date>-<hash>.md and every run to the gitignored
logs/seed-<date>-<hash>.jsonl. Seed messages are synthetic; their replies may be stored there only.
"""

import argparse
import datetime
import math
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path

# Imported first: the CLI guard turns a bad .env value into one line without the value, and its
# logging helper keeps log lines out of the terminal. Importing it loads and validates settings.
from app.entrypoints.cli import TEXT_TRACING_NOTICE, configure_cli_logging

# isort: split
from app.coach.coach_factory import CoachConfigError, build_coach, text_capture_enabled
from app.coach.conversation.coach import Coach
from app.coach.prompts.prompt_registry import PromptRegistryError
from app.core.config import Settings, settings
from app.core.config.base import BASE_DIR
from app.evals.seed_messages import SEED_PATH, SeedFileError, load_seed
from app.evals.seed_report import RunInfo, render_report, report_paths, write_report, write_runs
from app.evals.seed_runner import RunResult, run_seed

RESULTS_DIR = BASE_DIR / "docs" / "features" / "slice-1c-seed-evals" / "results"
LOGS_DIR = BASE_DIR / "logs"
LOG_FILE = LOGS_DIR / "run_seed.log"
INTERRUPTED_EXIT = 130


def _pause(value: str) -> float:
    try:
        seconds = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a number: {value!r}") from None
    if seconds < 0 or not math.isfinite(seconds):
        raise argparse.ArgumentTypeError(f"must be 0 or more seconds, got {value!r}")
    return seconds


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.scripts.run_seed")
    parser.add_argument(
        "--pause-seconds",
        type=_pause,
        default=5.0,
        help="wait between model calls to stay under the rate limit (default 5, 0 = no wait)",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    build: Callable[[Settings], Coach] = build_coach,
    sleep: Callable[[float], None] = time.sleep,
    today: Callable[[], datetime.date] = datetime.date.today,
    seed_path: Path = SEED_PATH,
    results_dir: Path = RESULTS_DIR,
    logs_dir: Path = LOGS_DIR,
) -> int:
    args = _parser().parse_args(argv)
    try:
        messages = load_seed(seed_path)
        coach = build(settings)
    except (SeedFileError, CoachConfigError, PromptRegistryError) as error:
        print(f"Cannot run the seed evals: {error}", file=sys.stderr)
        return 1

    info = RunInfo(coach.model_name, coach.prompt_version, coach.prompt_hash)
    day = today()
    tracing = settings.langfuse.enabled
    print(f"model: {info.model}  prompt: {info.prompt_version}  hash: {info.prompt_hash}")
    if tracing and text_capture_enabled(settings):
        print(TEXT_TRACING_NOTICE)
    collected: list[RunResult] = []
    try:
        run_seed(
            coach,
            messages,
            pause_seconds=args.pause_seconds,
            sleep=sleep,
            record_session=tracing,
            on_result=collected.append,
        )
    except KeyboardInterrupt:
        partial = report_paths(info, day, results_dir, logs_dir).runs
        write_runs(collected, partial)
        print(f"\n(stopped: no results file written; {len(collected)} runs in {partial})")
        return INTERRUPTED_EXIT
    finally:
        coach.close()

    table, _ = render_report(collected, info, day)
    paths = write_report(collected, info, day, results_dir, logs_dir)
    print(f"\n{table}\nresults: {paths.document}\nall runs: {paths.runs}")
    return 0


if __name__ == "__main__":
    configure_cli_logging(LOG_FILE)
    sys.exit(main())
