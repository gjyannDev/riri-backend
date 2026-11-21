from collections.abc import Mapping
from enum import StrEnum
from typing import Any, ClassVar

from fastapi_problem.error import StatusProblem


class ErrorCategory(StrEnum):
    VALIDATION = "validation"
    AUTH = "auth"
    DOMAIN = "domain"
    DATABASE = "database"
    EXTERNAL = "external"
    INTERNAL = "internal"


class AppError(StatusProblem):
    """Base for every error the API returns as application/problem+json.

    Subclasses set `category`, `status`, `code` (stable, unique), `title` (safe to show users)
    and `retryable`. `detail` is optional per raise; keyword extras become body fields.
    """

    category: ClassVar[ErrorCategory] = ErrorCategory.INTERNAL
    code: ClassVar[str] = "INTERNAL_ERROR"
    retryable: ClassVar[bool] = False
    status = 500
    title = "An unexpected error occurred"

    def __init__(
        self,
        detail: str | None = None,
        *,
        headers: Mapping[str, str] | None = None,
        **extras: Any,
    ) -> None:
        super().__init__(
            detail,
            headers=dict(headers) if headers is not None else None,
            code=self.code,
            category=self.category.value,
            retryable=self.retryable,
            **extras,
        )


def error_classes() -> list[type[AppError]]:
    """Every AppError subclass that has been imported, for the uniqueness test and the docs."""
    found: list[type[AppError]] = []
    pending = list(AppError.__subclasses__())
    while pending:
        cls = pending.pop()
        found.append(cls)
        pending.extend(cls.__subclasses__())
    return sorted(found, key=lambda cls: (cls.category, cls.code))
