"""Structured logging: one setup for app code (structlog) and library loggers (stdlib).

Local: readable console lines. Elsewhere: one JSON object per line on stdout.
Every record gets the request ID (when inside a request) and has sensitive keys redacted.
"""

import io
import logging
import sys
from collections.abc import Mapping
from typing import Any

import structlog
from asgi_correlation_id import correlation_id
from structlog.typing import EventDict, Processor, WrappedLogger

REDACTED = "[REDACTED]"
SENSITIVE_KEYS = frozenset({"password", "token", "authorization", "cookie", "api_key", "secret"})

_handler: logging.Handler | None = None


def _redact(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            key: REDACTED if str(key).lower() in SENSITIVE_KEYS else _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list | tuple):
        return [_redact(item) for item in value]
    return value


def redact_sensitive(_logger: WrappedLogger, _method: str, event_dict: EventDict) -> EventDict:
    return _redact(event_dict)


def add_request_id(_logger: WrappedLogger, _method: str, event_dict: EventDict) -> EventDict:
    if request_id := correlation_id.get():
        event_dict.setdefault("request_id", request_id)
    return event_dict


def configure_logging(level: str, *, json_logs: bool) -> None:
    global _handler

    shared: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        add_request_id,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        redact_sensitive,
    ]
    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=False,
    )

    renderer: list[Processor] = (
        [structlog.processors.format_exc_info, structlog.processors.JSONRenderer()]
        if json_logs
        # Plain tracebacks: the default (Rich) one prints every frame's local variable values.
        else [
            structlog.dev.ConsoleRenderer(
                colors=sys.stdout.isatty(), exception_formatter=structlog.dev.plain_traceback
            )
        ]
    )
    stream = sys.stdout
    # Redirected stdout on Windows uses a legacy code page (cp1252). Escape characters it can't
    # encode (traceback box drawing, emoji) instead of losing the whole record.
    if isinstance(stream, io.TextIOWrapper):
        stream.reconfigure(errors="backslashreplace")
    handler = logging.StreamHandler(stream)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared,
            processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta, *renderer],
        )
    )

    root = logging.getLogger()
    if _handler is not None:
        root.removeHandler(_handler)
    root.addHandler(handler)
    root.setLevel(level)
    _handler = handler

    # Route uvicorn through the root handler; our access-log middleware replaces uvicorn's.
    for name in ("uvicorn", "uvicorn.error"):
        logging.getLogger(name).handlers.clear()
        logging.getLogger(name).propagate = True
    access = logging.getLogger("uvicorn.access")
    access.handlers.clear()
    access.propagate = False
    access.disabled = True
