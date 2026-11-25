import json
from pathlib import Path

import pytest

from app.scripts.prompts import main


@pytest.fixture
def registry(tmp_path: Path) -> Path:
    """A declared-but-empty registry, as a developer writes it before the first `add`."""
    (tmp_path / "blocks").mkdir()
    (tmp_path / "blocks" / "persona_v1.md").write_text("Warm and calm.", encoding="utf-8")
    path = tmp_path / "prompt_registry.json"
    manifest = {
        "active_set": "coach_default",
        "blocks": {"persona": {"versions": {}}},
        "sets": {"coach_default": []},
    }
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def _run(registry: Path, *args: str) -> int:
    return main(["--registry", str(registry), *args])


def test_add_registers_a_version(registry: Path, capsys: pytest.CaptureFixture[str]) -> None:
    file = registry.parent / "blocks" / "persona_v1.md"

    code = _run(registry, "add", "persona", str(file), "--note", "First persona.")

    assert code == 0
    assert capsys.readouterr().out.strip() == "Added persona@v1"
    entry = json.loads(registry.read_text(encoding="utf-8"))["blocks"]["persona"]["versions"]["v1"]
    assert entry["note"] == "First persona."
    assert len(entry["sha256"]) == 64


def test_add_without_a_note_is_refused(registry: Path) -> None:
    file = str(registry.parent / "blocks" / "persona_v1.md")
    before = registry.read_bytes()

    with pytest.raises(SystemExit) as missing:
        _run(registry, "add", "persona", file)
    blank = _run(registry, "add", "persona", file, "--note", " ")

    assert missing.value.code == 2
    assert blank == 1
    assert registry.read_bytes() == before


def test_activate_then_check(registry: Path, capsys: pytest.CaptureFixture[str]) -> None:
    file = str(registry.parent / "blocks" / "persona_v1.md")
    _run(registry, "add", "persona", file, "--note", "First persona.")

    activated = _run(registry, "activate", "coach_default", "persona", "v1")
    checked = _run(registry, "check")

    lines = capsys.readouterr().out.strip().splitlines()
    assert (activated, checked) == (0, 0)
    assert lines[1] == "Activated persona@v1 in coach_default"
    assert lines[2].startswith("OK coach_default:persona@v1 hash=")


def test_errors_exit_non_zero_with_one_line(
    registry: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    activated = _run(registry, "activate", "coach_default", "persona", "v9")
    checked = _run(registry, "check")

    err = capsys.readouterr().err.strip().splitlines()
    assert (activated, checked) == (1, 1)
    assert err[0].startswith("error: ") and "persona@v9" in err[0]
    assert err[1] == "error: Active set 'coach_default' has no blocks."
