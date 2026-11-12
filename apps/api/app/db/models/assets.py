"""Tracked-asset models.

A tracked asset is an address a workspace keeps an eye on: the user's own
deployment, a contract they are about to ship, a competitor's contract, or
a contract discovered on a public network. Every scan of that address is
attached to the asset, so the workspace can see the dated history of a
contract and how its findings changed over time.

This is the spine that both product modes write into:

* autonomous discovery creates ``discovered`` assets,
* a developer scanning their own contract creates an ``owned`` asset,
* both then accumulate a timeline of scans and findings against one row.

Without it, a scan is a one-off event with no memory, and "keep track of
progress" is not answerable from the database.

The progress counters are deliberately *not* stored here. A cached counter
can disagree with the findings it claims to count, and the one number a
user watches to decide whether their fix worked must never be stale. The
progress is computed from the scans and findings that actually exist.
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
    String,
    Text,
    UniqueConstraint,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, created_at_column, enum_column, updated_at_column, uuid_pk
from app.db.enums import AssetKind

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.db.models.scans import Scan


class TrackedAsset(Base):
    """An address a workspace tracks, with the progress counters over time."""

    __tablename__ = "tracked_assets"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "chain_id",
            "address",
            name="uq_tracked_asset_scope",
        ),
        Index("ix_tracked_asset_workspace_kind", "workspace_id", "kind"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chain_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("chains.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    address: Mapped[str] = mapped_column(String(42), nullable=False)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(
        enum_column(AssetKind, "asset_kind"),
        nullable=False,
        default=AssetKind.OWNED,
        server_default=AssetKind.OWNED.value,
        doc=(
            "Why this address is tracked: 'owned' for the workspace's own "
            "deployments, 'watched' for an address the team follows, "
            "'discovered' for a contract found by autonomous discovery."
        ),
    )
    notes: Mapped[str | None] = mapped_column(Text)

    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        doc="When the workspace first recorded this address.",
    )
    active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=true(),
        doc="False when tracking stops; the history is kept either way.",
    )

    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    scans: Mapped[list[Scan]] = relationship(back_populates="asset")
