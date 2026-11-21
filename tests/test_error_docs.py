from app.core.errors import error_classes
from app.scripts.gen_error_docs import DOC_PATH, render


def test_committed_error_code_page_is_up_to_date() -> None:
    assert DOC_PATH.read_text(encoding="utf-8") == render(), (
        "docs/error-codes.md is stale: run `uv run python -m app.scripts.gen_error_docs`"
    )


def test_every_error_code_is_documented_with_its_details() -> None:
    page = render()

    for cls in error_classes():
        retryable = "yes" if cls.retryable else "no"
        row = f"| `{cls.code}` | {cls.category.value} | {cls.status} | {retryable} |"
        assert row in page, cls.__name__
