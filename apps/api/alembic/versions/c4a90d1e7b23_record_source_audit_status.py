"""record whether the source engine ran for a scan

The bytecode engine and the source engine are complementary: one sees the
deployed bytes, the other sees the verified source. A scan has to be able
to say which of them actually ran, and why the other one did not, so the
answer is stored on the scan rather than inferred.

Revision ID: c4a90d1e7b23
Revises: b1e7c4a9d206
Create Date: 2026-10-28

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c4a90d1e7b23"
down_revision: str | None = "b1e7c4a9d206"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "scans",
        sa.Column(
            "source_audited",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "scans",
        sa.Column("source_audit_skipped", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("scans", "source_audit_skipped")
    op.drop_column("scans", "source_audited")
