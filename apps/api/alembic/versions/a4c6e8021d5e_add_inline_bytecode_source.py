"""record how a target's inline bytecode was obtained

``contract_targets.inline_bytecode`` holds bytes that did not come from
the chain: either a developer pasted the runtime bytecode, or a
developer pasted Solidity and the server compiled it. Both end up as
the same column, but they are not the same thing.

The difference matters for the reader of a scan. "Upload" means the
bytes were taken at the developer's word. "Compiled" means the server
compiled the developer's source with a named compiler and analysed
what came out -- which is a stronger claim, because the source map that
came with the compilation is what lets a finding point at a line.

This revision adds ``contract_targets.inline_bytecode_source`` so the
scan records which of the two it was, instead of leaving it to be
guessed from the presence of a source file.

Revision ID: a4c6e8021d5e
Revises: f2b4c6d8e0a1
Create Date: 2026-11-13

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a4c6e8021d5e"
down_revision: str | None = "f2b4c6d8e0a1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the inline bytecode source column to contract targets."""
    op.add_column(
        "contract_targets",
        sa.Column("inline_bytecode_source", sa.String(32), nullable=True),
    )


def downgrade() -> None:
    """Remove the inline bytecode source column."""
    op.drop_column("contract_targets", "inline_bytecode_source")
