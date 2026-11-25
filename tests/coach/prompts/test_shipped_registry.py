import json
import re

from langchain_core.messages import HumanMessage

from app.coach.prompts.prompt_registry import (
    DEFAULT_REGISTRY_PATH,
    compile_active_set,
    validate_registry,
)

BLOCK_ORDER = ("role", "constraints", "task", "input", "output", "capabilities")
SECTION_LABELS = ("ROLE", "CONSTRAINTS", "TASK", "INPUT", "OUTPUT", "CAPABILITIES")


def _system_text() -> str:
    compiled = compile_active_set(DEFAULT_REGISTRY_PATH)
    messages = compiled.template.invoke({"history": [], "user_text": "hello"}).to_messages()
    return messages[0].text


def test_shipped_registry_validates() -> None:
    validate_registry(DEFAULT_REGISTRY_PATH)


def test_active_set_is_coach_default_in_section_order() -> None:
    compiled = compile_active_set(DEFAULT_REGISTRY_PATH)

    blocks = [entry.partition("@")[0] for entry in compiled.version.split(":")[1].split(",")]
    assert compiled.version.startswith("coach_default:")
    assert tuple(blocks) == BLOCK_ORDER


def test_compiled_prompt_starts_with_role_then_constraints() -> None:
    compiled = compile_active_set(DEFAULT_REGISTRY_PATH)
    messages = compiled.template.invoke({"history": [], "user_text": "hello"}).to_messages()

    assert messages[0].text.startswith("ROLE\nYou are Riri, an AI skills coach")
    assert messages[0].text.split("\n\n")[1].startswith("CONSTRAINTS\n")
    assert messages[-1] == HumanMessage("hello")


def test_each_section_starts_with_its_label_in_order() -> None:
    sections = _system_text().split("\n\n")

    assert tuple(section.splitlines()[0] for section in sections) == SECTION_LABELS


def test_the_first_four_block_layout_is_kept_as_history() -> None:
    manifest = json.loads(DEFAULT_REGISTRY_PATH.read_text(encoding="utf-8"))

    assert manifest["sets"]["coach_4block"] == [
        "safety_scope@v1",
        "persona@v1",
        "principles@v1",
        "skills@v1",
    ]


def test_prompt_text_has_no_markdown_formatting() -> None:
    text = _system_text()

    assert not re.search(r"^\s*(#|[-*+] )", text, re.MULTILINE), "headings or bullets"
    assert "**" not in text and "__" not in text and "`" not in text
