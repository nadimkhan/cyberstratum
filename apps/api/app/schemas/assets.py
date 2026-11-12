"""Schemas for the tracked-asset API."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.db.enums import AssetKind


class AssetCreateRequest(BaseModel):
    """Register an address to track."""

    model_config = ConfigDict(extra="forbid")

    address: str = Field(description="Contract or wallet address to track (0x-prefixed, 20 bytes).")
    chain_id: int = Field(default=1, ge=1, description="EVM chain id.")
    label: str | None = Field(default=None, max_length=200)
    kind: AssetKind = Field(
        default=AssetKind.OWNED,
        description=(
            "Why this address is tracked: 'owned' for the workspace's own "
            "deployments, 'watched' for an address the team follows, "
            "'discovered' for a contract found by autonomous discovery."
        ),
    )
    notes: str | None = Field(default=None, max_length=2000)
    workspace_id: uuid.UUID | None = Field(
        default=None,
        description="Workspace to file the asset under; defaults to the caller's own.",
    )


class AssetRead(BaseModel):
    """One tracked asset."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID
    chain_id: uuid.UUID
    address: str
    label: str
    kind: str
    notes: str | None
    first_seen_at: datetime
    active: bool
    created_at: datetime
    updated_at: datetime


class AssetProgress(BaseModel):
    """What has happened to an address so far."""

    scan_count: int = Field(description="How many scans have been taken against this address.")
    last_scanned_at: datetime | None = Field(
        default=None, description="When the most recent scan was created."
    )
    finding_count: int = Field(description="Findings raised across every scan.")
    open_finding_count: int = Field(
        description="Findings that have not been dismissed as false positives."
    )
    by_status: dict[str, int] = Field(default_factory=dict)
    by_severity: dict[str, int] = Field(default_factory=dict)


class AssetTimelineEntry(BaseModel):
    """One dated scan in an asset's history."""

    scan_id: uuid.UUID
    created_at: datetime
    status: str
    finding_count: int
    by_status: dict[str, int] = Field(default_factory=dict)
    by_severity: dict[str, int] = Field(default_factory=dict)


class AssetDetail(BaseModel):
    """A tracked asset with its progress."""

    asset: AssetRead
    evm_chain_id: int
    progress: AssetProgress
    timeline: list[AssetTimelineEntry] = Field(default_factory=list)


class AssetListResponse(BaseModel):
    """A page of tracked assets."""

    items: list[AssetDetail]
    total: int


class AssetHistoryResponse(BaseModel):
    """The dated history of one tracked asset."""

    asset: AssetRead
    evm_chain_id: int
    progress: AssetProgress
    timeline: list[AssetTimelineEntry]
    total: int
