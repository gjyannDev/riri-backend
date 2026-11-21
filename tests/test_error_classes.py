import pytest

from app.core.errors import (
    AppError,
    ConflictError,
    DatabaseConflictError,
    DatabaseUnavailableError,
    ErrorCategory,
    ExternalBadResponseError,
    ExternalRateLimitedError,
    ExternalServiceError,
    ExternalTimeoutError,
    ForbiddenError,
    InternalError,
    NotFoundError,
    UnauthorizedError,
    ValidationError,
    error_classes,
)


def test_every_error_class_defines_its_own_category_status_and_code() -> None:
    for cls in error_classes():
        assert "code" in vars(cls), f"{cls.__name__} must set its own code"
        assert isinstance(cls.category, ErrorCategory), cls.__name__
        assert 400 <= cls.status <= 599, cls.__name__
        assert cls.code.isupper() and " " not in cls.code, cls.__name__


def test_error_codes_are_unique() -> None:
    codes = [cls.code for cls in error_classes()]
    duplicates = sorted({code for code in codes if codes.count(code) > 1})
    assert duplicates == []


@pytest.mark.parametrize(
    ("cls", "category", "status", "code", "retryable"),
    [
        (ValidationError, ErrorCategory.VALIDATION, 422, "VALIDATION_ERROR", False),
        (UnauthorizedError, ErrorCategory.AUTH, 401, "UNAUTHORIZED", False),
        (ForbiddenError, ErrorCategory.AUTH, 403, "FORBIDDEN", False),
        (NotFoundError, ErrorCategory.DOMAIN, 404, "NOT_FOUND", False),
        (ConflictError, ErrorCategory.DOMAIN, 409, "RESOURCE_CONFLICT", False),
        (DatabaseUnavailableError, ErrorCategory.DATABASE, 503, "DATABASE_UNAVAILABLE", True),
        (DatabaseConflictError, ErrorCategory.DATABASE, 409, "CONFLICT", False),
        (ExternalTimeoutError, ErrorCategory.EXTERNAL, 504, "EXTERNAL_TIMEOUT", True),
        (ExternalRateLimitedError, ErrorCategory.EXTERNAL, 503, "EXTERNAL_RATE_LIMITED", True),
        (ExternalBadResponseError, ErrorCategory.EXTERNAL, 502, "EXTERNAL_BAD_RESPONSE", False),
        (InternalError, ErrorCategory.INTERNAL, 500, "INTERNAL_ERROR", False),
    ],
)
def test_category_status_code_and_retryable(cls, category, status, code, retryable) -> None:
    assert (cls.category, cls.status, cls.code, cls.retryable) == (
        category,
        status,
        code,
        retryable,
    )


def test_error_body_carries_code_category_and_retryable() -> None:
    body = NotFoundError("No session with that id").marshal()

    assert body["status"] == 404
    assert body["detail"] == "No session with that id"
    assert body["code"] == "NOT_FOUND"
    assert body["category"] == "domain"
    assert body["retryable"] is False


def test_existing_classes_keep_their_import_path_and_positional_detail() -> None:
    exc = NotFoundError("gone")

    assert isinstance(exc, AppError)
    assert exc.detail == "gone"
    assert exc.status_code == 404
    assert issubclass(ConflictError, AppError)
    assert issubclass(UnauthorizedError, AppError)


def test_unauthorized_sends_bearer_challenge() -> None:
    headers = UnauthorizedError().headers

    assert headers is not None
    assert headers["WWW-Authenticate"] == "Bearer"


def test_external_errors_name_the_service() -> None:
    body = ExternalTimeoutError(service="stt").marshal()

    assert body["service"] == "stt"
    assert issubclass(ExternalTimeoutError, ExternalServiceError)


def test_rate_limited_passes_retry_after_through() -> None:
    headers = ExternalRateLimitedError(service="llm", retry_after=30).headers

    assert headers is not None
    assert headers["Retry-After"] == "30"
