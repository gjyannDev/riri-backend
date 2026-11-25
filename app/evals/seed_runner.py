"""Run each seed message through the coach, score every reply. Logs ids and verdicts only."""

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import structlog

from app.coach.conversation.coach import Coach
from app.core.errors import ExternalServiceError
from app.evals.seed_messages import SeedMessage
from app.evals.seed_rules import RULES

log = structlog.get_logger("app.evals")


@dataclass(frozen=True)
class RunResult:
    """One run of one message. `reply` and `verdicts` are empty when the run is an error."""

    message_id: str
    run: int
    reply: str | None
    verdicts: dict[str, bool] = field(default_factory=dict)
    error: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    ttft_ms: float | None = None
    session_id: str | None = None


def run_seed(
    coach: Coach,
    messages: Sequence[SeedMessage],
    *,
    runs: int = 3,
    pause_seconds: float = 5,
    sleep: Callable[[float], None] = time.sleep,
    write: Callable[[str], None] = print,
    record_session: bool = False,
    on_result: Callable[[RunResult], None] = lambda _: None,
) -> list[RunResult]:
    """Each run is a fresh conversation. Errors are recorded, never retried; Ctrl-C propagates.

    `on_result` sees each result as soon as it exists, so a caller keeps partial results.
    """
    results: list[RunResult] = []
    cases = [(message, run) for message in messages for run in range(1, runs + 1)]
    for index, (message, run) in enumerate(cases):
        if index and pause_seconds:
            sleep(pause_seconds)
        result = _run_once(coach, message, run, record_session)
        write(_progress(result))
        log.info(
            "seed_run",
            message_id=result.message_id,
            run=result.run,
            outcome="error" if result.error else "scored",
            error_code=result.error,
            **result.verdicts,
        )
        results.append(result)
        on_result(result)
    return results


def _run_once(coach: Coach, message: SeedMessage, run: int, record_session: bool) -> RunResult:
    coach.reset()
    session_id = coach.session_id if record_session else None
    try:
        reply = "".join(coach.respond(message.text))
    except ExternalServiceError as error:
        return RunResult(message.id, run, None, error=error.code, session_id=session_id)
    (stats,) = coach.stats()
    return RunResult(
        message.id,
        run,
        reply,
        verdicts={name: check(reply) for name, check in RULES},
        input_tokens=stats.input_tokens,
        output_tokens=stats.output_tokens,
        ttft_ms=stats.ttft_ms,
        session_id=session_id,
    )


def _progress(result: RunResult) -> str:
    head = f"{result.message_id} run {result.run}:"
    if result.error:
        return f"{head} error {result.error}"
    verdicts = " ".join(
        f"{name}={'pass' if ok else 'fail'}" for name, ok in result.verdicts.items()
    )
    return f"{head} {verdicts}"
