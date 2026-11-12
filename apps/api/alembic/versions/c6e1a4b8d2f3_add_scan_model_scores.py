"""record the model's per-category scores on the scan

A model that only ever runs in a notebook cannot be audited and cannot
be improved. This revision gives every scan a place to record what the
installed model said about the contract, next to the findings the
engines produced.

The scores are ranking aids. They are stored separately from the
findings so that a reader can see that the model ranked the findings
without ever having changed what they say.

Revision ID: c6e1a4b8d2f3
Revises: b5d9f3a7c1e2
Create Date: 2026-11-13

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c6e1a4b8d2f3"
down_revision: str | None = "b5d9f3a7c1e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the model_scores column to scans."""
    op.add_column(
        "scans",
        sa.Column(
            "model_scores",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    """Remove the model_scores column from scans."""
    op.drop_column("scans", "model_scores")
