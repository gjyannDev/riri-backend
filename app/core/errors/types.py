from typing import Any

from app.core.errors.base import AppError, ErrorCategory

# --- validation: bad input from the client ---


class ValidationError(AppError):
    category = ErrorCategory.VALIDATION
    status = 422
    code = "VALIDATION_ERROR"
    title = "Request validation failed"


class BadRequestError(ValidationError):
    status = 400
    code = "BAD_REQUEST"
    title = "Bad request"


class MethodNotAllowedError(ValidationError):
    status = 405
    code = "METHOD_NOT_ALLOWED"
    title = "Method not allowed"


# --- auth: not authenticated, or not allowed ---


class AuthError(AppError):
    category = ErrorCategory.AUTH
    status = 401
    code = "AUTH_ERROR"
    title = "Authentication failed"


class UnauthorizedError(AuthError):
    code = "UNAUTHORIZED"
    title = "Could not validate credentials"
    headers_ = {"WWW-Authenticate": "Bearer"}


class ForbiddenError(AuthError):
    status = 403
    code = "FORBIDDEN"
    title = "You do not have permission to do this"


# --- domain: business rules ---


class DomainError(AppError):
    category = ErrorCategory.DOMAIN
    status = 422
    code = "DOMAIN_ERROR"
    title = "The request could not be completed"


class NotFoundError(DomainError):
    status = 404
    code = "NOT_FOUND"
    title = "Resource not found"


class ConflictError(DomainError):
    status = 409
    code = "RESOURCE_CONFLICT"
    title = "Resource already exists"


class RuleViolationError(DomainError):
    code = "RULE_VIOLATION"
    title = "The request breaks a business rule"


# --- database: unavailable, timed out, or an unhandled constraint failure ---


class DatabaseError(AppError):
    category = ErrorCategory.DATABASE
    code = "DATABASE_ERROR"
    title = "A database error occurred"


class DatabaseUnavailableError(DatabaseError):
    status = 503
    code = "DATABASE_UNAVAILABLE"
    title = "Database is unavailable"
    retryable = True


class DatabaseConflictError(DatabaseError):
    status = 409
    code = "CONFLICT"
    title = "Resource conflicts with existing data"


# --- external: outside services (LLM, speech, payments) ---


class ExternalServiceError(AppError):
    category = ErrorCategory.EXTERNAL
    status = 502
    code = "EXTERNAL_SERVICE_ERROR"
    title = "An external service failed"

    def __init__(self, detail: str | None = None, *, service: str, **extras: Any) -> None:
        super().__init__(detail, service=service, **extras)


class ExternalTimeoutError(ExternalServiceError):
    status = 504
    code = "EXTERNAL_TIMEOUT"
    title = "An external service timed out"
    retryable = True


class ExternalRateLimitedError(ExternalServiceError):
    status = 503
    code = "EXTERNAL_RATE_LIMITED"
    title = "An external service is rate limiting requests"
    retryable = True

    def __init__(
        self,
        detail: str | None = None,
        *,
        service: str,
        retry_after: int | None = None,
        **extras: Any,
    ) -> None:
        headers = {"Retry-After": str(retry_after)} if retry_after is not None else None
        super().__init__(detail, service=service, headers=headers, **extras)


class ExternalBadResponseError(ExternalServiceError):
    code = "EXTERNAL_BAD_RESPONSE"
    title = "An external service returned an invalid response"


# --- internal: bugs and unknown exceptions ---


class InternalError(AppError):
    code = "INTERNAL_ERROR"
    title = "An unexpected error occurred"
