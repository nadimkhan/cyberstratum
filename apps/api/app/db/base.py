"""Declarative base and shared column types for the CyberStratum ORM models."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Enum, MetaData, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

#: Deterministic constraint names keep Alembic autogenerate diffs stable.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Base class for every ORM model."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def uuid_pk() -> Mapped[uuid.UUID]:
    """A UUID primary key column with a client-side default."""
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def created_at_column() -> Mapped[datetime]:
    """A timezone-aware ``created_at`` column defaulting to ``now()``."""
    return mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), default=func.now()
    )


def updated_at_column() -> Mapped[datetime]:
    """A timezone-aware ``updated_at`` column defaulting to ``now()``."""
    return mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        default=func.now(),
        onupdate=func.now(),
    )


__all__ = [
    "Base",
    "JSONB",
    "NAMING_CONVENTION",
    "UUID",
    "created_at_column",
    "updated_at_column",
    "uuid_pk",
]


def enum_column(enum_cls: type[StrEnum], name: str) -> Enum:
    """Build a SQLAlchemy column type that stores the enum *values*.

    SQLAlchemy's default stores the member *names*; CyberStratum stores the
    lowercase values so the database, the API responses and the design doc's
    example contracts all agree.
    """
    return Enum(
        enum_cls,
        name=name,
        native_enum=False,
        values_callable=lambda members: [member.value for member in members],
    )
