"""Export-stage masking for traces: the last step before anything leaves the machine.

An allowlist, not a denylist: an attribute survives only if it is named here, so a key added by a
future SDK version is deleted by default. Message content (input, output, error text) never
passes; only numbers, ids and the prompt version and hash do.
"""

import json
from collections.abc import Mapping

from langfuse.types import (
    AttributeValue,
    MaskOtelSpansParams,
    MaskOtelSpansResult,
    OtelSpanPatch,
)

PLACEHOLDER = "[masked]"

_MASKED_KEYS = frozenset({"langfuse.observation.input", "langfuse.observation.output"})
_KEPT_KEYS = frozenset(
    {
        "session.id",
        "langfuse.observation.type",
        "langfuse.observation.level",
        "langfuse.observation.model.name",
        "langfuse.observation.completion_start_time",
        "langfuse.internal.is_app_root",
        "langfuse.internal.as_root",
    }
)
# JSON objects the SDK builds from numbers; anything else inside them is dropped.
_NUMBER_OBJECT_KEYS = frozenset(
    {
        "langfuse.observation.usage_details",
        "langfuse.observation.cost_details",
        "langfuse.observation.model.parameters",
    }
)
_METADATA_PREFIXES = ("langfuse.observation.metadata.", "langfuse.trace.metadata.")
_METADATA_NAMES = frozenset(
    {
        "prompt_version",
        "prompt_hash",
        "turn",
        "model",
        "thinking_level",
        "temperature",
        "is_langchain_root",
        "ls_provider",
        "ls_model_name",
        "ls_model_type",
        "ls_temperature",
        "ls_max_tokens",
        "ls_integration",
    }
)


def mask_otel_spans(*, params: MaskOtelSpansParams) -> MaskOtelSpansResult:
    """Return one patch per span. If this raises, the SDK drops the whole batch (fails closed)."""
    return _mask(params, keep_text=False)


def mask_otel_spans_keeping_text(*, params: MaskOtelSpansParams) -> MaskOtelSpansResult:
    """Same allowlist, except input and output text passes (opt-in local debugging only).

    Error text, the status message and every unknown attribute are still removed.
    """
    return _mask(params, keep_text=True)


def _mask(params: MaskOtelSpansParams, *, keep_text: bool) -> MaskOtelSpansResult:
    return MaskOtelSpansResult(
        span_patches={
            identifier: _patch(span.attributes, keep_text)
            for identifier, span in params.spans.items()
        }
    )


def _patch(attributes: Mapping[str, AttributeValue], keep_text: bool) -> OtelSpanPatch:
    delete: list[str] = []
    replace: dict[str, AttributeValue] = {}
    for key, value in attributes.items():
        if key in _MASKED_KEYS:
            if not keep_text:
                replace[key] = PLACEHOLDER
            elif not isinstance(value, str):
                delete.append(key)
        elif key in _NUMBER_OBJECT_KEYS:
            numbers = _numbers_only(value)
            if numbers is None:
                delete.append(key)
            elif numbers != value:
                replace[key] = numbers
        elif not (_is_allowed(key) and isinstance(value, (str, int, float, bool))):
            delete.append(key)
    return OtelSpanPatch(set_attributes=replace, delete_attributes=tuple(delete))


def _is_allowed(key: str) -> bool:
    if key in _KEPT_KEYS:
        return True
    return any(
        key.startswith(prefix) and key.removeprefix(prefix) in _METADATA_NAMES
        for prefix in _METADATA_PREFIXES
    )


def _numbers_only(value: AttributeValue) -> str | None:
    """Keep the numeric entries of a JSON object. None when it is not a JSON object."""
    if not isinstance(value, str):
        return None
    try:
        data = json.loads(value)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    kept = {
        k: v for k, v in data.items() if isinstance(v, (int, float)) and not isinstance(v, bool)
    }
    return json.dumps(kept)
