"""unify the discovery schema with the scan schema

Implements the seven decisions in ``docs/SCHEMA-RECONCILIATION.md``:

1. A discovery cycle is not a scan. ``discovery_runs`` and ``feed_cursors``
   are new tables rather than columns on ``scans``.
2. Source code moves out of a TEXT column into the artifact store.
   ``contract_targets.source_object_key`` points at it.
3. Slither, rule and ML outputs share one ``findings`` table, told apart
   by the new ``findings.source`` column.
4. The proxy-template allowlist becomes an auditable table instead of a
   helper function's constant.
5. Suppressed findings keep their suppression metadata.
6. Discovered contracts land in a designated discovery workspace, so they
   do not appear in every tenant's contract list.
7. Contracts are unique per (workspace, chain, address), which makes a
   re-discovery idempotent.

Revision ID: b1e7c4a9d206
Revises: 9f4c1a2b7e10
Create Date: 2026-10-28

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b1e7c4a9d206"
down_revision: str | None = "9f4c1a2b7e10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- 6. the discovery workspace ------------------------------------
    op.add_column(
        "workspaces",
        sa.Column("kind", sa.String(length=32), nullable=False, server_default="tenant"),
    )
    op.create_check_constraint(
        "kind", "workspaces", "kind IN ('tenant', 'discovery')"
    )

    # --- 3. one findings table, told apart by its source ----------------
    op.add_column(
        "findings",
        sa.Column("source", sa.String(length=16), nullable=False, server_default="rule"),
    )
    op.create_index("ix_findings_source", "findings", ["source"])
    op.create_check_constraint(
        "source", "findings", "source IN ('rule', 'slither', 'ml')"
    )

    # --- 1. a discovery cycle is not a scan ----------------------------
    op.create_table(
        "discovery_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="running"),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("chains_covered", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("chains_failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("contracts_found", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("contracts_new", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("contracts_updated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("errors", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_discovery_runs_workspace_created",
        "discovery_runs",
        ["workspace_id", "started_at"],
    )

    op.create_table(
        "feed_cursors",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "chain_id",
            sa.Uuid(),
            sa.ForeignKey("chains.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("last_address", sa.String(length=42), nullable=True),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("contracts_seen", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("chain_id", "workspace_id", name="uq_feed_cursor_scope"),
    )
    op.create_index("ix_feed_cursors_workspace_id", "feed_cursors", ["workspace_id"])
    op.create_index("ix_feed_cursors_chain_id", "feed_cursors", ["chain_id"])

    # --- 2. source becomes an artifact ---------------------------------
    op.add_column(
        "contract_targets", sa.Column("source_object_key", sa.String(length=512), nullable=True)
    )

    # --- the provenance of a discovered contract ------------------------
    op.add_column(
        "contract_targets",
        sa.Column(
            "discovery_run_id",
            sa.Uuid(),
            sa.ForeignKey("discovery_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "contract_targets", sa.Column("discovery_route", sa.String(length=32), nullable=True)
    )
    op.add_column(
        "contract_targets", sa.Column("verification_state", sa.String(length=16), nullable=True)
    )
    op.add_column(
        "contract_targets", sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index(
        "ix_contract_targets_discovery_run_id", "contract_targets", ["discovery_run_id"]
    )

    # --- 7. a contract is unique per (workspace, chain, address) --------
    op.create_unique_constraint(
        "uq_contract_target_scope",
        "contract_targets",
        ["workspace_id", "chain_id", "address"],
    )

    # --- 4. the proxy-template allowlist becomes a table ----------------
    op.create_table(
        "proxy_template_allowlist",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("pattern", sa.String(length=120), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "added_by",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("pattern", name="uq_proxy_template_pattern"),
    )


def downgrade() -> None:
    op.drop_table("proxy_template_allowlist")
    op.drop_constraint("uq_contract_target_scope", "contract_targets", type_="unique")
    op.drop_index("ix_contract_targets_discovery_run_id", table_name="contract_targets")
    op.drop_column("contract_targets", "verified_at")
    op.drop_column("contract_targets", "verification_state")
    op.drop_column("contract_targets", "discovery_route")
    op.drop_column("contract_targets", "discovery_run_id")
    op.drop_column("contract_targets", "source_object_key")
    op.drop_index("ix_feed_cursors_chain_id", table_name="feed_cursors")
    op.drop_index("ix_feed_cursors_workspace_id", table_name="feed_cursors")
    op.drop_table("feed_cursors")
    op.drop_index("ix_discovery_runs_workspace_created", table_name="discovery_runs")
    op.drop_table("discovery_runs")
    op.drop_constraint("source", "findings", type_="check")
    op.drop_index("ix_findings_source", table_name="findings")
    op.drop_column("findings", "source")
    op.drop_constraint("kind", "workspaces", type_="check")
    op.drop_column("workspaces", "kind")
