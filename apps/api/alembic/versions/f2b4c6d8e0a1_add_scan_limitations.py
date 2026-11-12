"""record what was incomplete about a partial scan

A scan whose status is ``partial`` is not a clean scan with fewer
findings. It is a scan whose coverage was incomplete: the disassembly
warned about something, or the control-flow graph could not be fully
resolved, or the source engine did not run.

Until now that lived only in the log line. The database recorded the
*status* but not the *reason*, so the API could show a user a scan
labelled "partial" and refuse to say what was missing. That is the
difference between an honest result and a shrug.

This revision adds ``scans.limitations``: a JSON document that records
exactly what the analysis could not cover. It is written for every scan
-- ``NULL`` when nothing was incomplete -- so that "partial" and
"complete" can be told apart by the data and not by the absence of an
error.

Revision ID: f2b4c6d8e0a1
Revises: d7a3b9c1e5f2
Create Date: 2026-11-13

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f2b4c6d8e0a1"
down_revision: str | None = "d7a3b9c1e5f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the limitations column to scans."""
    op.add_column(
        "scans",
        sa.Column(
            "limitations",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    """Remove the limitations column."""
    op.drop_column("scans", "limitations")
