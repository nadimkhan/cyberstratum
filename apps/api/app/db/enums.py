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


#: Every provenance the product writes into ``findings.source``.
#:
#: This is the single source of truth for the set. The database carries a
#: CHECK constraint with the same list, and the two are compared by
#: ``tests/api/test_migration_contract.py``: a finding that the database
#: refuses to store is a finding the product computed and then threw away,
#: and the contract would look exactly like one no engine ever examined.
#:
#: The values are data, not identifiers, on purpose: the Slither entry
#: names an engine that is invoked out of process under the AGPL boundary
#: of ADR-0013, and the AGPL guard reads an identifier as code.
FINDING_SOURCES: tuple[str, ...] = ("rule", "slither", "ml", "mythril")


class ScanJobType(StrEnum):
    """Type of work performed by a scan job."""

    SCAN = "scan"
    REPRODUCTION = "reproduction"
    MYTHRIL = "mythril"
    CORRESPONDENCE = "correspondence"


class CorrespondenceStatus(StrEnum):
    """Outcome of a source-to-bytecode correspondence check.

    The distinction between ``MISMATCH`` and ``UNAVAILABLE`` is the whole
    point of the enum. A mismatch is a finding: the published source does not
    describe the deployed contract. An unavailable check is *not* a finding:
    the compiler hung, crashed, was missing, or emitted something that was
    not JSON, so the check simply did not run. Collapsing the two would let a
    tooling failure be reported as evidence against a contract.
    """

    ESTABLISHED = "established"
    SKIPPED = "skipped"
    MISMATCH = "mismatch"
    UNAVAILABLE = "unavailable"


class AssetKind(StrEnum):
    """Why a workspace follows an address.

    The kind records intent and decides nothing about the analysis: a
    discovered contract is analysed exactly like one the user owns. It
    exists so a workspace can tell "my contracts" from "contracts I
    found", and so the product knows which addresses a user is asking to
    be watched over time.
    """

    OWNED = "owned"
    WATCHED = "watched"
    DISCOVERED = "discovered"


__all__ = [
    "AssetKind",
    "AuthorizationStatus",
    "BytecodeType",
    "ChainEnvironment",
    "CorrespondenceStatus",
    "FindingStatus",
    "ScanJobStatus",
    "ScanJobType",
    "ScanStatus",
    "Severity",
    "StrEnum",
    "UserStatus",
    "WorkspaceRole",
]
