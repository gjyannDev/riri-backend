"""Local-only route to trigger each kind of error, for exploring responses, logs and Sentry.

Mounted only when ENVIRONMENT=local, so it does not exist in staging or production.
"""

from collections.abc import Callable
from enum import StrEnum

from fastapi import APIRouter

from app.core import errors

router = APIRouter(prefix="/_debug", tags=["debug"])


class ErrorKind(StrEnum):
    VALIDATION = "validation"
    AUTH = "auth"
    DOMAIN = "domain"
    DATABASE = "database"
    EXTERNAL = "external"
    INTERNAL = "internal"
    UNHANDLED = "unhandled"


_ERRORS: dict[ErrorKind, Callable[[], Exception]] = {
    ErrorKind.VALIDATION: lambda: errors.ValidationError("Triggered from the debug route"),
    ErrorKind.AUTH: lambda: errors.UnauthorizedError(),
    ErrorKind.DOMAIN: lambda: errors.NotFoundError("Triggered from the debug route"),
    ErrorKind.DATABASE: lambda: errors.DatabaseUnavailableError(),
    ErrorKind.EXTERNAL: lambda: errors.ExternalTimeoutError(service="debug"),
    ErrorKind.INTERNAL: lambda: errors.InternalError(),
    ErrorKind.UNHANDLED: lambda: RuntimeError("Unhandled exception from the debug route"),
}


@router.get("/errors/{kind}")
def trigger_error(kind: ErrorKind) -> None:
    raise _ERRORS[kind]()
