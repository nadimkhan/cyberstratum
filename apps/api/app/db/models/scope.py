"""Authorised scope: what this workspace is allowed to assess and disclose.

A commercial scanner is only useful if the person using it can show
*why* they were allowed to look at a contract and what they may do
with what they found. That is what a scope grant is: a declaration,
made by the workspace, that says which contracts, chains or programmes
are in bounds, under which safe-harbour rules, and until when.

The registry is deliberately declarative. It does not make requests to
any programme, it does not crawl a scope file, and it does not decide
what is a bug. It records what the workspace has said is in bounds, so
that every scan can be marked with the authorisation it had -- and so
that a report can say, honestly, whether its subject was in scope.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, created_at_column, uuid_pk


class ScopeGrant(Base):
    """One declaration that something is in bounds for a workspace."""

    __tablename__ = "scope_grants"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('programme', 'contract', 'chain')",
            name="kind",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="contract",
        server_default="contract",
        doc=("What the grant covers: a programme, a single contract address, or a chain."),
    )
    value: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        doc="The address, chain id or programme this grant names.",
    )
    chain_id: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        index=True,
        doc="The chain the grant applies to, when the grant is not chain-agnostic.",
    )
    safe_harbour: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        doc=(
            "Whether the programme's safe-harbour rules were read and "
            "accepted. A grant without them is still a declaration, but "
            "it is not a promise about disclosure."
        ),
    )
    reference: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
        doc="Where the scope was published, so the declaration can be checked.",
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="When the grant stops applying. A grant past this date is ignored.",
    )
    created_at: Mapped[datetime] = created_at_column()


__all__ = ["ScopeGrant"]
