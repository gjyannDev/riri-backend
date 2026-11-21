"""Optional Sentry reporting. The global error handler is the only thing that reports.

Sentry starts only when SENTRY_ENABLED is on and SENTRY_DSN is set. Automatic integrations are
off so each error is reported once, and no personal data or local variable values are sent.
"""

from typing import Any

import sentry_sdk
import structlog
from sentry_sdk.integrations.atexit import AtexitIntegration
from sentry_sdk.integrations.dedupe import DedupeIntegration
from sentry_sdk.integrations.excepthook import ExcepthookIntegration

from app.core.config import Settings

log = structlog.get_logger("app.observability")

_reporting = False


def init_sentry(settings: Settings) -> bool:
    global _reporting
    _reporting = False
    config = settings.sentry
    if not config.enabled:
        return False
    if config.dsn is None:
        if settings.ENVIRONMENT != "local":
            log.warning("sentry_dsn_missing", environment=settings.ENVIRONMENT)
        return False

    sentry_sdk.init(
        dsn=config.dsn.get_secret_value(),
        environment=settings.ENVIRONMENT,
        send_default_pii=False,
        include_local_variables=False,
        default_integrations=False,
        auto_enabling_integrations=False,
        integrations=[AtexitIntegration(), DedupeIntegration(), ExcepthookIntegration()],
    )
    _reporting = True
    return True


def report_error(exc: BaseException, content: dict[str, Any]) -> None:
    """Send server errors (status 500+) to Sentry. Never raises, so it can't break a response."""
    if not _reporting or content["status"] < 500:
        return
    try:
        sentry_sdk.capture_exception(
            exc,
            tags={
                "error.category": content.get("category"),
                "error.code": content.get("code"),
                "request_id": content.get("request_id"),
            },
        )
    except Exception:
        log.warning("sentry_capture_failed", exc_info=True)
