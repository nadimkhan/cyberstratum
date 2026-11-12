"""record who reviewed a finding, when, and why

The labels this product trains on come from human review, and a review
that cannot be attributed teaches the model nothing: a false positive
without a reason is indistinguishable from a false positive that was
wrong, and neither is usable as ground truth.

Three columns are added to ``findings``:

* ``reviewed_by`` -- the user who made the call. It is a foreign key to
  ``users`` with ``ON DELETE SET NULL``, because deleting a user must
  not delete the record of a judgement they made.
* ``reviewed_at`` -- when the call was made.
* ``review_note`` -- why. The API requires it for a false-positive
  verdict, which is the verdict that becomes a negative label.

Revision ID: c4e6a8b0d392
Revises: b3d5f7a9c281
Create Date: 2026-11-12

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c4e6a8b0d392"
down_revision: str | None = "b3d5f7a9c281"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Attribute the review."""
    op.add_column(
        "findings",
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("findings", sa.Column("review_note", sa.Text(), nullable=True))
    op.add_column(
        "findings",
        sa.Column(
            "reviewed_by",
            sa.UUID(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_findings_reviewed_by", "findings", ["reviewed_by"], unique=False)


def downgrade() -> None:
    """Remove the attribution."""
    op.drop_index("ix_findings_reviewed_by", table_name="findings")
    op.drop_column("findings", "reviewed_by")
    op.drop_column("findings", "review_note")
    op.drop_column("findings", "reviewed_at")
