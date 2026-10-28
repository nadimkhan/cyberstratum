"""Health endpoints.

``/health`` is a public liveness probe. ``/api/health`` is a readiness probe
that also reports database and queue reachability. Neither leaks credentials,
hostnames or stack traces (design doc section 10.1).
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Response, status
from sqlalchemy import text

from app.core.logging import get_logger
from app.db.session import get_engine
from app.queue.connection import get_redis
from app.schemas.health import DependencyStatus, HealthResponse, ReadinessResponse

log = get_logger(__name__)

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse, summary="Liveness probe")
def health() -> HealthResponse:
    """Return a static liveness response."""
    return HealthResponse(
        status="ok",
        service="cyberstratum-api",
        version="0.1.0",
        timestamp=datetime.now(UTC),
    )


def _check_database() -> DependencyStatus:
    started = time.perf_counter()
    try:
        with get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 - any failure means not ready
        log.warning("health_db_check_failed", error=str(exc))
        return DependencyStatus(name="database", status="error", detail="Database unreachable")
    latency = round((time.perf_counter() - started) * 1000, 2)
    return DependencyStatus(name="database", status="ok", latency_ms=latency)


def _check_queue() -> DependencyStatus:
    started = time.perf_counter()
    try:
        get_redis().ping()
    except Exception as exc:  # noqa: BLE001 - any failure means degraded
        log.warning("health_queue_check_failed", error=str(exc))
        return DependencyStatus(name="queue", status="error", detail="Queue unreachable")
    latency = round((time.perf_counter() - started) * 1000, 2)
    return DependencyStatus(name="queue", status="ok", latency_ms=latency)


@router.get(
    "/api/health",
    response_model=ReadinessResponse,
    summary="Readiness probe",
)
def readiness(response: Response) -> ReadinessResponse:
    """Report service readiness including dependency checks."""
    checks = [_check_database(), _check_queue()]
    overall: Literal["ok", "degraded", "error"]
    if any(check.status == "error" for check in checks):
        overall = "error"
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    elif any(check.status == "degraded" for check in checks):
        overall = "degraded"
    else:
        overall = "ok"

    return ReadinessResponse(
        status=overall,
        service="cyberstratum-api",
        version="0.1.0",
        timestamp=datetime.now(UTC),
        checks=checks,
    )


__all__ = ["router"]
