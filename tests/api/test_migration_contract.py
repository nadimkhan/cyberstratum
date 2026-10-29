"""The migrated schema must accept every finding the code writes.

The test suite builds its schema from ``Base.metadata``. That hides
anything that exists only in a migration - a CHECK constraint, an index, a
column width. The defect this module exists for was found the hard way:
Mythril ran, found a real reentrancy, and the database refused to store
the finding because the migrated ``findings.source`` CHECK constraint
allowed only 'rule', 'slither' and 'ml'. The engine's verdict was
discarded and the contract looked exactly like one Mythril never
examined.

This module applies the real migration chain to the test database and
compares the result with what the code says it writes.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from app.core.config import get_settings
from app.db.base import Base
from app.db.enums import FINDING_SOURCES

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ALEMBIC_INI = _REPO_ROOT / "alembic.ini"

#: The rendered definition of a CHECK constraint lists the allowed values
#: as 'value'::character varying entries.
_ALLOWED = re.compile(r"'([^']+)'::character varying")


def _reset_schema(connection) -> None:
    """Empty the schema completely.

    The migration chain creates everything from scratch, so the tables the
    session fixture built have to go first. The schema is dropped rather
    than table by table because a migration may create a table the models
    do not know about.
    """
    connection.execute(text("DROP SCHEMA public CASCADE"))
    connection.execute(text("CREATE SCHEMA public"))


def _restore_schema(connection) -> None:
    """Put the schema the rest of the suite expects back."""
    _reset_schema(connection)
    Base.metadata.create_all(bind=connection)


@pytest.fixture()
def migrated_schema(engine):
    """Apply the real migration chain to the test database."""
    # The settings are cached. Clearing them makes the migration chain read
    # the test database rather than a URL that was cached before the test
    # fixture set the environment.
    get_settings.cache_clear()
    with engine.begin() as connection:
        _reset_schema(connection)
    try:
        config = Config(str(_ALEMBIC_INI))
        config.set_main_option("script_location", str(_REPO_ROOT / "apps" / "api" / "alembic"))
        command.upgrade(config, "head")
        yield engine
    finally:
        with engine.begin() as connection:
            _restore_schema(connection)


def _constraint_values(engine) -> set[str]:
    """Return the values the findings.source constraint accepts."""
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT pg_get_constraintdef(oid)
                FROM pg_constraint
                WHERE conrelid = 'findings'::regclass
                  AND contype = 'c'
                  AND pg_get_constraintdef(oid) LIKE '%(source)%'
                """
            )
        ).fetchall()
    if len(rows) != 1:
        raise AssertionError(
            f"expected exactly one CHECK constraint on findings.source, found {len(rows)}"
        )
    return set(_ALLOWED.findall(rows[0][0]))


def test_the_migrated_schema_accepts_every_provenance_the_code_writes(migrated_schema):
    """A finding the database refuses is a finding the product discards."""
    accepted = _constraint_values(migrated_schema)
    assert accepted == set(FINDING_SOURCES)


def test_the_migrated_schema_refuses_an_unknown_provenance(migrated_schema):
    """An unknown provenance must not be writable by accident."""
    accepted = _constraint_values(migrated_schema)
    assert "bogus" not in accepted


def test_the_migrated_schema_still_has_the_provenance_constraint(migrated_schema):
    """The constraint must exist at all, not merely be permissive."""
    with migrated_schema.connect() as connection:
        count = connection.execute(
            text(
                """
                SELECT count(*)
                FROM pg_constraint
                WHERE conrelid = 'findings'::regclass AND contype = 'c'
                """
            )
        ).scalar_one()
    assert count >= 1
