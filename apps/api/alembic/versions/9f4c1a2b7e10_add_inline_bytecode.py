"""allow user-supplied bytecode on a contract target

Design doc section 6.1 lists "bytecode uploaded by the user" as a first-class
input, and section 18.1 makes it an acceptance criterion ("a user can create
a target from pasted or uploaded bytecode"). The column holds the bytes
directly, so a scan of an uploaded target never contacts an RPC.

Revision ID: 9f4c1a2b7e10
Revises: 6d0038e2fcb8
Create Date: 2026-10-28

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9f4c1a2b7e10"
down_revision: str | None = "6d0038e2fcb8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "contract_targets",
        sa.Column("inline_bytecode", sa.LargeBinary(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("contract_targets", "inline_bytecode")
