"""record how much of a contract the analysis reached

A scan's status says whether the analysis was *complete* or *partial*.
What it did not say is how much was analysed -- how many instructions
were decoded, how far the static view reached, and how many control
flow edges could not be followed because their destination is computed
at run time.

Those numbers used to be filed as a limitation, which was the wrong
place for them. A dynamic jump is a property of ordinary Solidity, not
a hole in the analysis: treating it as a limitation meant that nearly
every real contract came back "partial", and the word stopped carrying
information.

This revision adds ``scans.coverage``: a JSON document that records the
measurement for every scan -- complete ones included -- so that two
scans of the same contract can be compared and a reader can weigh the
findings against what was actually read.

Revision ID: b5d9f3a7c1e2
Revises: a4c6e8021d5e
Create Date: 2026-11-13

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b5d9f3a7c1e2"
down_revision: str | None = "a4c6e8021d5e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the coverage column to scans."""
    op.add_column(
        "scans",
        sa.Column(
            "coverage",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    """Remove the coverage column from scans."""
    op.drop_column("scans", "coverage")
