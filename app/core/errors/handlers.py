"""The one place exceptions become responses: convert, log once, report, respond.

Every exception, whether ours, FastAPI's, SQLAlchemy's or an unknown bug, is converted into an
`AppError` (or an equivalent problem), logged once by category, and returned as
application/problem+json with `code`, `category`, `retryable` and `request_id`.
"""

import sqlite3
from http import HTTPStatus
from pathlib import Path
from typing import Any

import rfc9457
import structlog
from asgi_correlation_id import correlation_id
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi_problem.handler import ExceptionHandler, add_exception_handler, new_exception_handler
from sqlalchemy.exc import IntegrityError, InterfaceError, OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import settings
from app.core.errors.base import AppError, ErrorCategory
from app.core.errors.types import (
    BadRequestError,
    ConflictError,
    DatabaseConflictError,
    DatabaseUnavailableError,
    ForbiddenError,
    InternalError,
    MethodNotAllowedError,
    NotFoundError,
    UnauthorizedError,
    ValidationError,
)
from app.core.observability import report_error

log = structlog.get_logger("app.errors")

# unique_violation, foreign_key_violation (Postgres) and their SQLite equivalents.
_CONFLICT_SQLSTATES = frozenset({"23505", "23503"})
_CONFLICT_SQLITE = frozenset(
    {"SQLITE_CONSTRAINT_UNIQUE", "SQLITE_CONSTRAINT_PRIMARYKEY", "SQLITE_CONSTRAINT_FOREIGNKEY"}
)

_HTTP_ERRORS: dict[int, type[AppError]] = {
    400: BadRequestError,
    401: UnauthorizedError,
    403: ForbiddenError,
    404: NotFoundError,
    405: MethodNotAllowedError,
    409: ConflictError,
    422: ValidationError,
}


# --- conversion: library exception -> problem ---


def _integrity(_eh: ExceptionHandler, _request: Request, exc: IntegrityError) -> AppError:
    orig = exc.orig
    is_conflict = (
        getattr(orig, "sqlstate", None) in _CONFLICT_SQLSTATES
        or getattr(orig, "sqlite_errorname", None) in _CONFLICT_SQLITE
    )
    # Not-null and check violations mean our code sent bad data: a bug, not a client conflict.
    return DatabaseConflictError() if is_conflict else InternalError()


def _database_unavailable(_eh: ExceptionHandler, _request: Request, _exc: Exception) -> AppError:
    return DatabaseUnavailableError()


def _http(_eh: ExceptionHandler, _request: Request, exc: HTTPException) -> rfc9457.Problem:
    status = HTTPStatus(exc.status_code)
    detail = exc.detail if isinstance(exc.detail, str) and exc.detail != status.phrase else None
    if cls := _HTTP_ERRORS.get(status):
        return cls(detail, headers=exc.headers)
    category = ErrorCategory.INTERNAL if status >= 500 else ErrorCategory.VALIDATION
    return rfc9457.Problem(
        status.phrase,
        status=status.value,
        detail=detail,
        headers=dict(exc.headers) if exc.headers is not None else None,
        code=status.name,
        category=category.value,
        retryable=status in (HTTPStatus.TOO_MANY_REQUESTS, HTTPStatus.SERVICE_UNAVAILABLE),
    )


def _validation(_eh: ExceptionHandler, _request: Request, exc: RequestValidationError) -> AppError:
    # Pydantic's "input" is deliberately dropped, so submitted passwords are never echoed back.
    errors = [
        {
            "field": ".".join(str(part) for part in err["loc"]),
            "issue": err["msg"],
            "type": err["type"],
        }
        for err in exc.errors()
    ]
    return ValidationError(errors=errors)


def _unhandled(_eh: ExceptionHandler, _request: Request, exc: Exception) -> AppError | None:
    if isinstance(exc, rfc9457.Problem):
        return None  # already a problem: the library returns it as is
    if settings.ENVIRONMENT == "local":
        return InternalError(debug={"type": type(exc).__name__, "message": str(exc)})
    return InternalError()


# --- hooks: remember the exception, then finish the response and log it once ---


def _remember(request: Request, exc: Exception) -> None:
    request.state.error = exc


def _finish(content: dict, request: Request, response: JSONResponse) -> tuple[dict, JSONResponse]:
    exc: Exception = request.state.error
    content["request_id"] = correlation_id.get()
    response.body = response.render(content)
    _log(exc, content)
    report_error(exc, content)
    return content, response


def _log(exc: Exception, content: dict[str, Any]) -> None:
    status, category = content["status"], content.get("category")
    fields: dict[str, Any] = {
        "code": content.get("code"),
        "category": category,
        "status": status,
        "error_type": type(exc).__name__,
        "location": _raise_location(exc),
    }
    if "errors" in content:
        fields["errors"] = content["errors"]
    if isinstance(exc, IntegrityError):
        fields["constraint"] = _constraint(exc)

    if status >= 500:
        log.error("request_error", exc_info=exc, **fields)
    elif category in (ErrorCategory.AUTH, ErrorCategory.DATABASE):
        log.warning("request_error", **fields)
    else:
        log.info("request_error", **fields)


def _constraint(exc: IntegrityError) -> str:
    """Name the failed constraint without the row values Postgres puts in its message."""
    orig = exc.orig
    if name := getattr(getattr(orig, "diag", None), "constraint_name", None):
        return name
    if isinstance(orig, sqlite3.Error):
        return str(orig)  # e.g. "UNIQUE constraint failed: things.name" (no values)
    return type(orig).__name__


def _raise_location(exc: BaseException) -> str:
    """'path/to/file.py:42 func' of the innermost frame, where the error was raised."""
    tb = exc.__traceback__
    if tb is None:
        return ""
    while tb.tb_next:
        tb = tb.tb_next
    code = tb.tb_frame.f_code
    path = Path(code.co_filename)
    try:
        shown = path.resolve().relative_to(Path.cwd()).as_posix()
    except ValueError:
        shown = path.name
    return f"{shown}:{tb.tb_lineno} {code.co_name}"


# --- wiring ---


class CatchUnhandledMiddleware:
    """Handles exceptions no route handler caught, inside the request-ID middleware.

    Starlette would otherwise handle them in its outermost layer, which skips the request-ID
    header and re-raises so the server logs the same error a second time.
    """

    def __init__(self, app: ASGIApp, handler: ExceptionHandler) -> None:
        self.app = app
        self.handler = handler

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        started = False

        async def track_start(message: Message) -> None:
            nonlocal started
            started = started or message["type"] == "http.response.start"
            await send(message)

        try:
            await self.app(scope, receive, track_start)
        except Exception as exc:
            if started:  # too late to send an error response
                raise
            await self.handler(Request(scope), exc)(scope, receive, send)


def register_exception_handlers(app: FastAPI) -> None:
    # Values are Any: fastapi-problem types every handler as (eh, request, Exception) -> Problem,
    # but it calls them with the matched subclass and treats a None return as "no match"
    # (`_unhandled` relies on that), so the narrower, accurate signatures don't type-check.
    # Matched in order with isinstance, so the catch-all Exception handler must stay last.
    handlers: dict[type[Exception], Any] = {
        IntegrityError: _integrity,
        OperationalError: _database_unavailable,
        InterfaceError: _database_unavailable,
        PoolTimeoutError: _database_unavailable,
        HTTPException: _http,
        RequestValidationError: _validation,
        Exception: _unhandled,
    }
    eh = new_exception_handler(
        handlers=handlers,
        http_exception_handler=_http,
        request_validation_handler=_validation,
        pre_hooks=[_remember],
        post_hooks=[_finish],
        documentation_uri_template="about:blank",
        strict_rfc9457=True,
    )
    add_exception_handler(app, eh, generic_swagger_defaults=False)
    app.add_middleware(CatchUnhandledMiddleware, handler=eh)
