"""FastAPI application factory."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.router import api_router
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging, request_id_var
from app.core.middleware import (
    BodySizeLimitMiddleware,
    OriginCheckMiddleware,
    RateLimitMiddleware,
    RequestContextMiddleware,
)
from app.workers.celery_app import celery_app  # noqa: F401  (binds task producers)

logger = logging.getLogger("app")

API_PREFIX = "/api"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_format)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        logger.info(
            "startup",
            extra={
                "env": settings.app_env.value,
                "version": settings.app_version,
                # AI_GRADE: "AI" (trained models when deployed) or "CLASSIC" (no ML).
                "scoring_mode": settings.scoring_mode.upper(),
            },
        )
        yield
        logger.info("shutdown")

    # Interactive API docs are a development aid only; they are not exposed publicly.
    docs_enabled = not settings.is_production
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        lifespan=lifespan,
        docs_url=f"{API_PREFIX}/docs" if docs_enabled else None,
        redoc_url=None,
        openapi_url=f"{API_PREFIX}/openapi.json" if docs_enabled else None,
    )
    app.add_middleware(OriginCheckMiddleware, allowed_origin=settings.public_base_url)
    app.add_middleware(
        RateLimitMiddleware,
        cookie_name=settings.session_cookie_name,
        per_session=settings.api_rate_limit_per_minute_session,
        per_ip=settings.api_rate_limit_per_minute_ip,
        per_ip_public=settings.api_rate_limit_per_minute_public,
    )
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_request_body_bytes)
    app.add_middleware(RequestContextMiddleware)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        # Never leak internals: a generic message plus the request id for support.
        logger.exception("unhandled error", extra={"path": request.url.path})
        return JSONResponse(
            {
                "detail": "Something went wrong on our side.",
                "request_id": getattr(request.state, "request_id", None) or request_id_var.get(),
            },
            status_code=500,
        )

    app.include_router(api_router, prefix=API_PREFIX)
    return app


app = create_app()
