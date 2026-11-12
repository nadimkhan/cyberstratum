"""read the history of the feed, not only its newest page

The discovery feed lists contracts newest first. Reading only page one
means the newest contracts are found over and over while everything
older is never seen at all -- the cycle keeps re-reading the same
fifty addresses.

This revision gives the per-chain cursor a page to continue from, so a
cycle can walk forward through the history of the chain and come back
to the newest page when it reaches the end, which is where the next
new contract will appear.

Revision ID: e1f3b5d7a902
Revises: d8f2a4c6b901
Create Date: 2026-11-13

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e1f3b5d7a902"
down_revision: str | None = "d8f2a4c6b901"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Record where in the feed each chain's walk has reached."""
    op.add_column(
        "feed_cursors",
        sa.Column("next_page", sa.Integer(), nullable=False, server_default="1"),
    )


def downgrade() -> None:
    """Remove the page the cursor continues from."""
    op.drop_column("feed_cursors", "next_page")
