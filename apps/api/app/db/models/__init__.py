"""ORM model registry.

Importing this module registers every model on ``Base.metadata`` so Alembic
autogenerate and ``create_all`` see the complete schema.
"""

from __future__ import annotations

from app.db.models.identity import (
    ApiKey,
    AuditEvent,
    Chain,
    ContractTarget,
    User,
    Workspace,
    WorkspaceMember,
)
from app.db.models.scans import (
    BasicBlock,
    CfgEdge,
    FeatureRecord,
    Finding,
    Instruction,
    Scan,
    ScanArtifact,
    ScanJob,
)

__all__ = [
    "ApiKey",
    "AuditEvent",
    "BasicBlock",
    "CfgEdge",
    "Chain",
    "ContractTarget",
    "FeatureRecord",
    "Finding",
    "Instruction",
    "Scan",
    "ScanArtifact",
    "ScanJob",
    "User",
    "Workspace",
    "WorkspaceMember",
]
