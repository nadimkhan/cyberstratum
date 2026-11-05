"""FastAPI application factory for the CyberStratum API."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api.auth import router as auth_router
from app.api.discovery import router as discovery_router
from app.api.findings import router as findings_router
from app.api.health import router as health_router
from app.api.models import router as models_router
from app.api.scans import router as scans_router
from app.core.config import get_settings
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging, get_logger

log = get_logger(__name__)

DESCRIPTION = (
    "CyberStratum — bytecode-first EVM security analysis platform. "
    "Scans are queued as background jobs; findings are triage signals that "
    "require manual validation, not proofs of exploitability."
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage application startup and shutdown."""
    settings = get_settings()
    configure_logging()
    log.info("api_starting", app_env=settings.app_env)

    if settings.app_env.lower() in {"local", "test", "development"}:
        try:
            from app.db.session import create_all

            create_all()
            log.info("api_schema_ensured")
        except Exception as exc:  # noqa: BLE001 - dev convenience only
            log.warning("api_schema_ensure_failed", error=str(exc))

    yield

    log.info("api_stopping")


def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title="CyberStratum API",
        description=DESCRIPTION,
        version="0.1.0",
        lifespan=lifespan,
        openapi_url="/openapi.json",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", settings.api_key_header],
    )

    register_error_handlers(app)

    app.include_router(health_router)
    app.include_router(scans_router)
    app.include_router(findings_router)
    app.include_router(discovery_router)
    app.include_router(auth_router)
    app.include_router(models_router)

    @app.middleware("http")
    async def _request_id_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
        request_id = request.headers.get("X-Request-ID") or ""
        request.state.request_id = request_id
        response = await call_next(request)
        if request_id:
            response.headers["X-Request-ID"] = request_id
        return response

    return app


app = create_app()

__all__ = ["app", "create_app"]
