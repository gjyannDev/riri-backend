"""Terminal door into the coach: uv run python -m app.entrypoints.cli

A thin loop over `Coach`. Commands: /reset, /stats, /quit. Ctrl-C mid-reply cancels that turn;
Ctrl-C or EOF at the prompt exits.
"""

import logging
import sys
from collections.abc import Callable
from contextlib import closing
from pathlib import Path

from pydantic import ValidationError

# Importing the app loads and validates settings, so a bad .env value fails right here.
try:
    from app.coach.coach_factory import CoachConfigError, build_coach, text_capture_enabled
    from app.coach.conversation.coach import FALLBACK_LINE, GREETING, Coach
    from app.coach.conversation.turn_stats import TurnStats
    from app.coach.prompts.prompt_registry import PromptRegistryError
    from app.core.config import settings
    from app.core.config.base import BASE_DIR
    from app.core.errors import ExternalServiceError
    from app.core.logging import configure_logging
except ValidationError as error:
    problems = "; ".join(
        f"{error.title}.{'.'.join(map(str, problem['loc']))}: {problem['msg']}"
        for problem in error.errors()
    )
    raise SystemExit(
        f"Cannot start the coach: invalid setting {problems}. Fix the value in .env "
        "(the variable is the group prefix plus the field name, for example LLM_THINKING_LEVEL)."
    ) from None

LOG_FILE = BASE_DIR / "logs" / "cli.log"
# Third-party loggers that log every HTTP call at INFO. Their lines hold URLs, never text.
_NOISY_LOGGERS = ("httpx", "httpx2", "google_genai")

UNKNOWN_COMMAND = "Unknown command. Try /reset, /stats or /quit."
TEXT_TRACING_NOTICE = (
    "(tracing: message text IS being sent to Langfuse. Use synthetic conversations only.)"
)
NO_TURNS = "No turns yet."
COACH_PREFIX = "Riri: "
PROMPT = "you> "
_STATS_HEADER = ("turn", "ttft_ms", "total_ms", "in_tok", "out_tok", "truncated")


class CliSession:
    """Handles one input line at a time. `write` receives everything the user should see."""

    def __init__(self, coach: Coach, write: Callable[[str], None]) -> None:
        self._coach = coach
        self._write = write

    def greet(self) -> None:
        self._write(f"{COACH_PREFIX}{GREETING}\n")

    def handle(self, line: str) -> bool:
        """Process one line. Returns False when the session should end."""
        text = line.strip()
        if not text:
            return True
        match text:
            case "/quit":
                return False
            case "/reset":
                self._coach.reset()
                self.greet()
            case "/stats":
                self._write(_stats_table(self._coach.stats()))
            case _ if text.startswith("/"):
                self._write(f"{UNKNOWN_COMMAND}\n")
            case _:
                self._reply(text)
        return True

    def _reply(self, text: str) -> None:
        started = False
        try:
            # closing() makes Ctrl-C close the stream, so the coach logs the turn as cancelled.
            with closing(self._coach.respond(text)) as stream:
                for piece in stream:
                    if not started:
                        self._write(COACH_PREFIX)
                        started = True
                    self._write(piece)
        except ExternalServiceError:
            self._write(f"{'\n' if started else ''}{COACH_PREFIX}{FALLBACK_LINE}")
        self._write("\n")


def _stats_table(stats: tuple[TurnStats, ...]) -> str:
    if not stats:
        return f"{NO_TURNS}\n"
    rows = [_STATS_HEADER] + [
        (
            str(s.turn),
            _cell(s.ttft_ms),
            _cell(s.total_ms),
            _cell(s.input_tokens),
            _cell(s.output_tokens),
            "yes" if s.truncated else "no",
        )
        for s in stats
    ]
    return "".join("  ".join(cell.rjust(9) for cell in row) + "\n" for row in rows)


def _cell(value: float | int | None) -> str:
    return "?" if value is None else str(value)


def _write(text: str) -> None:
    sys.stdout.write(text)
    sys.stdout.flush()


def configure_cli_logging(path: Path) -> None:
    """Send logs to a file so they don't interleave with the streamed chat."""
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = path.open("a", encoding="utf-8")  # noqa: SIM115  (lives for the whole process)
    configure_logging(settings.log.level, json_logs=settings.ENVIRONMENT != "local", stream=stream)
    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)


def main() -> int:
    configure_cli_logging(LOG_FILE)
    try:
        coach = build_coach(settings)
    except (CoachConfigError, PromptRegistryError) as error:
        print(f"Cannot start the coach: {error}", file=sys.stderr)
        return 1

    print(f"(logs: {LOG_FILE})")
    if settings.langfuse.enabled and text_capture_enabled(settings):
        print(TEXT_TRACING_NOTICE)
    session = CliSession(coach, _write)
    session.greet()
    try:
        return _chat_loop(session)
    finally:
        coach.close()


def _chat_loop(session: CliSession) -> int:
    while True:
        try:
            line = input(PROMPT)
        except EOFError, KeyboardInterrupt:
            _write("\n")
            return 0
        try:
            if not session.handle(line):
                return 0
        except KeyboardInterrupt:
            _write("\n(stopped)\n")


if __name__ == "__main__":
    sys.exit(main())
