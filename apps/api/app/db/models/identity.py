"""Identity models: users, API keys, workspaces, chains, targets and audit events."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, created_at_column, enum_column, uuid_pk
from app.db.enums import UserStatus, WorkspaceRole

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.db.models.scans import Scan


class User(Base):
    """A platform user (design doc table ``users``)."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = uuid_pk()
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    display_name: Mapped[str | None] = mapped_column(String(200))
    auth_provider_id: Mapped[str | None] = mapped_column(String(255), unique=True)
    password_hash: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[UserStatus] = mapped_column(
        enum_column(UserStatus, "user_status"),
        nullable=False,
        default=UserStatus.ACTIVE,
    )
    created_at: Mapped[datetime] = created_at_column()
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    memberships: Mapped[list[WorkspaceMember]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    api_keys: Mapped[list[ApiKey]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class ApiKey(Base):
    """A hashed API key that authenticates API clients.

    The plaintext key is only ever shown at creation time; the stored value is
    a SHA-256 digest so a database leak does not yield usable credentials.
    """

    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    key_prefix: Mapped[str] = mapped_column(String(12), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = created_at_column()
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User | None] = relationship(back_populates="api_keys")


class Workspace(Base):
    """A tenant workspace (design doc table ``workspaces``)."""

    __tablename__ = "workspaces"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = created_at_column()

    members: Mapped[list[WorkspaceMember]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan"
    )


class WorkspaceMember(Base):
    """Membership of a user inside a workspace (design doc ``workspace_members``)."""

    __tablename__ = "workspace_members"
    __table_args__ = (UniqueConstraint("workspace_id", "user_id", name="uq_ws_members_pair"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[WorkspaceRole] = mapped_column(
        enum_column(WorkspaceRole, "workspace_role"),
        nullable=False,
        default=WorkspaceRole.RESEARCHER,
    )
    created_at: Mapped[datetime] = created_at_column()

    workspace: Mapped[Workspace] = relationship(back_populates="members")
    user: Mapped[User] = relationship(back_populates="memberships")


class Chain(Base):
    """A supported chain (design doc table ``chains``)."""

    __tablename__ = "chains"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    chain_id: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    environment: Mapped[str] = mapped_column(String(32), nullable=False, default="mainnet")
    rpc_config_ref: Mapped[str | None] = mapped_column(String(255))
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    description: Mapped[str | None] = mapped_column(Text)

    targets: Mapped[list[ContractTarget]] = relationship(back_populates="chain")


class ContractTarget(Base):
    """A contract to be analysed (design doc table ``contract_targets``)."""

    __tablename__ = "contract_targets"

    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chain_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("chains.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    address: Mapped[str | None] = mapped_column(String(42), index=True)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    bytecode_type: Mapped[str] = mapped_column(String(16), nullable=False, default="runtime")
    bytecode_hash: Mapped[str | None] = mapped_column(String(64))
    inline_bytecode: Mapped[bytes | None] = mapped_column(
        LargeBinary,
        nullable=True,
        doc=(
            "Bytecode supplied directly by the user (pasted or uploaded), as "
            "design doc section 6.1 allows. When set, the scanner analyses "
            "these bytes and never contacts an RPC."
        ),
    )
    bytecode_object_key: Mapped[str | None] = mapped_column(String(512))
    source_uri: Mapped[str | None] = mapped_column(String(512))
    abi_object_key: Mapped[str | None] = mapped_column(String(512))
    provenance: Mapped[str | None] = mapped_column(Text)
    authorization_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="unknown"
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = created_at_column()

    chain: Mapped[Chain] = relationship(back_populates="targets")
    scans: Mapped[list[Scan]] = relationship(
        back_populates="target", cascade="all, delete-orphan"
    )


class AuditEvent(Base):
    """Append-only audit trail (design doc table ``audit_events``)."""

    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_events_workspace_created", "workspace_id", "created_at"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True, index=True
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(120), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(80), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(64))
    ip_hash: Mapped[str | None] = mapped_column(String(64))
    metadata_redacted: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = created_at_column()


__all__ = [
    "ApiKey",
    "AuditEvent",
    "Chain",
    "ContractTarget",
    "User",
    "Workspace",
    "WorkspaceMember",
]
