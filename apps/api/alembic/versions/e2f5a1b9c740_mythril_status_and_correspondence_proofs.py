"""record Mythril runs and store correspondence proofs

Two related additions, both about honesty about what actually ran.

1. ``scans.mythril_ran`` / ``scans.mythril_skipped`` mirror the existing
   ``source_audited`` / ``source_audit_skipped`` pair. Mythril is manual-only
   and slow, so a scan has to be able to say whether it ran at all and, if it
   did not, why. A Mythril run that produced no verdict is recorded here; it
   is never presented as a clean result.

2. ``correspondence_proofs`` stores the source-to-bytecode correspondence
   evidence for a scan. The proof is the only thing that licenses the
   product to print an exact source path and line against a finding, so it
   has to be a first-class stored object rather than a throwaway script
   output. Its ``status`` keeps ``mismatch`` (the source genuinely does not
   describe the deployed contract) separate from ``unavailable`` (the check
   could not be performed: the compiler hung, crashed, was missing, or
   emitted non-JSON). Collapsing those two would let a tooling failure be
   reported as evidence against a contract.

The ``scan_jobs.job_type`` column is a VARCHAR with no database-level CHECK
constraint: the allowed values are enforced by the ORM type, which validates
every value on the way in. Widening the enum therefore needs a wider column,
not a rewritten constraint - and "correspondence" is fourteen characters
where the old longest value, "reproduction", was twelve.

The ``findings.source`` column is the opposite: it *does* carry a database
CHECK constraint, and it allowed only 'rule', 'slither' and 'ml'. A Mythril
finding was therefore rejected with a CheckViolation - the engine ran, found
real issues, and the product discarded them. Widening that constraint is
not done here: this revision was already applied to the development
databases, and a migration is never re-run. The constraint is widened by
the revision that follows, ``f7d9a3c1e5b2``.

Revision ID: e2f5a1b9c740
Revises: c4a90d1e7b23
Create Date: 2026-10-29

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e2f5a1b9c740"
down_revision: str | None = "c4a90d1e7b23"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The old and new widths of ``scan_jobs.job_type``. The new width is the
#: length of the longest job type, "correspondence".
_JOB_TYPE_OLD_LENGTH = 12
_JOB_TYPE_NEW_LENGTH = 14

_CORRESPONDENCE_STATUSES = ("established", "skipped", "mismatch", "unavailable")


def upgrade() -> None:
    # --- scan_job_type gains 'mythril' and 'correspondence' ---------------
    # The column is a VARCHAR whose allowed values are enforced by the ORM
    # type rather than by a database CHECK constraint, so the only schema
    # change needed is a wider column.
    op.alter_column(
        "scan_jobs",
        "job_type",
        existing_type=sa.VARCHAR(_JOB_TYPE_OLD_LENGTH),
        type_=sa.VARCHAR(_JOB_TYPE_NEW_LENGTH),
        existing_nullable=False,
        postgresql_using=f"job_type::varchar({_JOB_TYPE_NEW_LENGTH})",
    )

    # --- Mythril run status on the scan ----------------------------------
    op.add_column(
        "scans",
        sa.Column(
            "mythril_ran",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "scans",
        sa.Column("mythril_skipped", sa.String(length=64), nullable=True),
    )

    # --- correspondence proofs -------------------------------------------
    op.create_table(
        "correspondence_proofs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("scan_id", sa.UUID(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(*_CORRESPONDENCE_STATUSES, name="correspondence_status", native_enum=False),
            nullable=False,
        ),
        sa.Column("skipped", sa.String(length=64), nullable=True),
        sa.Column("compiler_version", sa.String(length=64), nullable=True),
        sa.Column("source_path", sa.String(length=512), nullable=True),
        sa.Column("runtime_sha256", sa.String(length=64), nullable=True),
        sa.Column("executable_sha256", sa.String(length=64), nullable=True),
        sa.Column("metadata_sha256", sa.String(length=64), nullable=True),
        sa.Column("runtime_byte_size", sa.Integer(), nullable=True),
        sa.Column("executable_byte_size", sa.Integer(), nullable=True),
        sa.Column("instruction_count", sa.Integer(), nullable=True),
        sa.Column("mapped_instruction_count", sa.Integer(), nullable=True),
        sa.Column("proof_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["scan_id"],
            ["scans.id"],
            name=op.f("fk_correspondence_proofs_scan_id_scans"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_correspondence_proofs")),
    )
    op.create_index(
        op.f("ix_correspondence_proofs_scan_id"),
        "correspondence_proofs",
        ["scan_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_correspondence_proofs_status"),
        "correspondence_proofs",
        ["status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_correspondence_proofs_status"), table_name="correspondence_proofs")
    op.drop_index(op.f("ix_correspondence_proofs_scan_id"), table_name="correspondence_proofs")
    op.drop_table("correspondence_proofs")

    op.drop_column("scans", "mythril_skipped")
    op.drop_column("scans", "mythril_ran")

    # The rows for the job types this migration introduced cannot exist in
    # the older schema, so they are removed rather than silently truncated
    # into an invalid value.
    op.execute("DELETE FROM scan_jobs WHERE job_type IN ('mythril', 'correspondence')")
    op.alter_column(
        "scan_jobs",
        "job_type",
        existing_type=sa.VARCHAR(_JOB_TYPE_NEW_LENGTH),
        type_=sa.VARCHAR(_JOB_TYPE_OLD_LENGTH),
        existing_nullable=False,
        postgresql_using=f"job_type::varchar({_JOB_TYPE_OLD_LENGTH})",
    )

    # The findings written by Mythril cannot exist in the older schema, so
    # they go before the CHECK constraint is narrowed back to the three
    # provenances it allowed.
    op.execute("DELETE FROM findings WHERE source = 'mythril'")
