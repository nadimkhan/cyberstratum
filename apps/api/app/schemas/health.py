"""Health check schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Liveness response."""

    status: Literal["ok", "degraded", "error"] = Field(description="Overall service health.")
    service: str = Field(default="cyberstratum-api")
    version: str = Field(default="0.1.0")
    timestamp: datetime


class DependencyStatus(BaseModel):
    """Health of one downstream dependency."""

    name: str
    status: Literal["ok", "degraded", "error"]
    detail: str | None = None
    latency_ms: float | None = None


class ReadinessResponse(BaseModel):
    """Readiness response including dependency checks."""

    status: Literal["ok", "degraded", "error"]
    service: str = Field(default="cyberstratum-api")
    version: str = Field(default="0.1.0")
    timestamp: datetime
    checks: list[DependencyStatus] = Field(default_factory=list)


__all__ = ["DependencyStatus", "HealthResponse", "ReadinessResponse"]
