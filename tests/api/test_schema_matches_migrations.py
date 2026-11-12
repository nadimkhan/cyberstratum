"""The migrated schema must match the ORM models, for every table.

This is the general version of the check that once caught the one missing
constraint. ``tests/api/test_migration_contract.py`` proves that a
*specific* constraint exists in the migrated database. This test proves the
broader property: **whatever the ORM models declare is what the migration
chain actually creates**, and vice versa.

Why it matters: a defect that exists only in a migration is invisible to
every other test in the suite. The application talks to the database through
the ORM, so a missing column, a narrowed type, a dropped index or a
constraint that was never created all fail *at runtime*, in production,
on a column the model believes exists. The reverse is just as bad: a column
in the database that the model does not know about is a column nobody
validates.

The comparison is done against a **throwaway database** that the test
creates, migrates from scratch with the real Alembic chain, and drops
again. The development and test databases are never touched.
"""

from __future__ import annotations

import os
import re
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, create_engine, inspect
from sqlalchemy.engine.reflection import Inspector

from app.core.config import get_settings
from app.db.base import Base

#: The Alembic version table is created by the migration chain itself and is
#: not part of the ORM's model, so it is not a difference.
ALEMBIC_VERSION_TABLE = "alembic_version"


def _database_name(url: str) -> str:
    """Return the database name of a SQLAlchemy URL."""
    return url.rsplit("/", 1)[-1].split("?", 1)[0]


def _url_for_database(url: str, database: str) -> str:
    """Return the same URL pointing at another database."""
    head, _, _ = url.rpartition("/")
    return f"{head}/{database}"


def _maintenance_url(url: str) -> str:
    """Return a URL pointing at the ``postgres`` maintenance database."""
    return _url_for_database(url, "postgres")


def _create_scratch_database(url: str) -> str:
    """Create a throwaway database and return its URL.

    The database is created from the ``postgres`` maintenance database with
    the application's own credentials, so the test needs no superuser and
    no hard-coded password.
    """
    name = f"cs_schemadiff_{uuid.uuid4().hex[:10]}"
    engine = create_engine(_maintenance_url(url), isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql(f'CREATE DATABASE "{name}"')
    finally:
        engine.dispose()
    return _url_for_database(url, name)


def _drop_scratch_database(url: str, database: str) -> None:
    """Drop the throwaway database, killing any leftover connections."""
    engine = create_engine(_maintenance_url(url), isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (database,),
            )
            connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{database}"')
    finally:
        engine.dispose()


def _migrate(scratch_url: str) -> None:
    """Run the real Alembic chain against the scratch database.

    The migration environment reads the URL from the application settings,
    so the setting is pointed at the scratch database for the duration of
    the migration and restored afterwards.
    """
    from alembic import command
    from alembic.config import Config

    repo_root = Path(__file__).resolve().parents[2]
    original = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = scratch_url
    get_settings.cache_clear()
    try:
        config = Config(str(repo_root / "alembic.ini"))
        # The ini file uses paths relative to the repository root; make them
        # absolute so the test does not depend on the working directory.
        config.set_main_option("script_location", str(repo_root / "apps" / "api" / "alembic"))
        config.set_main_option("prepend_sys_path", str(repo_root / "apps" / "api"))
        command.upgrade(config, "head")
    finally:
        if original is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = original
        get_settings.cache_clear()


def _normalise_type(value: str) -> str:
    """Return a comparable form of a SQL type name.

    SQLAlchemy's generic ``DateTime`` renders as ``TIMESTAMP`` on
    PostgreSQL, so the two spellings are the same type.
    """
    text = value.strip().upper()
    text = text.replace(", ", ",")
    text = text.replace(" (", "(")
    text = text.replace("DATETIME", "TIMESTAMP")
    text = text.replace("BLOB", "BYTEA")
    text = text.replace("FLOAT", "DOUBLE PRECISION")
    return text


def _normalise_default(value: Any) -> str:
    """Return a comparable form of a column default."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    text = str(value).strip()
    if text.lower() == "null":
        return ""
    text = text.replace("::character varying", "").replace("::text", "").strip()
    text = text.strip("()")
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        text = text[1:-1]
    return text.strip().lower()


def _model_default(column: Any) -> str:
    """Return the default the *database* applies for a column.

    Only a server default counts. A Python-side default (``default=False``,
    ``default=uuid.uuid4``) is applied by the ORM when it inserts a row;
    the database knows nothing about it, so it has no counterpart to
    compare against.
    """
    server_default = column.server_default
    if server_default is None:
        return ""
    argument = getattr(server_default, "arg", None)
    if argument is not None:
        return _normalise_default(argument)
    return _normalise_default(server_default)


def _normalise_check(text: str) -> str:
    """Return a comparable form of a CHECK constraint expression.

    PostgreSQL stores ``x IN ('a', 'b')`` in its canonical form
    ``x = ANY (ARRAY['a', 'b'])``, so the two spellings are folded
    together. Everything else is compared literally, without whitespace
    or quoting, so that a genuine change of meaning still shows up.
    """
    value = text.strip().lower()
    # PostgreSQL stores the canonical form of ``x IN ('a', 'b')`` as
    # ``x = ANY (ARRAY['a'::character varying, 'b'::character varying]::text[])``,
    # so the element casts and the array cast are removed before the two
    # spellings are folded together.
    value = re.sub(r"::[a-z ]+\[\]", "", value)
    value = value.replace("::character varying", "").replace("::text", "")
    value = value.replace("'", "")
    value = value.replace(" ", "")
    match = re.fullmatch(r"(.+)=any\((?:array)?\[(.*)\]\)", value)
    if match:
        value = f"{match.group(1)}in({match.group(2)})"
    return value


def _metadata_checks(table: Any) -> set[str]:
    """Return the CHECK constraints the ORM declares for a table."""
    checks: set[str] = set()
    for constraint in table.constraints:
        if constraint.__class__.__name__ != "CheckConstraint":
            continue
        sqltext = getattr(constraint, "sqltext", None)
        if sqltext is not None:
            checks.add(_normalise_check(str(sqltext)))
    return checks


def _metadata_indexes(table: Any) -> dict[str, tuple[str, ...]]:
    """Return the ORM's indexes as ``name -> columns``."""
    indexes: dict[str, tuple[str, ...]] = {}
    for index in table.indexes:
        indexes[index.name] = tuple(column.name for column in index.columns)
    return indexes


def _compare(
    inspector: Inspector,
) -> list[str]:
    """Return every difference between the models and the migrated schema."""
    differences: list[str] = []

    database_tables = {
        name for name in inspector.get_table_names() if name != ALEMBIC_VERSION_TABLE
    }
    model_tables = set(Base.metadata.tables)

    for missing in sorted(model_tables - database_tables):
        differences.append(
            f"table {missing}: declared by the models but not created by the migrations"
        )
    for extra in sorted(database_tables - model_tables):
        differences.append(
            f"table {extra}: created by the migrations but not declared by the models"
        )

    for name in sorted(model_tables & database_tables):
        model_table = Base.metadata.tables[name]
        live_columns = {column["name"]: column for column in inspector.get_columns(name)}
        model_columns = {column.name: column for column in model_table.columns}

        for missing in sorted(set(model_columns) - set(live_columns)):
            differences.append(f"table {name}: column {missing} is declared but not created")
        for extra in sorted(set(live_columns) - set(model_columns)):
            differences.append(f"table {name}: column {extra} exists but is not declared")

        for column_name in sorted(set(model_columns) & set(live_columns)):
            model_column = model_columns[column_name]
            live_column = live_columns[column_name]

            model_type = _normalise_type(str(model_column.type))
            live_type = _normalise_type(str(live_column["type"]))
            if model_type != live_type:
                differences.append(
                    f"table {name}: column {column_name} type is {live_type} in the database "
                    f"but {model_type} in the models"
                )

            live_nullable = bool(live_column.get("nullable", True))
            if bool(model_column.nullable) != live_nullable:
                differences.append(
                    f"table {name}: column {column_name} is "
                    f"{'nullable' if live_nullable else 'not nullable'} in the database but "
                    f"{'nullable' if model_column.nullable else 'not nullable'} in the models"
                )

            model_default = _model_default(model_column)
            live_default = _normalise_default(live_column.get("default"))
            if model_default != live_default:
                differences.append(
                    f"table {name}: column {column_name} default is {live_default!r} in the "
                    f"database but {model_default!r} in the models"
                )

        model_pk = tuple(sorted(column.name for column in model_table.primary_key.columns))
        live_pk = tuple(
            sorted((inspector.get_pk_constraint(name) or {}).get("constrained_columns") or [])
        )
        if model_pk != live_pk:
            differences.append(
                f"table {name}: primary key is {live_pk} in the database "
                f"but {model_pk} in the models"
            )

        model_fks = {
            (
                tuple(column.name for column in constraint.columns),
                str(constraint.referred_table.name),
                tuple(element.column.name for element in constraint.elements),
            )
            for constraint in model_table.constraints
            if constraint.__class__.__name__ == "ForeignKeyConstraint"
        }
        live_fks = {
            (
                tuple(fk.get("constrained_columns") or []),
                str(fk.get("referred_table")),
                tuple(fk.get("referred_columns") or []),
            )
            for fk in inspector.get_foreign_keys(name)
        }
        for missing in sorted(model_fks - live_fks):
            differences.append(f"table {name}: foreign key {missing} is declared but not created")
        for extra in sorted(live_fks - model_fks):
            differences.append(f"table {name}: foreign key {extra} exists but is not declared")

        model_uniques = {
            frozenset(constraint.columns.keys())
            for constraint in model_table.constraints
            if constraint.__class__.__name__ == "UniqueConstraint"
        }
        # A column declared ``unique=True`` is a uniqueness promise too.
        model_uniques |= {
            frozenset({column.name}) for column in model_table.columns if column.unique
        }
        live_indexes_by_name = {
            index["name"]: (
                tuple(index.get("column_names") or []),
                bool(index.get("unique")),
            )
            for index in inspector.get_indexes(name)
            if index.get("name") is not None
        }
        live_uniques = {
            frozenset(constraint.get("column_names") or [])
            for constraint in inspector.get_unique_constraints(name)
        }
        # PostgreSQL may enforce uniqueness with a constraint or with a
        # unique index. Both are the same promise, so both count.
        live_uniques |= {
            frozenset(columns) for columns, unique in live_indexes_by_name.values() if unique
        }
        for missing in sorted(model_uniques - live_uniques, key=sorted):
            differences.append(
                f"table {name}: unique constraint {sorted(missing)} is declared but not created"
            )
        for extra in sorted(live_uniques - model_uniques, key=sorted):
            differences.append(
                f"table {name}: unique constraint {sorted(extra)} exists but is not declared"
            )

        model_checks = _metadata_checks(model_table)
        live_checks = {
            _normalise_check(constraint.get("sqltext") or "")
            for constraint in inspector.get_check_constraints(name)
        }
        for missing in sorted(model_checks - live_checks):
            differences.append(
                f"table {name}: check constraint {missing!r} is declared but not created"
            )
        for extra in sorted(live_checks - model_checks):
            differences.append(
                f"table {name}: check constraint {extra!r} exists but is not declared"
            )

        model_indexes = _metadata_indexes(model_table)
        for missing in sorted(set(model_indexes) - set(live_indexes_by_name)):
            differences.append(f"table {name}: index {missing} is declared but not created")
        for shared in sorted(set(model_indexes) & set(live_indexes_by_name)):
            live_columns, _ = live_indexes_by_name[shared]
            if model_indexes[shared] != live_columns:
                differences.append(
                    f"table {name}: index {shared} covers {live_columns} in the "
                    f"database but {model_indexes[shared]} in the models"
                )
        for extra in sorted(
            name
            for name, (_, unique) in live_indexes_by_name.items()
            if name not in model_indexes and not unique
        ):
            differences.append(f"table {name}: index {extra} exists but is not declared")

    return differences


@pytest.fixture(scope="module")
def scratch_schema() -> Iterator[tuple[str, str]]:
    """Create, migrate and drop a throwaway database."""
    url = get_settings().database_url
    scratch_url = _create_scratch_database(url)
    database = _database_name(scratch_url)
    try:
        _migrate(scratch_url)
        yield scratch_url, database
    finally:
        _drop_scratch_database(url, database)


def test_the_migrated_schema_matches_the_models(scratch_schema: tuple[str, str]) -> None:
    """The migration chain creates exactly what the models declare."""
    scratch_url, _ = scratch_schema
    engine: Engine = create_engine(scratch_url)
    try:
        differences = _compare(inspect(engine))
    finally:
        engine.dispose()

    summary = "The migrated schema and the ORM models disagree:\n  - " + "\n  - ".join(differences)
    assert not differences, summary


def test_the_scratch_database_is_dropped_again(scratch_schema: tuple[str, str]) -> None:
    """The test leaves no database behind.

    This is a guard on the test itself: a schema-diff test that leaks a
    database on every run would fill the development cluster with debris.
    The database is dropped by the fixture's ``finally`` block, which runs
    after this test, so this assertion checks the *next* run sees a clean
    cluster rather than a growing pile.
    """
    _, database = scratch_schema
    url = get_settings().database_url
    engine = create_engine(_maintenance_url(url), isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as connection:
            rows = connection.exec_driver_sql(
                "SELECT count(*) FROM pg_database WHERE datname = %s", (database,)
            ).scalar()
    finally:
        engine.dispose()

    assert rows == 1, "The scratch database should exist while the test runs"
