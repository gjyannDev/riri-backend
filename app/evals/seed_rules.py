"""The three seed rule checks: pure, literal string tests on one reply. Never tuned for a pass."""

import re
from collections.abc import Callable

_QUESTION_GROUP = re.compile(r"\?[?!]*")
_LIST_LINE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s", re.MULTILINE)
_HEADING_LINE = re.compile(r"^\s*#", re.MULTILINE)
_INLINE_MARKERS = ("`", "**", "__")


def one_question(reply: str) -> bool:
    """At most one question. `??` or `?!?` counts once; two questions with one `?` pass."""
    return len(_QUESTION_GROUP.findall(reply)) <= 1


def no_markdown(reply: str) -> bool:
    """No bullet or numbered list lines, no headings, no backticks, bold or underline markers."""
    if _LIST_LINE.search(reply) or _HEADING_LINE.search(reply):
        return False
    return not any(marker in reply for marker in _INLINE_MARKERS)


def no_fake_empathy(reply: str) -> bool:
    """The literal phrase "I understand exactly", case-insensitive. Near-misses pass on purpose."""
    return "i understand exactly" not in reply.lower()


RULES: tuple[tuple[str, Callable[[str], bool]], ...] = (
    ("one_question", one_question),
    ("no_markdown", no_markdown),
    ("no_fake_empathy", no_fake_empathy),
)
