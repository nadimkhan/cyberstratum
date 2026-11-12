"""Schemas for the scans resource."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.db.enums import CorrespondenceStatus, ScanJobStatus, ScanStatus
from app.schemas.findings import FindingRead
from app.services.source_compile import MAX_SOURCE_BYTES

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

    contract_address: str | None = Field(
        default=None,
        description=(
            "Deployed contract address (0x-prefixed, 20 bytes). Required unless "
            "source_code is supplied; a pasted source is filed under an address "
            "derived from the source itself."
        ),
    )
    chain_id: int = Field(default=1, ge=1, description="EVM chain id.")
    fork: str | None = Field(
        default=None,
        description=(
            "EVM fork / opcode table to use. Leave it unset and the fork is "
            "inferred from the opcodes the bytecode uses, which is correct "
            "for chains this product has not characterised yet."
        ),
    )
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
    source_code: str | None = Field(
        default=None,
        description=(
            "Optional Solidity source. It is compiled on the server and the "
            "resulting runtime bytecode is analysed, exactly as a deployed "
            "contract's bytecode is. The source map that comes with it is "
            "what lets a finding point at a line of the developer's code."
        ),
    )
    solc_version: str | None = Field(
        default=None,
        description=(
            "The solc version to compile source_code with, such as 0.8.26. "
            "The newest installed compiler is used when this is unset."
        ),
    )

    @model_validator(mode="after")
    def _one_input(self) -> ScanCreateRequest:
        if not self.contract_address and not self.bytecode_hex and not self.source_code:
            raise ValueError(
                "supply contract_address, bytecode_hex or source_code: a scan "
                "needs something to analyse"
            )
        if self.source_code and self.bytecode_hex:
            raise ValueError(
                "supply either source_code or bytecode_hex, not both: they are "
                "two different answers to the same question"
            )
        return self

    @field_validator("contract_address")
    @classmethod
    def _validate_address(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not ADDRESS_RE.match(value):
            raise ValueError("contract_address must be a 0x-prefixed 20-byte hex address")
        return value.lower()

    @field_validator("source_code")
    @classmethod
    def _validate_source(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.strip():
            raise ValueError("source_code must not be empty")
        if len(value.encode("utf-8")) > MAX_SOURCE_BYTES:
            raise ValueError(f"source_code is over the {MAX_SOURCE_BYTES} byte limit")
        return value

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
    def _validate_fork(cls, value: str | None) -> str | None:
        if value is None:
            return None
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


class SourceFileRead(BaseModel):
    """One file of the source that was analysed."""

    model_config = ConfigDict(from_attributes=True)

    path: str | None = None
    content: str


class ScanSourceRead(BaseModel):
    """The source that was analysed, when the scan stored one.

    A scan made from runtime bytecode alone has no source to show. That
    is reported in words, with ``available`` false and a reason, so an
    empty file list is never mistaken for "there was nothing there".
    """

    available: bool
    reason: str | None = None
    language: str | None = None
    compiler_version: str | None = None
    verified: bool | None = None
    source_uri: str | None = None
    files: list[SourceFileRead] = Field(default_factory=list)


class ScanSummary(BaseModel):
    """Scan summary used in list responses."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID
    target_id: uuid.UUID
    contract_address: str | None = None
    chain_id: int | None = None
    labels: list[str] = Field(default_factory=list)
    finding_counts: dict[str, int] = Field(default_factory=dict)
    total_findings: int = 0
    status: ScanStatus
    fork: str
    fork_source: str = "requested"
    fork_conflict: bool = False
    bytecode_source: str
    queued_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    parser_version: str | None = None
    ruleset_version: str | None = None
    model_version: str | None = None
    source_audited: bool = False
    source_audit_skipped: str | None = None
    mythril_ran: bool = False
    mythril_skipped: str | None = None
    error_code: str | None = None
    error_message_redacted: str | None = None
    limitations: dict[str, Any] | None = None
    coverage: dict[str, Any] | None = None
    model_scores: dict[str, Any] | None = None
    created_at: datetime


class CorrespondenceProofRead(BaseModel):
    """The stored source-to-bytecode correspondence proof for a scan.

    A proof is the only thing that licenses the product to print an exact
    source path and line against a finding. ``status`` keeps ``mismatch``
    (the source genuinely does not describe the deployed contract) separate
    from ``unavailable`` (the check could not be performed at all).
    """

    model_config = ConfigDict(from_attributes=True)

    scan_id: uuid.UUID
    status: CorrespondenceStatus
    skipped: str | None = None
    compiler_version: str | None = None
    source_path: str | None = None
    runtime_sha256: str | None = None
    executable_sha256: str | None = None
    metadata_sha256: str | None = None
    runtime_byte_size: int | None = None
    executable_byte_size: int | None = None
    instruction_count: int | None = None
    mapped_instruction_count: int | None = None
    created_at: datetime | None = None


class ScanDetail(ScanSummary):
    """Full scan detail including jobs, artifacts and findings."""

    jobs: list[ScanJobRead] = Field(default_factory=list)
    artifacts: list[ScanArtifactRead] = Field(default_factory=list)
    findings: list[FindingRead] = Field(default_factory=list)
    correspondence: CorrespondenceProofRead | None = None


class MythrilRunResponse(BaseModel):
    """202 response returned when an on-demand Mythril run is queued.

    The response says the work was *queued*. It says nothing about what
    Mythril will find, and it deliberately does not claim success: a Mythril
    run that later produces no verdict must never be presented as clean.
    """

    scan_id: uuid.UUID
    job_id: uuid.UUID | None = None
    status: str = "queued"
    queue_name: str
    message: str


class CorrespondenceRunResponse(BaseModel):
    """202 response returned when a correspondence proof is queued.

    The response says the work was *queued*. It does not say a source line
    may be claimed: only a proof with the ``established`` status licenses
    that, and until it exists nothing has been proven.
    """

    scan_id: uuid.UUID
    job_id: uuid.UUID | None = None
    status: str = "queued"
    queue_name: str
    message: str


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
    "CorrespondenceProofRead",
    "CorrespondenceRunResponse",
    "MythrilRunResponse",
    "ScanAcceptedResponse",
    "ScanArtifactRead",
    "ScanCreateRequest",
    "ScanDetail",
    "ScanJobRead",
    "ScanListResponse",
    "SourceFileRead",
    "ScanSourceRead",
    "ScanSummary",
]
