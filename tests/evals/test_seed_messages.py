from pathlib import Path

import pytest

from app.evals.seed_messages import SEED_PATH, SeedFileError, load_seed

_GOOD = '{"id": "%s", "type": "angry", "text": "A synthetic message."}'


def _write(tmp_path: Path, *lines: str) -> Path:
    path = tmp_path / "seed.jsonl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_the_real_seed_file_has_ten_unique_messages_covering_the_named_types() -> None:
    messages = load_seed(SEED_PATH)

    assert len(messages) == 10
    assert len({m.id for m in messages}) == 10
    assert {"angry", "numb", "rambling", "one_word", "resistant"} <= {m.type for m in messages}


def test_blank_lines_are_ignored(tmp_path: Path) -> None:
    path = _write(tmp_path, _GOOD % "a", "", _GOOD % "b")

    assert [m.id for m in load_seed(path, size=2)] == ["a", "b"]


@pytest.mark.parametrize(
    ("lines", "message"),
    [
        (["{not json"], "Line 1 is not valid JSON."),
        (['["a", "list"]'], "Line 1 is not a JSON object."),
        ([_GOOD % "a", '{"id": "b", "type": "angry"}'], "Line 2 is missing a non-empty 'text'."),
        (['{"id": "a", "type": " ", "text": "x"}'], "Line 1 is missing a non-empty 'type'."),
        (['{"id": 7, "type": "t", "text": "x"}'], "Line 1 is missing a non-empty 'id'."),
        ([_GOOD % "a", _GOOD % "a"], "Duplicate seed ids: a."),
        ([_GOOD % "a"], "Seed file has 1 messages, expected 2."),
    ],
)
def test_a_bad_seed_file_names_the_problem(tmp_path: Path, lines: list[str], message: str) -> None:
    with pytest.raises(SeedFileError) as error:
        load_seed(_write(tmp_path, *lines), size=2)

    assert str(error.value) == message


def test_a_bad_line_error_does_not_repeat_the_message_text(tmp_path: Path) -> None:
    path = _write(tmp_path, '{"id": "a", "type": "t", "text": "private words"', _GOOD % "b")

    with pytest.raises(SeedFileError) as error:
        load_seed(path, size=2)

    assert "private" not in str(error.value)


def test_a_missing_file_is_a_seed_error(tmp_path: Path) -> None:
    with pytest.raises(SeedFileError, match="Cannot read seed file"):
        load_seed(tmp_path / "absent.jsonl")
