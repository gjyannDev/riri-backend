from dataclasses import dataclass


@dataclass(frozen=True)
class TurnStats:
    """Numbers for one completed turn. Never text."""

    turn: int
    ttft_ms: float | None
    total_ms: float
    input_tokens: int | None
    output_tokens: int | None
    truncated: bool
