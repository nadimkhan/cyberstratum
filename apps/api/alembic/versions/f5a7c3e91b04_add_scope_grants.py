"""record the authorised scope of every scan

A scanner that cannot say *why* it was allowed to look at a contract is
not usable in a bug-bounty programme, and a report whose subject was
out of scope must not be mistaken for a report about something the
workspace was welcome to examine.

Two things are added:

* ``scope_grants`` -- what a workspace has declared to be in bounds.
  A grant names a programme, a contract address or a chain, says
  whether the safe-harbour rules were read, and may expire.
* ``scans.scope_status`` -- what the authorisation was *at the time
  the scan was queued*. It is recorded on the scan rather than
  computed on demand, because the declaration can change afterwards
  and a report must keep the authorisation it was produced under.

Revision ID: f5a7c3e91b04
Revises: e1f3b5d7a902
Create Date: 2026-11-13

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f5a7c3e91b04"
down_revision: str | None = "e1f3b5d7a902"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the scope registry and the recorded authorisation."""
    op.create_table(
        "scope_grants",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=16), server_default="contract", nullable=False),
        sa.Column("value", sa.String(length=200), nullable=False),
        sa.Column("chain_id", sa.Integer(), nullable=True),
        sa.Column("safe_harbour", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("reference", sa.String(length=500), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('programme', 'contract', 'chain')",
            name="ck_scope_grants_kind",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_scope_grants_workspace_id_workspaces",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_scope_grants"),
    )
    op.create_index("ix_scope_grants_workspace_id", "scope_grants", ["workspace_id"], unique=False)
    op.create_index("ix_scope_grants_chain_id", "scope_grants", ["chain_id"], unique=False)
    op.add_column(
        "scans",
        sa.Column(
            "scope_status",
            sa.String(length=16),
            server_default="unknown",
            nullable=False,
        ),
    )
    op.create_index("ix_scans_scope_status", "scans", ["scope_status"], unique=False)


def downgrade() -> None:
    """Remove the scope registry."""
    op.drop_index("ix_scans_scope_status", table_name="scans")
    op.drop_column("scans", "scope_status")
    op.drop_index("ix_scope_grants_chain_id", table_name="scope_grants")
    op.drop_index("ix_scope_grants_workspace_id", table_name="scope_grants")
    op.drop_table("scope_grants")
