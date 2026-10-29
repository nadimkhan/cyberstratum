"""Scan, scan job, artifact and analysis-result models.

These mirror design doc section 9.1: ``scans``, ``scan_jobs``,
``instructions``, ``basic_blocks``, ``cfg_edges``, ``features`` and
``findings``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, created_at_column, enum_column, updated_at_column, uuid_pk
from app.db.enums import (
    CorrespondenceStatus,
    FindingStatus,
    ScanJobStatus,
    ScanJobType,
    ScanStatus,
    Severity,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.db.models.identity import ContractTarget


class Scan(Base):
    """A single analysis run over a contract target."""

    __tablename__ = "scans"
    __table_args__ = (Index("ix_scans_workspace_created", "workspace_id", "created_at"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    target_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("contract_targets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[ScanStatus] = mapped_column(
        enum_column(ScanStatus, "scan_status"),
        nullable=False,
        default=ScanStatus.QUEUED,
        index=True,
    )
    requested_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    fork: Mapped[str] = mapped_column(String(32), nullable=False, default="cancun")
    bytecode_source: Mapped[str] = mapped_column(String(64), nullable=False, default="rpc")
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    parser_version: Mapped[str | None] = mapped_column(String(64))
    ruleset_version: Mapped[str | None] = mapped_column(String(64))
    model_version: Mapped[str | None] = mapped_column(String(64))
    source_audited: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        doc="Whether the source engine actually ran for this scan.",
    )
    source_audit_skipped: Mapped[str | None] = mapped_column(
        String(64),
        doc=(
            "Why the source engine did not run, when it did not: "
            "'no_source', 'slither_not_installed', 'solc_not_found', "
            "'compilation_failed', and so on."
        ),
    )
    mythril_ran: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        doc="Whether the Mythril engine actually ran for this scan.",
    )
    mythril_skipped: Mapped[str | None] = mapped_column(
        String(64),
        doc=(
            "Why Mythril did not run, when it did not: "
            "'mythril_not_installed', 'creation_bytecode_supplied', "
            "'no_runtime_bytecode', 'no_verdict', 'timeout', and so on. "
            "A Mythril run that produced no verdict is recorded here and is "
            "never treated as a clean result."
        ),
    )
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message_redacted: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    target: Mapped[ContractTarget] = relationship(back_populates="scans")
    jobs: Mapped[list[ScanJob]] = relationship(back_populates="scan", cascade="all, delete-orphan")
    findings: Mapped[list[Finding]] = relationship(
        back_populates="scan", cascade="all, delete-orphan"
    )
    artifacts: Mapped[list[ScanArtifact]] = relationship(
        back_populates="scan", cascade="all, delete-orphan"
    )
    correspondence_proofs: Mapped[list[CorrespondenceProof]] = relationship(
        back_populates="scan", cascade="all, delete-orphan"
    )

    @property
    def contract_address(self) -> str | None:
        """The address of the analysed target.

        Derived rather than stored: the address belongs to the target, and
        duplicating it on every scan row would let the two drift apart.
        """
        target: ContractTarget | None = self.target
        return target.address if target is not None else None

    @property
    def chain_id(self) -> int | None:
        """The chain the target lives on."""
        target: ContractTarget | None = self.target
        if target is None:
            return None
        return target.chain.chain_id

    @property
    def labels(self) -> list[str]:
        """The labels of the analysed target."""
        target: ContractTarget | None = self.target
        if target is None or not target.label:
            return []
        return [target.label]


class ScanJob(Base):
    """A queue job backing a scan (design doc table ``scan_jobs``)."""

    __tablename__ = "scan_jobs"
    __table_args__ = (Index("ix_scan_jobs_scan_status", "scan_id", "status"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    scan_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("scans.id", ondelete="CASCADE"), nullable=False, index=True
    )
    job_type: Mapped[ScanJobType] = mapped_column(
        enum_column(ScanJobType, "scan_job_type"),
        nullable=False,
        default=ScanJobType.SCAN,
    )
    queue_name: Mapped[str] = mapped_column(String(64), nullable=False, default="cyberstratum")
    rq_job_id: Mapped[str | None] = mapped_column(String(64), index=True)
    status: Mapped[ScanJobStatus] = mapped_column(
        enum_column(ScanJobStatus, "scan_job_status"),
        nullable=False,
        default=ScanJobStatus.QUEUED,
        index=True,
    )
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    resource_usage: Mapped[dict[str, object] | None] = mapped_column(JSONB)

    scan: Mapped[Scan] = relationship(back_populates="jobs")


class ScanArtifact(Base):
    """A stored artifact produced by a scan (bytecode, disassembly, features).

    The design doc references artifacts by ``*_object_key`` on the owning
    rows; this table is the single index of artifacts for a scan.
    """

    __tablename__ = "scan_artifacts"

    id: Mapped[uuid.UUID] = uuid_pk()
    scan_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("scans.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(48), nullable=False)
    content_type: Mapped[str] = mapped_column(
        String(64), nullable=False, default="application/json"
    )
    object_key: Mapped[str] = mapped_column(String(512), nullable=False)
    byte_size: Mapped[int | None] = mapped_column(Integer)
    sha256: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = created_at_column()

    scan: Mapped[Scan] = relationship(back_populates="artifacts")


class Instruction(Base):
    """A decoded instruction belonging to a scan."""

    __tablename__ = "instructions"
    __table_args__ = (Index("ix_instructions_scan_offset", "scan_id", "byte_offset"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    scan_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("scans.id", ondelete="CASCADE"), nullable=False
    )
    byte_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    opcode_byte: Mapped[int] = mapped_column(Integer, nullable=False)
    opcode_name: Mapped[str] = mapped_column(String(32), nullable=False)
    immediate_hex: Mapped[str | None] = mapped_column(String(80))
    instruction_size: Mapped[int] = mapped_column(Integer, nullable=False)
    block_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("basic_blocks.id", ondelete="SET NULL"), nullable=True
    )
    stack_in: Mapped[int | None] = mapped_column(Integer)
    stack_out: Mapped[int | None] = mapped_column(Integer)


class BasicBlock(Base):
    """A basic block belonging to a scan."""

    __tablename__ = "basic_blocks"
    __table_args__ = (Index("ix_basic_blocks_scan_start", "scan_id", "start_offset"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    scan_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("scans.id", ondelete="CASCADE"), nullable=False
    )
    start_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    end_offset: Mapped[int] = mapped_column(Integer, nullable=False)
    terminator_opcode: Mapped[str | None] = mapped_column(String(32))
    is_entry: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_exit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    metadata_json: Mapped[dict[str, object] | None] = mapped_column(JSONB)


class CfgEdge(Base):
    """A control-flow edge belonging to a scan."""

    __tablename__ = "cfg_edges"
    __table_args__ = (Index("ix_cfg_edges_scan", "scan_id"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    scan_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("scans.id", ondelete="CASCADE"), nullable=False
    )
    from_block_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("basic_blocks.id", ondelete="CASCADE"), nullable=False
    )
    to_block_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("basic_blocks.id", ondelete="SET NULL"), nullable=True
    )
    edge_type: Mapped[str] = mapped_column(String(32), nullable=False)
    resolution: Mapped[str] = mapped_column(String(16), nullable=False, default="unresolved")
    evidence_json: Mapped[dict[str, object] | None] = mapped_column(JSONB)


class FeatureRecord(Base):
    """A versioned feature record produced by the feature service."""

    __tablename__ = "features"

    id: Mapped[uuid.UUID] = uuid_pk()
    scan_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("scans.id", ondelete="CASCADE"), nullable=False, index=True
    )
    feature_schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    feature_type: Mapped[str] = mapped_column(String(64), nullable=False)
    feature_object_key: Mapped[str | None] = mapped_column(String(512))
    feature_json: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = created_at_column()


class Finding(Base):
    """A detector finding attached to a scan (design doc table ``findings``)."""

    __tablename__ = "findings"
    __table_args__ = (
        Index("ix_findings_scan_severity", "scan_id", "severity"),
        Index("ix_findings_workspace_created", "workspace_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    scan_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("scans.id", ondelete="CASCADE"), nullable=False, index=True
    )
    detector_id: Mapped[str] = mapped_column(String(64), nullable=False)
    detector_version: Mapped[str] = mapped_column(String(32), nullable=False)
    source: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="rule",
        index=True,
        doc=(
            "Which engine produced this finding: 'rule' for the bytecode "
            "rules, 'slither' for the source engine, 'ml' for the model, "
            "'mythril' for the on-demand symbolic-execution engine."
        ),
    )
    category: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    severity: Mapped[Severity] = mapped_column(
        enum_column(Severity, "finding_severity"),
        nullable=False,
        default=Severity.MEDIUM,
        index=True,
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    status: Mapped[FindingStatus] = mapped_column(
        enum_column(FindingStatus, "finding_status"),
        nullable=False,
        default=FindingStatus.NEW,
        index=True,
    )
    evidence_json: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    limitations: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    scan: Mapped[Scan] = relationship(back_populates="findings")


class CorrespondenceProof(Base):
    """A stored source-to-bytecode correspondence proof for one scan.

    A proof is the *only* thing that licenses the product to print an exact
    source path and line against a finding. Without one, a finding is
    bytecode-only and the report must say so.

    The ``status`` column deliberately separates ``MISMATCH`` from
    ``UNAVAILABLE``. A mismatch means the published source genuinely does not
    describe the deployed contract. ``UNAVAILABLE`` means the check could not
    be performed at all - the compiler hung, crashed, was missing, or emitted
    something that was not JSON. Reporting a tooling failure as a
    correspondence failure would be a false accusation against a contract.
    """

    __tablename__ = "correspondence_proofs"

    id: Mapped[uuid.UUID] = uuid_pk()
    scan_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("scans.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[CorrespondenceStatus] = mapped_column(
        enum_column(CorrespondenceStatus, "correspondence_status"),
        nullable=False,
        default=CorrespondenceStatus.SKIPPED,
        index=True,
    )
    skipped: Mapped[str | None] = mapped_column(
        String(64),
        doc="Why the check did not run, when it did not.",
    )
    compiler_version: Mapped[str | None] = mapped_column(String(64))
    source_path: Mapped[str | None] = mapped_column(String(512))
    runtime_sha256: Mapped[str | None] = mapped_column(String(64))
    executable_sha256: Mapped[str | None] = mapped_column(String(64))
    metadata_sha256: Mapped[str | None] = mapped_column(String(64))
    runtime_byte_size: Mapped[int | None] = mapped_column(Integer)
    executable_byte_size: Mapped[int | None] = mapped_column(Integer)
    instruction_count: Mapped[int | None] = mapped_column(Integer)
    mapped_instruction_count: Mapped[int | None] = mapped_column(Integer)
    proof_json: Mapped[dict[str, object] | None] = mapped_column(
        JSONB,
        doc="The full proof payload, including the PC-to-line instruction map.",
    )
    created_at: Mapped[datetime] = created_at_column()

    scan: Mapped[Scan] = relationship(back_populates="correspondence_proofs")


__all__ = [
    "BasicBlock",
    "CfgEdge",
    "CorrespondenceProof",
    "FeatureRecord",
    "Finding",
    "Instruction",
    "Scan",
    "ScanArtifact",
    "ScanJob",
]
