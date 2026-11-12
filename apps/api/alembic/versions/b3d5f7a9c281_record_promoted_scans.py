"""record how many scans the discovery feed queued

The feed now promotes the contracts it finds into scans. A run that
reports how many contracts it found, and nothing about what happened to
them, hides the most important number: how much work the cycle actually
created.

``discovery_runs.scans_queued`` records that count. It is a counter
rather than a JSON blob because the only question anyone asks of it is
"how many", and a number answers it without a parser.

Revision ID: b3d5f7a9c281
Revises: a2c4e6f8b190
Create Date: 2026-11-12

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b3d5f7a9c281"
down_revision: str | None = "a2c4e6f8b190"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Count the scans a run queued."""
    op.add_column(
        "discovery_runs",
        sa.Column(
            "scans_queued",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )


def downgrade() -> None:
    """Remove the counter."""
    op.drop_column("discovery_runs", "scans_queued")
