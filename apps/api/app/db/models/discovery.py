"""Discovery models: feed cursors, discovery runs, and the proxy allowlist.

These are the tables the schema reconciliation called for
(``docs/SCHEMA-RECONCILIATION.md``). A *discovery cycle* is not a scan: a
scan analyses one contract, a discovery cycle sweeps many chains looking for
contracts worth analysing. Keeping them apart means a discovery run has
its own lifecycle, its own error handling, and its own cursor.
"""

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
    String,
    Text,
    UniqueConstraint,
    func,
    text,
    true,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, created_at_column, updated_at_column, uuid_pk

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.db.models.identity import Chain, ContractTarget, User, Workspace


class FeedCursor(Base):
    """How far a discovery feed has read on one chain.

    The cursor advances and is persisted *before* analysis starts. That
    ordering matters: a crash or a timeout mid-analysis then costs at most
    one contract, rather than causing the same contract to be fetched and
    re-analysed on every cycle.

    Attributes:
        chain_id: The chain this cursor belongs to.
        workspace_id: The workspace the cursor is scoped to.
        last_address: The last address seen on this chain.
        last_verified_at: The newest verification timestamp seen.
        updated_at: When the cursor last moved.
    """

    __tablename__ = "feed_cursors"
    __table_args__ = (
        UniqueConstraint("chain_id", "workspace_id", name="uq_feed_cursor_scope"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    chain_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("chains.id", ondelete="CASCADE"), nullable=False, index=True
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    last_address: Mapped[str | None] = mapped_column(String(42))
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    contracts_seen: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    updated_at: Mapped[datetime] = updated_at_column()

    chain: Mapped[Chain] = relationship()
    workspace: Mapped[Workspace] = relationship()


class DiscoveryRun(Base):
    """One sweep across a set of chains.

    Attributes:
        workspace_id: The discovery workspace the contracts landed in.
        status: ``running``, ``completed``, ``partial`` or ``failed``.
        chains_covered: How many chains the sweep reached.
        contracts_found: How many contracts the routes returned.
        contracts_new: How many were new since the last sweep.
        contracts_updated: How many were re-verified and so need a re-scan.
        errors: The per-chain failures, as JSON.
    """

    __tablename__ = "discovery_runs"
    __table_args__ = (
        # Named as the migration created it: the same (workspace_id,
        # started_at) coverage under a different name would be a lie the
        # schema-diff test rightly refuses.
        Index("ix_discovery_runs_workspace_created", "workspace_id", "started_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="running", server_default="running"
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    chains_covered: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    chains_failed: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    contracts_found: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    contracts_new: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    contracts_updated: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    scans_queued: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    errors: Mapped[list[dict[str, object]] | None] = mapped_column(JSONB)
    notes: Mapped[str | None] = mapped_column(Text)

    workspace: Mapped[Workspace] = relationship()
    targets: Mapped[list[ContractTarget]] = relationship(back_populates="discovery_run")


class ProxyTemplateAllowlist(Base):
    """Patterns whose contracts are known proxy templates.

    Watchdog kept this as a hard-coded set in a helper function, which made
    it impossible to review who added a pattern or why. The schema
    reconciliation replaces it with a table so every entry is auditable.

    Attributes:
        pattern: The lower-cased substring that identifies the template.
        reason: Why the pattern is on the list.
        added_by: The user who added it, when there is one.
        active: Whether the pattern is still in force.
    """

    __tablename__ = "proxy_template_allowlist"
    __table_args__ = (
        UniqueConstraint("pattern", name="uq_proxy_template_pattern"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    pattern: Mapped[str] = mapped_column(String(120), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    added_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )
    created_at: Mapped[datetime] = created_at_column()

    added_by_user: Mapped[User] = relationship()


__all__ = [
    "DiscoveryRun",
    "FeedCursor",
    "ProxyTemplateAllowlist",
]
