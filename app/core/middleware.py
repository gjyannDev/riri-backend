import time

import structlog
from starlette.types import ASGIApp, Message, Receive, Scope, Send

log = structlog.get_logger("app.access")


class AccessLogMiddleware:
    """One log line per request: method, path, status, duration and (via logging) request ID.

    Successful requests to `quiet_paths` (health checks) are skipped; failures are still logged.
    The query string is never logged, since it can carry tokens.
    """

    def __init__(self, app: ASGIApp, quiet_paths: frozenset[str] = frozenset({"/health"})) -> None:
        self.app = app
        self.quiet_paths = quiet_paths

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start = time.perf_counter()
        status = 500  # an exception escaping the app becomes a 500 in the outer error layer

        async def capture_status(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, capture_status)
        finally:
            if not (status < 400 and scope["path"] in self.quiet_paths):
                log.info(
                    "request",
                    method=scope["method"],
                    path=scope["path"],
                    status=status,
                    duration_ms=round((time.perf_counter() - start) * 1000, 2),
                )
