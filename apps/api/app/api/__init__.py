"""HTTP routers for the CyberStratum API."""

from __future__ import annotations

from app.api.findings import router as findings_router
from app.api.health import router as health_router
from app.api.knowledge import router as knowledge_router
from app.api.models import router as models_router
from app.api.scans import router as scans_router

__all__ = [
    "findings_router",
    "health_router",
    "knowledge_router",
    "models_router",
    "scans_router",
]
