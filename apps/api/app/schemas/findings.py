"""Schemas for the findings resource."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Protocol, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.db.enums import FindingStatus, Severity


class _FindingRow(Protocol):
    """The ORM attributes the API exposes for a finding."""

    id: uuid.UUID
    workspace_id: uuid.UUID
    scan_id: uuid.UUID
    detector_id: str
    detector_version: str
    source: str
    category: str
    title: str
    description: str
    severity: Severity
    confidence: float
    status: FindingStatus
    evidence_json: dict[str, Any] | None
    limitations: str | None
    created_at: datetime
    updated_at: datetime


class FindingRead(BaseModel):
    """A finding as returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID
    scan_id: uuid.UUID
    detector_id: str
    detector_version: str
    source: str = "rule"
    category: str
    title: str
    description: str
    severity: Severity
    confidence: float
    status: FindingStatus
    evidence: dict[str, object] | None = None
    limitations: str | None = None
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="before")
    @classmethod
    def _map_evidence(cls, data: object) -> object:
        """Expose the stored ``evidence_json`` column as ``evidence``."""
        if isinstance(data, dict) or not hasattr(data, "evidence_json"):
            return data
        row = cast("_FindingRow", data)
        return {
            "id": row.id,
            "workspace_id": row.workspace_id,
            "scan_id": row.scan_id,
            "detector_id": row.detector_id,
            "detector_version": row.detector_version,
            "source": row.source,
            "category": row.category,
            "title": row.title,
            "description": row.description,
            "severity": row.severity,
            "confidence": row.confidence,
            "status": row.status,
            "evidence": row.evidence_json,
            "limitations": row.limitations,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }


class SeverityCount(BaseModel):
    """Number of findings at one severity."""

    severity: Severity
    count: int


class StatusCount(BaseModel):
    """Number of findings at one triage status."""

    status: FindingStatus
    count: int


class SeverityBreakdown(BaseModel):
    """Aggregate counts across findings."""

    total: int
    by_severity: list[SeverityCount] = Field(default_factory=list)
    by_status: list[StatusCount] = Field(default_factory=list)
    average_confidence: float = 0.0


class FindingListResponse(BaseModel):
    """Paginated list of findings."""

    items: list[FindingRead]
    total: int
    limit: int
    offset: int


__all__ = [
    "FindingListResponse",
    "FindingRead",
    "SeverityBreakdown",
    "SeverityCount",
    "StatusCount",
]
