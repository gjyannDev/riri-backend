import inspect
import os
import threading
import time
import uuid
from typing import Any

import pytest
import structlog
from langchain_core.runnables import RunnableLambda
from langfuse import Langfuse
from pydantic import SecretStr

from app.coach.tracing import tracing_factory
from app.coach.tracing.tracing_factory import (
    DEFAULT_CLOSE_TIMEOUT_S,
    TracingConfigError,
    build_tracing,
    force_langsmith_off,
)
from app.coach.tracing.tracing_masking import mask_otel_spans, mask_otel_spans_keeping_text
from app.core.config.langfuse import LangfuseSettings
from tests.fakes.memory_span_sink import MemorySpanSink

SENTINEL = "SENTINEL-7f3a"


def _settings(**values: Any) -> LangfuseSettings:
    # The Langfuse client is shared per public key, so every test gets its own key.
    key = f"pk-lf-{uuid.uuid4().hex}"
    defaults: dict[str, Any] = {
        "enabled": True,
        "public_key": SecretStr(key),
        "secret_key": SecretStr("sk-lf-test"),
        "base_url": "http://127.0.0.1:9",
    }
    return LangfuseSettings.model_construct(**(defaults | values))


def _traced_call(tracing: Any, text: str = "hi") -> Any:
    call = tracing.start_call(session_id="sess-1", metadata={"prompt_version": "v1", "turn": 1})
    RunnableLambda(lambda value: value).invoke(text, config=call.config)
    return call


def test_disabled_builds_nothing_even_with_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("a Langfuse client was created while tracing is disabled")

    monkeypatch.setattr(tracing_factory, "Langfuse", boom)

    assert build_tracing(_settings(enabled=False)) is None


def test_a_traced_call_reaches_the_sink_with_the_session_id() -> None:
    sink = MemorySpanSink()
    tracing = build_tracing(_settings(), span_exporter=sink)
    assert tracing is not None

    _traced_call(tracing)
    tracing.close()

    assert sink.spans
    assert all(
        span.attributes and span.attributes.get("session.id") == "sess-1" for span in sink.spans
    )


def test_finish_attaches_the_outcome_as_a_score_on_the_calls_trace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scores: list[dict[str, Any]] = []
    monkeypatch.setattr(Langfuse, "create_score", lambda self, **kwargs: scores.append(kwargs))
    tracing = build_tracing(_settings(), span_exporter=MemorySpanSink())
    assert tracing is not None

    call = tracing.start_call(session_id="s", metadata={})
    call.finish("blocked")

    assert len(scores) == 1
    assert scores[0]["name"] == "outcome"
    assert scores[0]["value"] == "blocked"
    assert scores[0]["trace_id"] == call.trace_id
    tracing.close()


def test_a_failing_score_never_raises_and_logs_no_text(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(self: Any, **kwargs: Any) -> None:
        raise RuntimeError(f"server said {SENTINEL}")

    monkeypatch.setattr(Langfuse, "create_score", broken)
    tracing = build_tracing(_settings(), span_exporter=MemorySpanSink())
    assert tracing is not None
    call = tracing.start_call(session_id="s", metadata={})

    with structlog.testing.capture_logs() as logs:
        call.finish("ok")

    assert [log["event"] for log in logs] == ["tracing_failed"]
    assert logs[0]["error_type"] == "RuntimeError"
    assert SENTINEL not in str(logs)
    tracing.close()


def test_close_delivers_pending_traces() -> None:
    sink = MemorySpanSink()
    tracing = build_tracing(_settings(), span_exporter=sink)
    assert tracing is not None

    _traced_call(tracing)
    assert sink.spans == []

    tracing.close()

    assert sink.spans


def test_close_gives_up_after_its_time_limit_when_the_sink_blocks() -> None:
    release = threading.Event()
    tracing = build_tracing(
        _settings(), span_exporter=MemorySpanSink(block=release), close_timeout_s=0.3
    )
    assert tracing is not None
    _traced_call(tracing)

    started = time.perf_counter()
    with structlog.testing.capture_logs() as logs:
        tracing.close()
    elapsed = time.perf_counter() - started
    release.set()

    assert elapsed < 2
    assert [log["event"] for log in logs] == ["tracing_flush_timeout"]


@pytest.mark.parametrize(
    ("values", "setting"),
    [
        ({"public_key": None}, "LANGFUSE_PUBLIC_KEY"),
        ({"public_key": SecretStr("")}, "LANGFUSE_PUBLIC_KEY"),
        ({"secret_key": None}, "LANGFUSE_SECRET_KEY"),
        ({"secret_key": SecretStr("   ")}, "LANGFUSE_SECRET_KEY"),
    ],
)
def test_enabled_with_a_missing_or_blank_key_names_the_setting(
    values: dict[str, Any], setting: str
) -> None:
    with pytest.raises(TracingConfigError, match=setting) as error:
        build_tracing(_settings(**({"secret_key": SecretStr("sk-leak-canary")} | values)))

    assert "sk-leak-canary" not in str(error.value)


@pytest.mark.parametrize("value", ["true", "True", "1", "false"])
def test_force_langsmith_off_overrides_whatever_the_environment_says(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    for name in ("LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2"):
        monkeypatch.setenv(name, value)

    force_langsmith_off()

    assert os.environ["LANGSMITH_TRACING"] == "false"
    assert os.environ["LANGCHAIN_TRACING_V2"] == "false"


@pytest.mark.parametrize(
    ("capture_text", "expected"),
    [(False, mask_otel_spans), (True, mask_otel_spans_keeping_text)],
)
def test_the_mask_matches_the_text_capture_flag(
    monkeypatch: pytest.MonkeyPatch, capture_text: bool, expected: Any
) -> None:
    created: list[dict[str, Any]] = []

    class RecordingClient:
        def __init__(self, **kwargs: Any) -> None:
            created.append(kwargs)

    monkeypatch.setattr(tracing_factory, "Langfuse", RecordingClient)

    build_tracing(_settings(), capture_text=capture_text)

    assert created[0]["mask_otel_spans"] is expected


def test_the_default_close_limit_is_five_seconds() -> None:
    assert DEFAULT_CLOSE_TIMEOUT_S == 5.0
    assert inspect.signature(build_tracing).parameters["close_timeout_s"].default == 5.0
