"""Builds tracing from settings, and holds the LangSmith guard.

Vendor code (Langfuse) lives here and in `tracing_handler.py` only. Every method that touches the
network or the SDK swallows its own failures: tracing may never break or slow a coach turn.
"""

import os
import threading
from typing import Any

import structlog
from langchain_core.runnables import RunnableConfig
from langfuse import Langfuse
from opentelemetry.sdk.trace.export import SpanExporter

from app.coach.tracing.tracing_call import Metadata, TracedCall, UntracedCall
from app.coach.tracing.tracing_handler import MaskedCallbackHandler
from app.coach.tracing.tracing_masking import mask_otel_spans, mask_otel_spans_keeping_text
from app.core.config.langfuse import LangfuseSettings

log = structlog.get_logger("app.coach.tracing")

DEFAULT_CLOSE_TIMEOUT_S = 5.0


class TracingConfigError(Exception):
    """A required Langfuse setting is missing. The message names the setting, never its value."""


def force_langsmith_off() -> None:
    """LangChain reads these itself and would send conversation text to LangSmith. Never wanted.

    This writes the environment because LangChain reads it; it is the one allowed exception to
    "settings only through app.core.config".
    """
    os.environ["LANGSMITH_TRACING"] = "false"
    os.environ["LANGCHAIN_TRACING_V2"] = "false"


def _log_failure(operation: str, error: Exception) -> None:
    # The type only: the message may echo what the server or SDK was given.
    log.warning("tracing_failed", operation=operation, error_type=type(error).__name__)


class _LangfuseCall:
    def __init__(self, client: Langfuse, trace_id: str, config: RunnableConfig) -> None:
        self._client = client
        self._trace_id = trace_id
        self._config = config

    @property
    def config(self) -> RunnableConfig:
        return self._config

    @property
    def trace_id(self) -> str:
        return self._trace_id

    def finish(self, outcome: str) -> None:
        try:
            self._client.create_score(
                name="outcome", value=outcome, trace_id=self._trace_id, data_type="CATEGORICAL"
            )
        except Exception as error:
            _log_failure("finish", error)


class LangfuseTracing:
    def __init__(self, client: Langfuse, public_key: str, close_timeout_s: float) -> None:
        self._client = client
        self._public_key = public_key
        self._close_timeout_s = close_timeout_s

    def start_call(self, *, session_id: str, metadata: Metadata) -> TracedCall:
        try:
            trace_id = Langfuse.create_trace_id()
            handler = MaskedCallbackHandler(
                public_key=self._public_key, trace_context={"trace_id": trace_id}
            )
        except Exception as error:
            _log_failure("start_call", error)
            return UntracedCall()
        config = RunnableConfig(
            callbacks=[handler], metadata={"langfuse_session_id": session_id, **metadata}
        )
        return _LangfuseCall(self._client, trace_id, config)

    def close(self) -> None:
        thread = threading.Thread(target=self._shutdown, daemon=True)
        thread.start()
        thread.join(self._close_timeout_s)
        if thread.is_alive():
            log.warning("tracing_flush_timeout", timeout_s=self._close_timeout_s)

    def _shutdown(self) -> None:
        try:
            self._client.shutdown()
        except Exception as error:
            _log_failure("close", error)


def build_tracing(
    settings: LangfuseSettings,
    *,
    span_exporter: SpanExporter | None = None,
    close_timeout_s: float = DEFAULT_CLOSE_TIMEOUT_S,
    flush_interval_s: float | None = None,
    capture_text: bool = False,
) -> LangfuseTracing | None:
    """None when tracing is off. `span_exporter` replaces the network sender (tests only).

    `flush_interval_s` is how often pending spans are sent; None keeps the SDK default.
    `capture_text` lets input and output text through the mask; the caller decides it per
    environment. Raises `TracingConfigError` when enabled with a missing or blank key.

    Langfuse keeps one client per public key for the whole process: a second call with the same
    key returns the first client, ignoring the new mask, exporter and settings, and after
    `close()` it would return a client that has already shut down. Build tracing once per
    process (the CLI does; a long-lived door must too).
    """
    if not settings.enabled:
        return None
    public_key = _required(settings.public_key, "LANGFUSE_PUBLIC_KEY")
    secret_key = _required(settings.secret_key, "LANGFUSE_SECRET_KEY")
    client = Langfuse(
        public_key=public_key,
        secret_key=secret_key,
        base_url=settings.base_url,
        mask_otel_spans=mask_otel_spans_keeping_text if capture_text else mask_otel_spans,
        span_exporter=span_exporter,
        flush_interval=flush_interval_s,
    )
    return LangfuseTracing(client, public_key, close_timeout_s)


def _required(secret: Any, name: str) -> str:
    value = secret.get_secret_value().strip() if secret is not None else ""
    if not value:
        raise TracingConfigError(
            f"{name} is not set. Add it to .env, or set LANGFUSE_ENABLED=false to turn tracing off."
        )
    return value
