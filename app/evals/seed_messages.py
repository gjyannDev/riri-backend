"""Load and validate the seed messages before any model call. Synthetic messages only."""

import json
from dataclasses import dataclass
from pathlib import Path

from app.core.config.base import BASE_DIR

SEED_PATH = BASE_DIR / "evals" / "seed_v1.jsonl"
SEED_SIZE = 10
_FIELDS = ("id", "type", "text")


class SeedFileError(Exception):
    """The seed file is unusable. The message names the line or the problem, never its text."""


@dataclass(frozen=True)
class SeedMessage:
    id: str
    type: str
    text: str


def load_seed(path: Path = SEED_PATH, size: int = SEED_SIZE) -> tuple[SeedMessage, ...]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise SeedFileError(f"Cannot read seed file {path}: {error.strerror}") from None
    messages: list[SeedMessage] = []
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        messages.append(_parse(line, number))
    ids = [message.id for message in messages]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise SeedFileError(f"Duplicate seed ids: {', '.join(duplicates)}.")
    if len(messages) != size:
        raise SeedFileError(f"Seed file has {len(messages)} messages, expected {size}.")
    return tuple(messages)


def _parse(line: str, number: int) -> SeedMessage:
    try:
        row = json.loads(line)
    except json.JSONDecodeError:
        raise SeedFileError(f"Line {number} is not valid JSON.") from None
    if not isinstance(row, dict):
        raise SeedFileError(f"Line {number} is not a JSON object.")
    for field in _FIELDS:
        value = row.get(field)
        if not isinstance(value, str) or not value.strip():
            raise SeedFileError(f"Line {number} is missing a non-empty '{field}'.")
    return SeedMessage(id=row["id"], type=row["type"], text=row["text"])
