"""Manage the prompt registry. Hashes are computed here, never written by hand.

Run:
  uv run python -m app.scripts.prompts check
  uv run python -m app.scripts.prompts add <block> <file> --note "Why this version" [--var NAME]
  uv run python -m app.scripts.prompts activate <set> <block> <version>
"""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from app.coach.prompts.prompt_registry import (
    DEFAULT_REGISTRY_PATH,
    PromptRegistryError,
    activate_version,
    add_version,
    compile_active_set,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.scripts.prompts")
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY_PATH)
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("check", help="validate the registry and compile the active set")

    add = commands.add_parser("add", help="register a file as the next version of a block")
    add.add_argument("block")
    add.add_argument("file", type=Path)
    add.add_argument("--note", required=True, help="changelog note (required)")
    add.add_argument("--var", action="append", default=[], help="declared template variable")

    activate = commands.add_parser("activate", help="use a block version in a set")
    activate.add_argument("set")
    activate.add_argument("block")
    activate.add_argument("version")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        match args.command:
            case "check":
                compiled = compile_active_set(args.registry)
                print(f"OK {compiled.version} hash={compiled.hash}")
            case "add":
                version = add_version(args.registry, args.block, args.file, args.note, args.var)
                print(f"Added {args.block}@{version}")
            case "activate":
                activate_version(args.registry, args.set, args.block, args.version)
                print(f"Activated {args.block}@{args.version} in {args.set}")
    except PromptRegistryError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
