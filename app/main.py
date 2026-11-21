from uuid import uuid4

from asgi_correlation_id import CorrelationIdMiddleware
from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.debug import router as debug_router
from app.core.errors.handlers import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import AccessLogMiddleware
from app.core.observability import init_sentry

REQUEST_ID_HEADER = "X-Request-ID"


def create_app() -> FastAPI:
    configure_logging(settings.log.level, json_logs=settings.ENVIRONMENT != "local")
    init_sentry(settings)

    app = FastAPI(
        title=settings.PROJECT_NAME,
        openapi_url=f"{settings.API_V1_PREFIX}/openapi.json",
        docs_url=None if settings.ENVIRONMENT == "production" else "/docs",
        redoc_url=None,
    )

    # Added innermost first: CORS -> unhandled-error catcher -> access log -> request ID.
    if settings.BACKEND_CORS_ORIGINS:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.BACKEND_CORS_ORIGINS,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=[REQUEST_ID_HEADER],
        )
    register_exception_handlers(app)
    app.add_middleware(AccessLogMiddleware)
    app.add_middleware(
        CorrelationIdMiddleware,
        header_name=REQUEST_ID_HEADER,
        generator=lambda: str(uuid4()),
    )

    # Include feature module routers here, e.g. api_router.include_router(items_router)
    api_router = APIRouter(prefix=settings.API_V1_PREFIX)
    app.include_router(api_router)

    @app.get("/health", tags=["health"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    if settings.ENVIRONMENT == "local":
        app.include_router(debug_router)

    return app


app = create_app()
