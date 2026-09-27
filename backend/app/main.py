import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.exceptions import (
    LifeThreadException,
    http_exception_handler,
    lifethread_exception_handler,
    unhandled_exception_handler,
    validation_exception_handler,
)
from app.core.logging import setup_logging
from app.db.session import close_db_engine
from app.middleware.request_id import RequestIDMiddleware
from app.middleware.security import RateLimitMiddleware, SecurityHeadersMiddleware
from app.middleware.timing import TimingMiddleware
from app.schemas.health import HealthResponse

logger = logging.getLogger("lifethread.backend")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan context manager for startup and shutdown hooks."""
    settings = get_settings()
    setup_logging(
        level=settings.LOG_LEVEL,
        json_format=(settings.ENVIRONMENT == "production"),
    )
    from app.core.secrets import validate_secrets_configuration
    try:
        validate_secrets_configuration(settings)
    except Exception as exc:
        if getattr(settings, "STRICT_SECRET_VALIDATION", False):
            raise
        logger.warning("Secret validation warning: %s", exc)

    logger.info(
        "LifeThread backend initializing",
        extra={"environment": settings.ENVIRONMENT, "debug": settings.DEBUG},
    )

    # Initialize tables if SQLite or initial deployment
    try:
        from app.db.base import Base
        from app.db.session import get_engine
        engine = get_engine()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables verified/created successfully.")
    except Exception as exc:
        logger.warning("Could not auto-initialize database tables: %s", exc)

    yield
    await close_db_engine()
    logger.info("LifeThread backend shutting down")


def create_application() -> FastAPI:
    """Application factory building the configured FastAPI instance."""
    settings = get_settings()

    tags_metadata = [
        {
            "name": "Health & Readiness",
            "description": "Liveness and readiness probes for platform orchestration and load balancers.",
        },
        {
            "name": "System",
            "description": "Root service discovery and application information.",
        },
    ]

    app = FastAPI(
        title=settings.PROJECT_NAME,
        description=settings.PROJECT_DESCRIPTION,
        version=settings.VERSION,
        openapi_tags=tags_metadata,
        docs_url=settings.DOCS_URL
        if settings.DEBUG or settings.ENVIRONMENT != "production"
        else None,
        redoc_url=settings.REDOC_URL
        if settings.DEBUG or settings.ENVIRONMENT != "production"
        else None,
        openapi_url=settings.OPENAPI_URL,
        contact={
            "name": "LifeThread Engineering",
            "email": "engineering@lifethread.ai",
        },
        license_info={
            "name": "Proprietary",
        },
        lifespan=lifespan,
    )

    # 1. Global Exception Handlers
    app.add_exception_handler(LifeThreadException, lifethread_exception_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)

    from starlette.middleware.gzip import GZipMiddleware

    # 2. Middleware Stack (Executed in reverse order of addition on requests)
    # Execution flow on request: CORS -> SecurityHeaders -> RateLimit -> RequestID -> GZip -> Timing -> Route
    # Execution flow on response: Route -> Timing -> GZip -> RequestID -> RateLimit -> SecurityHeaders -> CORS
    app.add_middleware(TimingMiddleware)
    app.add_middleware(GZipMiddleware, minimum_size=500)
    app.add_middleware(RequestIDMiddleware)
    if settings.RATE_LIMIT_ENABLED:
        app.add_middleware(RateLimitMiddleware)
    if settings.SECURITY_HEADERS_ENABLED:
        app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.BACKEND_CORS_ORIGINS,
        allow_origin_regex=r"https://.*\.onrender\.com|https://.*\.vercel\.app|http://localhost:\d+|http://127\.0\.0\.1:\d+",
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
        allow_headers=["*"],
        expose_headers=["Content-Length", "X-Request-ID"],
        max_age=86400,
    )

    # 3. API Routers
    app.include_router(api_router, prefix=settings.API_V1_STR)

    # 4. Top-level /health alias for backwards compatibility and container probes
    @app.get(
        "/health",
        response_model=HealthResponse,
        status_code=status.HTTP_200_OK,
        tags=["Health & Readiness"],
        summary="Top-level Liveness Check",
    )
    async def top_level_health() -> HealthResponse:
        return HealthResponse(
            status="ok",
            service="lifethread-api",
            version=settings.VERSION,
        )

    # 5. Root service discovery endpoint
    @app.get("/", tags=["System"])
    async def root():
        return {
            "name": settings.PROJECT_NAME,
            "version": settings.VERSION,
            "docs": settings.DOCS_URL,
            "health": f"{settings.API_V1_STR}/health",
            "ready": f"{settings.API_V1_STR}/ready",
        }

    return app


app = create_application()
