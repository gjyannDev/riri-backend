import json
from collections.abc import Mapping
from typing import Any

import pytest
from langfuse.types import MaskOtelSpansParams, OtelSpanData, OtelSpanIdentifier

from app.coach.tracing.tracing_masking import (
    PLACEHOLDER,
    mask_otel_spans,
    mask_otel_spans_keeping_text,
)

SENTINEL = "SENTINEL-7f3a"
IDENTIFIER = OtelSpanIdentifier(trace_id="a" * 32, span_id="b" * 16)


def _export(attributes: Mapping[str, Any], mask: Any = mask_otel_spans) -> dict[str, Any]:
    """Run the mask over one span and return the attributes the sink would receive."""
    span = OtelSpanData(
        trace_id=IDENTIFIER.trace_id,
        span_id=IDENTIFIER.span_id,
        parent_span_id=None,
        name="SpyChatModel",
        instrumentation_scope_name="langfuse-sdk",
        instrumentation_scope_version=None,
        attributes=attributes,
        resource_attributes={},
    )
    result = mask(params=MaskOtelSpansParams(spans={IDENTIFIER: span}))
    assert result is not None
    patch = result.span_patches[IDENTIFIER]
    assert patch is not None
    exported = {k: v for k, v in attributes.items() if k not in patch.delete_attributes}
    return exported | dict(patch.set_attributes)


def test_ids_numbers_and_prompt_version_pass_through() -> None:
    attributes = {
        "session.id": "sess-1",
        "langfuse.observation.type": "generation",
        "langfuse.observation.level": "DEFAULT",
        "langfuse.observation.model.name": "gemini-test",
        "langfuse.observation.metadata.prompt_version": "coach_default:role@v1",
        "langfuse.observation.metadata.prompt_hash": "aa5966c524f5",
        "langfuse.observation.metadata.turn": 3,
        "langfuse.trace.metadata.prompt_hash": "aa5966c524f5",
        "langfuse.observation.metadata.thinking_level": "minimal",
        "langfuse.observation.metadata.temperature": 0.7,
        "langfuse.observation.usage_details": '{"input": 100, "output": 20, "total": 120}',
    }

    assert _export(attributes) == attributes


@pytest.mark.parametrize(
    "key",
    ["langfuse.observation.input", "langfuse.observation.output"],
)
def test_input_and_output_become_the_placeholder(key: str) -> None:
    assert _export({key: f'"user said {SENTINEL}"'})[key] == PLACEHOLDER


def test_input_and_output_that_are_absent_stay_absent() -> None:
    assert _export({"session.id": "s"}) == {"session.id": "s"}


def test_error_status_text_is_removed() -> None:
    exported = _export(
        {
            "langfuse.observation.level": "ERROR",
            "langfuse.observation.status_message": f"provider echoed {SENTINEL}",
        }
    )

    assert exported == {"langfuse.observation.level": "ERROR"}


@pytest.mark.parametrize(
    "key",
    [
        "gen_ai.prompt.0.content",
        "langfuse.observation.metadata.tags",
        "langfuse.observation.metadata.history",
        "langfuse.trace.metadata.user_text",
        "langfuse.trace.name",
        "langfuse.trace.tags",
        "user.id",
        "a.key.added.by.a.future.sdk.version",
    ],
)
def test_anything_not_on_the_allowlist_is_deleted(key: str) -> None:
    assert _export({key: SENTINEL, "session.id": "s"}) == {"session.id": "s"}


@pytest.mark.parametrize(
    "value",
    [["a", "b"], (1, 2), None],
)
def test_an_allowed_key_with_a_non_scalar_value_is_deleted(value: Any) -> None:
    assert _export({"langfuse.observation.metadata.turn": value}) == {}


@pytest.mark.parametrize("key", ["usage_details", "cost_details"])
def test_numeric_json_attributes_keep_only_numbers(key: str) -> None:
    full_key = f"langfuse.observation.{key}"
    value = json.dumps({"input": 100, "note": SENTINEL, "total": 1.5})

    exported = _export({full_key: value})

    assert json.loads(exported[full_key]) == {"input": 100, "total": 1.5}


@pytest.mark.parametrize("value", [f"not json {SENTINEL}", json.dumps([SENTINEL]), 42])
def test_numeric_json_attributes_that_are_not_a_json_object_are_deleted(value: Any) -> None:
    assert _export({"langfuse.observation.usage_details": value}) == {}


def test_model_parameters_keep_numbers_and_drop_strings() -> None:
    key = "langfuse.observation.model.parameters"
    value = json.dumps({"temperature": 0.7, "max_tokens": 512, "stop": [SENTINEL], "x": SENTINEL})

    assert json.loads(_export({key: value})[key]) == {"temperature": 0.7, "max_tokens": 512}


def test_the_sentinel_survives_nowhere_in_a_realistic_span() -> None:
    attributes = {
        "langfuse.observation.input": f'[{{"content": "{SENTINEL}"}}]',
        "langfuse.observation.output": f'"{SENTINEL}"',
        "langfuse.observation.status_message": SENTINEL,
        "langfuse.observation.metadata.tags": [SENTINEL],
        "langfuse.observation.metadata.lc_versions": SENTINEL,
        "langfuse.observation.usage_details": json.dumps({"input": 1, SENTINEL: SENTINEL}),
        "gen_ai.completion.0.content": SENTINEL,
        "session.id": "sess-1",
    }

    assert SENTINEL not in json.dumps(_export(attributes))


def test_every_span_in_a_batch_gets_its_own_patch() -> None:
    other = OtelSpanIdentifier(trace_id="c" * 32, span_id="d" * 16)
    spans = {
        IDENTIFIER: OtelSpanData(
            IDENTIFIER.trace_id, IDENTIFIER.span_id, None, "one", None, None, {"x": SENTINEL}, {}
        ),
        other: OtelSpanData(
            other.trace_id, other.span_id, None, "two", None, None, {"y": SENTINEL}, {}
        ),
    }

    result = mask_otel_spans(params=MaskOtelSpansParams(spans=spans))

    assert result is not None
    assert set(result.span_patches) == {IDENTIFIER, other}


@pytest.mark.parametrize("key", ["langfuse.observation.input", "langfuse.observation.output"])
def test_text_capture_keeps_input_and_output_as_they_are(key: str) -> None:
    exported = _export({key: f'"user said {SENTINEL}"'}, mask_otel_spans_keeping_text)

    assert exported == {key: f'"user said {SENTINEL}"'}


def test_text_capture_drops_input_that_is_not_text() -> None:
    assert _export({"langfuse.observation.input": ["x"]}, mask_otel_spans_keeping_text) == {}


def test_text_capture_still_removes_everything_else() -> None:
    attributes = {
        "langfuse.observation.status_message": f"provider echoed {SENTINEL}",
        "langfuse.observation.metadata.tags": [SENTINEL],
        "gen_ai.prompt.0.content": SENTINEL,
        "a.key.added.by.a.future.sdk.version": SENTINEL,
        "langfuse.observation.usage_details": json.dumps({"input": 1, "note": SENTINEL}),
        "session.id": "sess-1",
    }

    exported = _export(attributes, mask_otel_spans_keeping_text)

    assert SENTINEL not in json.dumps(exported)
    assert exported["session.id"] == "sess-1"
    assert json.loads(exported["langfuse.observation.usage_details"]) == {"input": 1}
