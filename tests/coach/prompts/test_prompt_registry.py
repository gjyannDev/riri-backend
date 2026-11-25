import hashlib
import json
from datetime import date
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate

from app.coach.prompts.prompt_registry import (
    PromptRegistryError,
    activate_version,
    add_version,
    compile_active_set,
    validate_registry,
)

ORDER = ("safety_scope", "persona", "principles", "skills")


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _write_registry(
    root: Path,
    texts: dict[str, str] | None = None,
    order: tuple[str, ...] = ORDER,
) -> Path:
    """A valid manifest with one v1 per block, built by hand so tests can then break it."""
    texts = texts or {name: f"{name} text." for name in order}
    blocks_dir = root / "blocks"
    blocks_dir.mkdir(exist_ok=True)
    blocks = {}
    for name, text in texts.items():
        (blocks_dir / f"{name}_v1.md").write_text(text, encoding="utf-8")
        blocks[name] = {
            "versions": {
                "v1": {
                    "file": f"blocks/{name}_v1.md",
                    "sha256": _sha256(text),
                    "date": "2026-11-24",
                    "note": f"First {name}.",
                    "variables": [],
                }
            }
        }
    manifest = {
        "active_set": "coach_default",
        "blocks": blocks,
        "sets": {"coach_default": [f"{name}@v1" for name in order]},
    }
    path = root / "prompt_registry.json"
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return path


def _manifest(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _save(path: Path, manifest: dict) -> None:
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def test_compile_gives_system_then_history_then_user(tmp_path: Path) -> None:
    path = _write_registry(tmp_path)

    compiled = compile_active_set(path)
    history = [AIMessage("Hi, I'm Riri."), HumanMessage("first"), AIMessage("reply one")]
    messages = compiled.template.invoke({"history": history, "user_text": "second"}).to_messages()

    assert isinstance(compiled.template, ChatPromptTemplate)
    assert isinstance(messages[0], SystemMessage)
    system = messages[0].text
    positions = [system.index(f"{name} text.") for name in ORDER]
    assert positions == sorted(positions)
    assert system.startswith("safety_scope text.")
    assert messages[1:4] == history
    assert messages[4] == HumanMessage("second")
    assert len(messages) == 5
    assert compiled.version == "coach_default:safety_scope@v1,persona@v1,principles@v1,skills@v1"
    assert len(compiled.hash) == 12


def test_compiled_hash_tracks_the_template_text_only(tmp_path: Path) -> None:
    roots = [tmp_path / name for name in ("a", "b", "c")]
    for root in roots:
        root.mkdir()

    first = compile_active_set(_write_registry(roots[0]))
    second = compile_active_set(_write_registry(roots[1]))
    changed = compile_active_set(_write_registry(roots[2], {n: f"{n} other." for n in ORDER}))

    assert first.hash == second.hash
    assert first.hash != changed.hash


def test_missing_manifest_fails(tmp_path: Path) -> None:
    with pytest.raises(PromptRegistryError, match="missing.json"):
        compile_active_set(tmp_path / "missing.json")


def test_edited_content_without_a_new_version_fails(tmp_path: Path) -> None:
    path = _write_registry(tmp_path)
    (tmp_path / "blocks" / "persona_v1.md").write_text("persona edited in place.", encoding="utf-8")

    with pytest.raises(PromptRegistryError) as error:
        validate_registry(path)

    message = str(error.value)
    assert "persona@v1" in message and "coach_default" in message
    assert "new version" in message


def test_crlf_checkout_does_not_change_the_hash(tmp_path: Path) -> None:
    path = _write_registry(tmp_path, {name: f"{name}\nline two." for name in ORDER})
    for name in ORDER:
        (tmp_path / "blocks" / f"{name}_v1.md").write_bytes(f"{name}\r\nline two.".encode())

    validate_registry(path)


@pytest.mark.parametrize(
    ("breakage", "expected"),
    [
        ("unknown_block", "nope@v1"),
        ("unknown_version", "persona@v9"),
        ("missing_file", "persona@v1"),
        ("unknown_active_set", "other_set"),
    ],
)
def test_missing_references_fail_naming_the_set_block_and_version(
    tmp_path: Path, breakage: str, expected: str
) -> None:
    path = _write_registry(tmp_path)
    manifest = _manifest(path)
    match breakage:
        case "unknown_block":
            manifest["sets"]["coach_default"].append("nope@v1")
        case "unknown_version":
            manifest["sets"]["coach_default"][1] = "persona@v9"
        case "missing_file":
            (tmp_path / "blocks" / "persona_v1.md").unlink()
        case "unknown_active_set":
            manifest["active_set"] = "other_set"
    _save(path, manifest)

    with pytest.raises(PromptRegistryError, match=expected):
        validate_registry(path)


@pytest.mark.parametrize("field", ["date", "note"])
def test_a_version_without_date_or_note_fails(tmp_path: Path, field: str) -> None:
    path = _write_registry(tmp_path)
    manifest = _manifest(path)
    manifest["blocks"]["skills"]["versions"]["v1"][field] = ""
    _save(path, manifest)

    with pytest.raises(PromptRegistryError, match=f"skills@v1.*{field}"):
        validate_registry(path)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Say {name} warmly.", "name"),
        ("A stray { brace.", "brace"),
        ("A stray } brace.", "brace"),
        ("An empty {} field.", "brace"),
    ],
)
def test_undeclared_variables_and_stray_braces_fail(
    tmp_path: Path, text: str, expected: str
) -> None:
    texts = {name: f"{name} text." for name in ORDER} | {"persona": text}
    path = _write_registry(tmp_path, texts)

    with pytest.raises(PromptRegistryError, match=f"persona@v1.*{expected}"):
        validate_registry(path)


def test_escaped_braces_and_declared_variables_pass(tmp_path: Path) -> None:
    texts = {name: f"{name} text." for name in ORDER} | {"persona": "Use {{braces}} for {name}."}
    path = _write_registry(tmp_path, texts)
    manifest = _manifest(path)
    manifest["blocks"]["persona"]["versions"]["v1"]["variables"] = ["name"]
    _save(path, manifest)

    validate_registry(path)


def test_compile_refuses_variables_the_caller_does_not_supply(tmp_path: Path) -> None:
    texts = {name: f"{name} text." for name in ORDER} | {"persona": "Hello {name}."}
    path = _write_registry(tmp_path, texts)
    manifest = _manifest(path)
    manifest["blocks"]["persona"]["versions"]["v1"]["variables"] = ["name"]
    _save(path, manifest)

    validate_registry(path)
    with pytest.raises(PromptRegistryError, match=r"coach_default.*persona@v1.*\['name'\]"):
        compile_active_set(path)

    compiled = compile_active_set(path, allowed_variables={"name"})
    assert "name" in compiled.template.input_variables


def _new_block_file(root: Path, name: str, text: str) -> Path:
    file = root / "blocks" / name
    file.write_text(text, encoding="utf-8")
    return file


def test_add_locks_hash_date_note_and_variables(tmp_path: Path) -> None:
    path = _write_registry(tmp_path)
    file = _new_block_file(tmp_path, "persona_v2.md", "Warmer, for {name}.")

    version = add_version(
        path, "persona", file, note="Warmer tone.", variables=["name"], today=date(2026, 11, 25)
    )

    assert version == "v2"
    entry = _manifest(path)["blocks"]["persona"]["versions"]["v2"]
    assert entry == {
        "file": "blocks/persona_v2.md",
        "sha256": _sha256("Warmer, for {name}."),
        "date": "2026-11-25",
        "note": "Warmer tone.",
        "variables": ["name"],
    }
    validate_registry(path)


@pytest.mark.parametrize(
    ("block", "text", "note", "expected"),
    [
        ("persona", "Fine text.", "", "note"),
        ("persona", "Fine text.", "   ", "note"),
        ("nope", "Fine text.", "A note.", "nope"),
        ("persona", "Hello {name}.", "A note.", "name"),
    ],
)
def test_add_refuses_and_leaves_the_manifest_unchanged(
    tmp_path: Path, block: str, text: str, note: str, expected: str
) -> None:
    path = _write_registry(tmp_path)
    before = path.read_bytes()
    file = _new_block_file(tmp_path, "candidate.md", text)

    with pytest.raises(PromptRegistryError, match=expected):
        add_version(path, block, file, note=note)

    assert path.read_bytes() == before


def test_add_refuses_a_file_outside_the_registry_folder(tmp_path: Path) -> None:
    root = tmp_path / "registry"
    root.mkdir()
    path = _write_registry(root)
    outside = tmp_path / "outside.md"
    outside.write_text("Text.", encoding="utf-8")

    with pytest.raises(PromptRegistryError, match="outside"):
        add_version(path, "persona", outside, note="A note.")


def test_activate_switches_the_version_in_place(tmp_path: Path) -> None:
    path = _write_registry(tmp_path)
    add_version(path, "persona", _new_block_file(tmp_path, "p2.md", "Persona two."), note="Two.")

    activate_version(path, "coach_default", "persona", "v2")

    compiled = compile_active_set(path)
    assert compiled.version == "coach_default:safety_scope@v1,persona@v2,principles@v1,skills@v1"
    system = compiled.template.invoke({"history": [], "user_text": "x"}).to_messages()[0].text
    assert "Persona two." in system and "persona text." not in system


def test_activate_appends_a_block_not_yet_in_the_set(tmp_path: Path) -> None:
    path = _write_registry(tmp_path, order=("safety_scope", "persona"))
    manifest = _manifest(path)
    manifest["blocks"]["skills"] = {"versions": {}}
    _save(path, manifest)
    add_version(path, "skills", _new_block_file(tmp_path, "s1.md", "Skills."), note="First.")

    activate_version(path, "coach_default", "skills", "v1")

    assert _manifest(path)["sets"]["coach_default"][-1] == "skills@v1"


@pytest.mark.parametrize(
    ("set_name", "block", "version", "expected"),
    [
        ("coach_default", "persona", "v9", "persona@v9"),
        ("other_set", "persona", "v1", "other_set"),
    ],
)
def test_activate_refuses_unknown_targets_and_leaves_the_manifest_unchanged(
    tmp_path: Path, set_name: str, block: str, version: str, expected: str
) -> None:
    path = _write_registry(tmp_path)
    before = path.read_bytes()

    with pytest.raises(PromptRegistryError, match=expected):
        activate_version(path, set_name, block, version)

    assert path.read_bytes() == before
