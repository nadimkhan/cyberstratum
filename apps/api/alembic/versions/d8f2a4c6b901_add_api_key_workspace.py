"""bind every API key to the workspace it acts in

An API key is a machine client. A machine client belongs to one
tenant: a key that could act in whichever workspace its owner happens
to belong to first is a key that can read another tenant's data by
accident, and an API key whose owner is in several workspaces has no
way to say which one it meant.

This revision adds ``api_keys.workspace_id`` and binds every existing
key to the workspace of its owner's earliest membership -- the only
workspace such a key could have been used in before this column
existed, because that is how it was resolved.

Revision ID: d8f2a4c6b901
Revises: c6e1a4b8d2f3
Create Date: 2026-11-13

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d8f2a4c6b901"
down_revision: str | None = "c6e1a4b8d2f3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the workspace column and bind every key to one workspace."""
    op.add_column(
        "api_keys",
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.create_index("ix_api_keys_workspace_id", "api_keys", ["workspace_id"])

    # Backfill: a key takes the workspace of its owner's earliest
    # membership, which is the workspace the key was already resolving
    # to. A key whose owner is in no workspace keeps none, and stays as
    # unable to reach any tenant.
    op.execute(
        """
        UPDATE api_keys AS k
        SET workspace_id = m.workspace_id
        FROM (
            SELECT DISTINCT ON (user_id) user_id, workspace_id
            FROM workspace_members
            ORDER BY user_id, created_at, id
        ) AS m
        WHERE k.user_id = m.user_id
          AND k.workspace_id IS NULL
        """
    )


def downgrade() -> None:
    """Remove the workspace column."""
    op.drop_index("ix_api_keys_workspace_id", table_name="api_keys")
    op.drop_column("api_keys", "workspace_id")
