import pytest

from app.evals.seed_rules import RULES, no_fake_empathy, no_markdown, one_question


@pytest.mark.parametrize(
    ("reply", "expected"),
    [
        ("That sounds hard.", True),
        ("What happened today?", True),
        ("What happened? How do you feel?", False),
        ("Really?? That is a lot.", True),  # EC6: a run of ? is one question
        ("Wait?!? Okay, tell me more.", True),  # EC6: ?!? is one question too
        ("Wait?!? What do you mean?", False),
        ("What happened and how do you feel?", True),  # EC7: known gap, one ? passes
        ("", True),
    ],
)
def test_one_question_allows_at_most_one_question_group(reply: str, expected: bool) -> None:
    assert one_question(reply) is expected


@pytest.mark.parametrize(
    ("reply", "expected"),
    [
        ("Let's take one slow breath together.", True),
        ("Try this:\n- breathe in\n- breathe out", False),
        ("* one thing at a time", False),
        ("+ notice your feet", False),
        ("Here is a plan.\n1. Breathe in.\n2. Breathe out.", False),
        ("1) Name five things you see.", False),
        ("  - an indented bullet", False),
        ("# Grounding", False),
        ("That is **really** hard.", False),
        ("That is __really__ hard.", False),
        ("Try `box breathing` now.", False),
        ("We can do step 1. then step 2 later.", True),  # EC8: mid-sentence number
        ("Try the 5-4-3-2-1 grounding exercise.", True),  # EC8
        ("It is a 10-minute walk, not more.", True),
        ("I'm here - take your time.", True),
        ("Pick one, maybe two * at most.", True),
    ],
)
def test_no_markdown_fails_on_lists_and_markup(reply: str, expected: bool) -> None:
    assert no_markdown(reply) is expected


@pytest.mark.parametrize(
    ("reply", "expected"),
    [
        ("That sounds really heavy.", True),
        ("I understand exactly how you feel.", False),
        ("I UNDERSTAND EXACTLY what you mean.", False),  # EC9: case-insensitive
        ("Honestly, i understand exactly.", False),
        ("I understand how hard that is.", True),  # EC9: near-miss passes
        ("I know exactly how you feel.", True),  # EC9: only the literal phrase
        ("I understand\nexactly that.", True),
    ],
)
def test_no_fake_empathy_fails_only_on_the_literal_phrase(reply: str, expected: bool) -> None:
    assert no_fake_empathy(reply) is expected


def test_rules_are_named_in_report_order() -> None:
    assert [name for name, _ in RULES] == ["one_question", "no_markdown", "no_fake_empathy"]
    assert [check for _, check in RULES] == [one_question, no_markdown, no_fake_empathy]
