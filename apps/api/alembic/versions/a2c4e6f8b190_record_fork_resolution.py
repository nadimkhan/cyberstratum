"""record how the analysis fork was resolved

The ``scans.fork`` column held a hard-coded ``cancun`` for every scan.
That is the right answer for some chains and the wrong one for many
others: a chain that predates Shanghai has no ``PUSH0``, zkSync is not
an EVM at all, and most of the chains a discovery feed finds are
neither Ethereum mainnet nor a Cancun L2. A wrong fork does not fail
loudly -- it reports real opcodes as invalid, or misses opcodes the
chain does have.

Two columns are added so that the record says how the fork was chosen:

* ``fork_source`` -- ``requested`` (the caller named a fork and the
  bytecode agreed), ``inferred`` (the fork was derived from the opcodes
  the bytecode uses), or ``fallback`` (the code could not be placed at
  all).
* ``fork_conflict`` -- the caller's request and the bytecode disagreed,
  or the code could not be placed. A conflict is not a failure: the
  scan still runs, but the result cannot be read as a clean analysis.

The default of ``scans.fork`` becomes the empty string, which means
"not resolved yet". The pipeline resolves it before disassembly, so a
queued scan has no fork yet and says so instead of pretending to be
Cancun.

Revision ID: a2c4e6f8b190
Revises: f7d9a3c1e5b2
Create Date: 2026-11-12

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a2c4e6f8b190"
down_revision: str | None = "f7d9a3c1e5b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Record the fork source and whether the request conflicted."""
    op.alter_column(
        "scans",
        "fork",
        existing_type=sa.String(length=32),
        nullable=False,
        server_default="",
    )
    op.add_column(
        "scans",
        sa.Column(
            "fork_source",
            sa.String(length=16),
            nullable=False,
            server_default="requested",
        ),
    )
    op.add_column(
        "scans",
        sa.Column(
            "fork_conflict",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    """Remove the fork-resolution record and restore the default."""
    op.drop_column("scans", "fork_conflict")
    op.drop_column("scans", "fork_source")
    op.alter_column(
        "scans",
        "fork",
        existing_type=sa.String(length=32),
        nullable=False,
        server_default="cancun",
    )
