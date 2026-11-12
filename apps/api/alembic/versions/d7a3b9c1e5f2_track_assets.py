"""follow the addresses a workspace cares about, over time

The product has two modes and both of them forget: an autonomous
discovery pass records that a contract exists, and a developer scans
their own contract once. Neither keeps the *history* of an address, so
"did my fix work?" cannot be answered from the database -- the findings
of last week's scan are unreachable from the address they belong to.

This revision adds the spine both modes write into:

* ``tracked_assets`` -- one row per (workspace, chain, address) that a
  workspace follows, whether it owns the contract, watches it, or found
  it by discovery. The row records when the address was first seen.
* ``scans.asset_id`` -- the link from a scan to the asset it belongs to.
  It is ``ON DELETE SET NULL`` on purpose: stopping the tracking of an
  address must not delete the evidence of the scans already taken.

The progress counters are not stored. They are computed from the scans
and findings that exist, because a cached counter can disagree with the
rows it claims to count.

Revision ID: d7a3b9c1e5f2
Revises: c4e6a8b0d392
Create Date: 2026-11-12

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d7a3b9c1e5f2"
down_revision: str | None = "c4e6a8b0d392"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ASSET_KINDS = ("owned", "watched", "discovered")


def upgrade() -> None:
    """Create the asset registry and link scans to it."""
    op.create_table(
        "tracked_assets",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "chain_id",
            sa.Uuid(),
            sa.ForeignKey("chains.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("address", sa.String(length=42), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(*_ASSET_KINDS, name="asset_kind", native_enum=False),
            nullable=False,
            server_default="owned",
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "active", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "workspace_id", "chain_id", "address", name="uq_tracked_asset_scope"
        ),
    )
    op.create_index("ix_tracked_assets_workspace_id", "tracked_assets", ["workspace_id"])
    op.create_index("ix_tracked_assets_chain_id", "tracked_assets", ["chain_id"])
    op.create_index(
        "ix_tracked_asset_workspace_kind",
        "tracked_assets",
        ["workspace_id", "kind"],
    )

    op.add_column(
        "scans",
        sa.Column(
            "asset_id",
            sa.Uuid(),
            sa.ForeignKey("tracked_assets.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_scans_asset_id", "scans", ["asset_id"])


def downgrade() -> None:
    """Remove the asset registry and the link to it."""
    op.drop_index("ix_scans_asset_id", table_name="scans")
    op.drop_column("scans", "asset_id")
    op.drop_index("ix_tracked_asset_workspace_kind", table_name="tracked_assets")
    op.drop_index("ix_tracked_assets_chain_id", table_name="tracked_assets")
    op.drop_index("ix_tracked_assets_workspace_id", table_name="tracked_assets")
    op.drop_table("tracked_assets")
