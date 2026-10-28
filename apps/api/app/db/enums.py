"""Enumerations shared by the ORM models and the API schemas."""

from __future__ import annotations

from enum import StrEnum


class ScanStatus(StrEnum):
    """Lifecycle of a scan, mirroring the pipeline stages in the design doc.

    Section 5.1 of the design document requires a scan to end as *complete*,
    *partial*, or *failed* with a reason. The intermediate states mirror the
    pipeline stages: intake -> disassembly -> CFG -> features -> rules.
    """

    QUEUED = "queued"
    FETCHING_BYTECODE = "fetching_bytecode"
    DISASSEMBLING = "disassembling"
    BUILDING_CFG = "building_cfg"
    EXTRACTING_FEATURES = "extracting_features"
    RUNNING_DETECTORS = "running_detectors"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ScanJobStatus(StrEnum):
    """Lifecycle of an individual queue job backing a scan."""

    QUEUED = "queued"
    STARTED = "started"
    FINISHED = "finished"
    FAILED = "failed"


class FindingStatus(StrEnum):
    """Triage state of a finding (design doc section 5.2)."""

    NEW = "new"
    TRIAGE = "triage"
    CONFIRMED = "confirmed"
    FALSE_POSITIVE = "false_positive"
    NEEDS_MORE_EVIDENCE = "needs_more_evidence"


class Severity(StrEnum):
    """Finding severity, ordered from most to least urgent."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class ChainEnvironment(StrEnum):
    """Deployment environment of a chain."""

    MAINNET = "mainnet"
    TESTNET = "testnet"
    LOCAL = "local"


class BytecodeType(StrEnum):
    """Kind of bytecode held by a contract target."""

    RUNTIME = "runtime"
    INIT = "init"


class AuthorizationStatus(StrEnum):
    """Whether the operator is authorised to analyse a given target."""

    AUTHORIZED = "authorized"
    UNVERIFIED = "unverified"
    UNKNOWN = "unknown"


class UserStatus(StrEnum):
    """Account status of a user."""

    ACTIVE = "active"
    INVITED = "invited"
    SUSPENDED = "suspended"


class WorkspaceRole(StrEnum):
    """Role of a member inside a workspace (design doc section 3)."""

    OWNER = "owner"
    ADMIN = "admin"
    RESEARCHER = "researcher"
    REVIEWER = "reviewer"
    VIEWER = "viewer"


class ScanJobType(StrEnum):
    """Type of work performed by a scan job."""

    SCAN = "scan"
    REPRODUCTION = "reproduction"


__all__ = [
    "AuthorizationStatus",
    "BytecodeType",
    "ChainEnvironment",
    "FindingStatus",
    "ScanJobStatus",
    "ScanJobType",
    "ScanStatus",
    "Severity",
    "StrEnum",
    "UserStatus",
    "WorkspaceRole",
]
