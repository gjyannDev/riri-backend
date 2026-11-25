"""The prompt registry: versioned prompt blocks, named sets, and compiling the active set.

The manifest (JSON) is the single source of truth. Hashes are computed here, never by hand.
"""

import hashlib
import json
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from string import Formatter
from typing import Any

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

DEFAULT_REGISTRY_PATH = Path(__file__).parent / "prompt_registry.json"

type Manifest = dict[str, Any]


class PromptRegistryError(Exception):
    """The registry is invalid or a change to it was refused."""


@dataclass(frozen=True)
class CompiledPrompt:
    template: ChatPromptTemplate
    version: str
    hash: str


def validate_registry(path: Path) -> None:
    """Check every set: references exist, metadata is complete, hashes and variables match."""
    _validated(path)


def compile_active_set(path: Path, allowed_variables: Collection[str] = ()) -> CompiledPrompt:
    """Compile the active set. Blocks may only declare variables the caller will supply."""
    manifest = _validated(path)
    set_name = manifest["active_set"]
    entries = manifest["sets"][set_name]
    if not entries:
        raise PromptRegistryError(f"Active set '{set_name}' has no blocks.")
    for entry in entries:
        block, _, version = entry.partition("@")
        declared = set(manifest["blocks"][block]["versions"][version].get("variables", []))
        if unsupplied := declared - set(allowed_variables):
            raise PromptRegistryError(
                f"set '{set_name}', {entry}: declares {sorted(unsupplied)}, which nothing supplies "
                "yet. Remove the variable in a new version, or supply it from the caller."
            )
    base = path.parent
    system = "\n\n".join(_check_entry(manifest, base, set_name, e).strip() for e in entries)
    template = ChatPromptTemplate.from_messages(
        [("system", system), MessagesPlaceholder("history"), ("human", "{user_text}")]
    )
    layout = json.dumps([["system", system], ["placeholder", "history"], ["human", "{user_text}"]])
    return CompiledPrompt(
        template=template,
        version=f"{set_name}:{','.join(entries)}",
        hash=_sha256(layout)[:12],
    )


def _validated(path: Path) -> Manifest:
    manifest = _load(path)
    _validate(manifest, path)
    return manifest


def _validate(manifest: Manifest, path: Path) -> None:
    sets = manifest.get("sets", {})
    active = manifest.get("active_set")
    if active not in sets:
        raise PromptRegistryError(f"Active set '{active}' is not defined in {path.name}.")
    for set_name, entries in sets.items():
        for entry in entries:
            _check_entry(manifest, path.parent, set_name, entry)


def add_version(
    path: Path,
    block: str,
    file: Path,
    note: str,
    variables: Sequence[str] = (),
    today: date | None = None,
) -> str:
    """Register `file` as the next version of `block`, locking its hash. Returns e.g. "v2"."""
    manifest = _load(path)
    if not note.strip():
        raise PromptRegistryError("A changelog note is required (--note).")
    versions = manifest.get("blocks", {}).get(block, {}).get("versions")
    if versions is None:
        raise PromptRegistryError(
            f"Unknown block '{block}'. Declare it under \"blocks\" in {path.name} first."
        )
    try:
        relative = file.resolve().relative_to(path.parent.resolve()).as_posix()
    except ValueError:
        raise PromptRegistryError(f"{file} is outside the registry folder {path.parent}.") from None
    if not file.is_file():
        raise PromptRegistryError(f"File not found: {file}.")
    version = f"v{max((int(v.removeprefix('v')) for v in versions), default=0) + 1}"
    info = {
        "file": relative,
        "sha256": _sha256(_read(file)),
        "date": (today or date.today()).isoformat(),
        "note": note.strip(),
        "variables": list(variables),
    }
    _check_version(path.parent, f"{block}@{version}", info)
    versions[version] = info
    _validate(manifest, path)
    _save(path, manifest)
    return version


def activate_version(path: Path, set_name: str, block: str, version: str) -> None:
    """Point `set_name` at block@version, appending the block if the set doesn't have it yet."""
    manifest = _load(path)
    entries = manifest.get("sets", {}).get(set_name)
    if entries is None:
        raise PromptRegistryError(f"Unknown set '{set_name}' in {path.name}.")
    entry = f"{block}@{version}"
    positions = [i for i, e in enumerate(entries) if e.partition("@")[0] == block]
    if positions:
        entries[positions[0]] = entry
    else:
        entries.append(entry)
    _check_entry(manifest, path.parent, set_name, entry)
    _validate(manifest, path)
    _save(path, manifest)


def _save(path: Path, manifest: Manifest) -> None:
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def _check_entry(manifest: Manifest, base: Path, set_name: str, entry: str) -> str:
    """Return the block text for `block@version` in a set, or raise naming the set and entry."""
    block, _, version = entry.partition("@")
    where = f"set '{set_name}', {entry}"
    info = manifest.get("blocks", {}).get(block, {}).get("versions", {}).get(version)
    if info is None:
        raise PromptRegistryError(f"{where}: no such block or version in the registry.")
    return _check_version(base, where, info)


def _check_version(base: Path, where: str, info: dict[str, Any]) -> str:
    for field in ("file", "sha256", "date", "note"):
        if not info.get(field):
            raise PromptRegistryError(f"{where}: missing {field}.")
    try:
        text = _read(base / info["file"])
    except FileNotFoundError:
        raise PromptRegistryError(f"{where}: file not found: {info['file']}.") from None
    if _sha256(text) != info["sha256"]:
        raise PromptRegistryError(
            f"{where}: {info['file']} no longer matches its locked hash. Never edit a version "
            "in place; add a new version with `uv run python -m app.scripts.prompts add`."
        )
    found = _variables(text, where)
    declared = set(info.get("variables", []))
    if found != declared:
        raise PromptRegistryError(
            f"{where}: template variables {sorted(found)} differ from declared {sorted(declared)}. "
            "Escape literal braces as {{ }} or declare the variable in a new version."
        )
    return text


def _variables(text: str, where: str) -> set[str]:
    try:
        names = {field for _, field, _, _ in Formatter().parse(text) if field is not None}
    except ValueError as error:
        raise PromptRegistryError(
            f"{where}: stray brace ({error}). Escape literal braces as {{{{ }}}}."
        ) from None
    if "" in names:
        raise PromptRegistryError(f"{where}: empty {{}} brace field. Name the variable.")
    return names


def _load(path: Path) -> Manifest:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise PromptRegistryError(f"Prompt registry not found: {path}") from None
    except json.JSONDecodeError as error:
        raise PromptRegistryError(f"Prompt registry {path} is not valid JSON: {error}") from None


def _read(path: Path) -> str:
    # LF-normalised so a CRLF checkout on Windows doesn't change the hash.
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
