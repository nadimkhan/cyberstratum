"""allow the database to store a Mythril finding

A Mythril finding is a finding. It belongs in the ``findings`` table with
``source = 'mythril'`` and it has to survive there, because a finding that
is computed and then thrown away is worse than one that was never computed:
the contract looks exactly like one Mythril never examined.

Two things were wrong with the way this was first done.

The revision that widened the constraint was ``e2f5a1b9c740``, which had
already been applied to the development databases. A migration is never
re-run, so the widening would have existed only on a database that was
built from scratch, and the environments that already had the revision
would have kept the narrow constraint - which is exactly where the
failure was found. The change therefore needs a revision of its own.

The constraint is also not named the same thing everywhere. One revision
created it as ``source``; another database has it as
``ck_findings_source``. A migration that drops a constraint by a
hard-coded name fails on whichever database disagrees with it, and a
migration that fails halfway leaves a schema that matches no code at all.
The name is therefore looked up in ``pg_constraint`` and every constraint
that constrains ``source`` is dropped by the name it actually has.

The constraint is widened and not removed. An unknown provenance still
cannot be written by accident.

Revision ID: f7d9a3c1e5b2
Revises: e2f5a1b9c740
Create Date: 2026-10-29

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "f7d9a3c1e5b2"
down_revision: str | None = "e2f5a1b9c740"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The name given to the constraint from here on. The project's naming
#: convention is ``ck_%(table_name)s_%(constraint_name)s``, so this is
#: stored in the database as ``ck_findings_source`` - the same name the
#: constraint has always had. The name is not marked final with ``op.f``:
#: the convention is applied by Alembic when the constraint is attached to
#: the table, and marking it final would only produce the doubled name
#: ``ck_findings_ck_findings_source``.
_CONSTRAINT_NAME = "source"

_OLD_SOURCES = ("rule", "slither", "ml")
_NEW_SOURCES = ("rule", "slither", "ml", "mythril")


def _source_list(sources: tuple[str, ...]) -> str:
    """Render the allowed provenances as a SQL list."""
    return ", ".join(f"'{name}'" for name in sources)


def _drop_source_constraints() -> None:
    """Drop every CHECK constraint on ``findings`` that constrains ``source``.

    The name is looked up rather than assumed. ``pg_get_constraintdef``
    renders the constrained column as ``(source)``, so a constraint on a
    different column that merely mentions the word - ``(bytecode_source)``,
    for instance - is not matched.
    """
    op.execute(
        """
        DO $$
        DECLARE
            constraint_name text;
        BEGIN
            FOR constraint_name IN
                SELECT conname
                FROM pg_constraint
                WHERE conrelid = 'findings'::regclass
                  AND contype = 'c'
                  AND pg_get_constraintdef(oid) LIKE '%(source)%'
            LOOP
                EXECUTE format(
                    'ALTER TABLE findings DROP CONSTRAINT %I', constraint_name
                );
            END LOOP;
        END $$;
        """
    )


def upgrade() -> None:
    """Widen the provenance constraint to include Mythril."""
    _drop_source_constraints()
    op.create_check_constraint(
        _CONSTRAINT_NAME,
        "findings",
        f"source IN ({_source_list(_NEW_SOURCES)})",
    )


def downgrade() -> None:
    """Narrow the constraint back to the three provenances it allowed.

    The findings written by Mythril cannot exist in the older schema, so
    they are removed first rather than being left to violate the restored
    constraint.
    """
    op.execute("DELETE FROM findings WHERE source = 'mythril'")
    _drop_source_constraints()
    op.create_check_constraint(
        _CONSTRAINT_NAME,
        "findings",
        f"source IN ({_source_list(_OLD_SOURCES)})",
    )
