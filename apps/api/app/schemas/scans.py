"""Schemas for the scans resource."""

from __future__ import annotations

import re
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.db.enums import ScanJobStatus, ScanStatus
from app.schemas.findings import FindingRead

ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")

FORKS = (
    "frontier",
    "homestead",
    "tangerine_whistle",
    "spurious_dragon",
    "byzantium",
    "constantinople",
    "petersburg",
    "istanbul",
    "berlin",
    "london",
    "paris",
    "shanghai",
    "cancun",
    "prague",
    "osaka",
)


class ScanCreateRequest(BaseModel):
    """Request body for queueing a scan of a contract."""

    model_config = ConfigDict(extra="forbid")

    contract_address: str = Field(
        description="Deployed contract address (0x-prefixed, 20 bytes)."
    )
    chain_id: int = Field(default=1, ge=1, description="EVM chain id.")
    fork: str = Field(default="cancun", description="EVM fork / opcode table to use.")
    label: str | None = Field(default=None, max_length=200)
    workspace_id: uuid.UUID | None = Field(
        default=None,
        description="Workspace to file the scan under; defaults to the default workspace.",
    )
    enable_experimental_ml: bool = Field(
        default=False, description="Enable the optional ML detector pass."
    )
    bytecode_hex: str | None = Field(
        default=None,
        description=(
            "Optional hex bytecode to analyse directly, with or without a 0x "
            "prefix. When supplied, no RPC or explorer is contacted and the "
            "supplied bytes are the analysis input (design doc section 6.1)."
        ),
    )

    @field_validator("contract_address")
    @classmethod
    def _validate_address(cls, value: str) -> str:
        if not ADDRESS_RE.match(value):
            raise ValueError("contract_address must be a 0x-prefixed 20-byte hex address")
        return value.lower()

    @field_validator("bytecode_hex")
    @classmethod
    def _validate_bytecode(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if stripped.startswith(("0x", "0X")):
            stripped = stripped[2:]
        if not stripped:
            raise ValueError("bytecode_hex must not be empty")
        if len(stripped) % 2 != 0:
            raise ValueError("bytecode_hex must have an even number of hex characters")
        try:
            bytes.fromhex(stripped)
        except ValueError as exc:
            raise ValueError(f"bytecode_hex is not valid hex: {exc}") from exc
        return stripped.lower()

    @field_validator("fork")
    @classmethod
    def _validate_fork(cls, value: str) -> str:
        normalized = value.lower()
        if normalized not in FORKS:
            raise ValueError(f"fork must be one of {', '.join(FORKS)}")
        return normalized


class ScanJobRead(BaseModel):
    """A queue job backing a scan."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    job_type: str
    queue_name: str
    rq_job_id: str | None = None
    status: ScanJobStatus
    attempt: int
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None


class ScanArtifactRead(BaseModel):
    """An artifact produced by a scan."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: str
    content_type: str
    object_key: str
    byte_size: int | None = None
    sha256: str | None = None
    created_at: datetime


class ScanSummary(BaseModel):
    """Scan summary used in list responses."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID
    target_id: uuid.UUID
    status: ScanStatus
    fork: str
    bytecode_source: str
    queued_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    parser_version: str | None = None
    ruleset_version: str | None = None
    model_version: str | None = None
    error_code: str | None = None
    error_message_redacted: str | None = None
    created_at: datetime


class ScanDetail(ScanSummary):
    """Full scan detail including jobs, artifacts and findings."""

    jobs: list[ScanJobRead] = Field(default_factory=list)
    artifacts: list[ScanArtifactRead] = Field(default_factory=list)
    findings: list[FindingRead] = Field(default_factory=list)


class ScanListResponse(BaseModel):
    """Paginated list of scans."""

    items: list[ScanSummary]
    total: int
    limit: int
    offset: int


class ScanAcceptedResponse(BaseModel):
    """202 response returned when a scan is queued."""

    id: uuid.UUID
    status: ScanStatus
    status_url: str
    queue_name: str


ScanDetail.model_rebuild()


__all__ = [
    "ScanAcceptedResponse",
    "ScanArtifactRead",
    "ScanCreateRequest",
    "ScanDetail",
    "ScanJobRead",
    "ScanListResponse",
    "ScanSummary",
]
