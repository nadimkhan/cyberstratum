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
    reviewed_by: uuid.UUID | None
    reviewed_at: datetime | None
    review_note: str | None
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
    reviewed_by: uuid.UUID | None = None
    reviewed_at: datetime | None = None
    review_note: str | None = None
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
            "reviewed_by": row.reviewed_by,
            "reviewed_at": row.reviewed_at,
            "review_note": row.review_note,
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


class DetectorCount(BaseModel):
    """Number of findings raised by one detector.

    The detector is what an issue *is*; the severity is how bad it is.
    Knowing which detectors fire most often is how the catalogue gets
    read, so the breakdown is a product of the detector catalogue and
    not a free-text label.
    """

    detector_id: str
    count: int


class ChainFindingCount(BaseModel):
    """Number of findings raised on one chain."""

    chain_id: int
    chain_name: str
    count: int


class SeverityBreakdown(BaseModel):
    """Aggregate counts across findings."""

    total: int
    by_severity: list[SeverityCount] = Field(default_factory=list)
    by_status: list[StatusCount] = Field(default_factory=list)
    average_confidence: float = 0.0
    by_detector: list[DetectorCount] = Field(default_factory=list)
    by_chain: list[ChainFindingCount] = Field(default_factory=list)


class FindingListResponse(BaseModel):
    """Paginated list of findings."""

    items: list[FindingRead]
    total: int
    limit: int
    offset: int


class FindingReviewRequest(BaseModel):
    """A human verdict on a finding.

    The verdict is the label the machine learning pipeline learns from,
    so it is not a free-form field: it is one of the statuses the
    product already defines, and a false-positive verdict must carry a
    reason. A false positive without a reason cannot be told apart from
    a mistaken one, and neither is usable as ground truth.
    """

    model_config = ConfigDict(extra="forbid")

    status: FindingStatus = Field(
        description=(
            "The verdict: 'confirmed', 'false_positive', "
            "'needs_more_evidence' or 'triage'."
        )
    )
    note: str | None = Field(
        default=None,
        max_length=2000,
        description="Why. Required for a false-positive verdict.",
    )


class BulkFindingReviewRequest(BaseModel):
    """One verdict applied to every open finding of one detector.

    A reviewer who has decided that one naming-convention finding is a
    style question has decided the same thing about the others of its
    kind. Recording that once, for all of them, is what makes a
    reviewed corpus possible at all.
    """

    model_config = ConfigDict(extra="forbid")

    detector_id: str = Field(min_length=1, max_length=120)
    status: FindingStatus = Field(
        description=(
            "The verdict: 'confirmed', 'false_positive', "
            "'needs_more_evidence' or 'triage'."
        )
    )
    note: str | None = Field(
        default=None,
        max_length=2000,
        description="Why. Required for a false-positive verdict.",
    )
    limit: int = Field(
        default=200,
        ge=1,
        le=500,
        description="How many findings one action may settle.",
    )


class BulkFindingReviewResponse(BaseModel):
    """What a bulk verdict changed, and what it left alone."""

    detector_id: str
    status: FindingStatus
    applied: int = 0
    skipped: int = 0
    finding_ids: list[uuid.UUID] = Field(default_factory=list)


__all__ = [
    "BulkFindingReviewRequest",
    "BulkFindingReviewResponse",
    "FindingListResponse",
    "FindingRead",
    "FindingReviewRequest",
    "SeverityBreakdown",
    "SeverityCount",
    "StatusCount",
]
