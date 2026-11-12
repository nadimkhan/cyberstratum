"""The authorised scope of a workspace.

A workspace declares what is in bounds for it. Every scan it queues
records what the authorisation was at that moment, and this API is
where the declaration is made and read.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.core.security import CurrentPrincipal, SessionDep, read_scope
from app.db.models.scope import ScopeGrant
from app.services.scope import IN_SCOPE, OUT_OF_SCOPE, UNKNOWN_SCOPE, evaluate_scope

router = APIRouter(prefix="/api/v1/scope", tags=["scope"])


class ScopeGrantCreate(BaseModel):
    """A declaration that something is in bounds."""

    model_config = ConfigDict(extra="forbid")

    kind: str = Field(description="One of 'programme', 'contract' or 'chain'.")
    value: str = Field(description="The address, chain id or programme name.")
    chain_id: int | None = Field(default=None, description="The chain, when it applies.")
    safe_harbour: bool = Field(
        default=False,
        description="Whether the programme's safe-harbour rules were read and accepted.",
    )
    reference: str | None = Field(default=None, description="Where the scope is published.")
    expires_at: str | None = Field(default=None, description="When the grant stops applying.")


class ScopeGrantRead(BaseModel):
    """One declared grant, as it is stored."""

    id: uuid.UUID
    kind: str
    value: str
    chain_id: int | None
    safe_harbour: bool
    reference: str | None
    expires_at: str | None
    created_at: str


class ScopeStatusRead(BaseModel):
    """What the registry says about a target."""

    status: str = Field(description="One of 'in_scope', 'out_of_scope' or 'unknown'.")
    reason: str
    statement: str
    grant_id: uuid.UUID | None = None
    reference: str | None = None
    safe_harbour: bool = False


def _workspace_id(principal: Any, requested: uuid.UUID | None) -> uuid.UUID:
    """Return the workspace this request acts in.

    A tenant credential acts in its own workspace. The administrative
    service key must name the workspace it acts in: a declaration of
    scope that applies to every workspace at once is not a
    declaration, and one that touches another tenant's scope without
    saying so is worse.
    """
    scope = read_scope(principal, requested)
    if scope is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="the request does not name a workspace",
        )
    return scope


@router.get("/grants", summary="List the authorised scope of this workspace")
def list_grants(
    session: SessionDep,
    principal: CurrentPrincipal,
    workspace_id: uuid.UUID | None = Query(default=None),
) -> list[ScopeGrantRead]:
    """List the grants this workspace has declared."""
    scope = _workspace_id(principal, workspace_id)
    grants = list(
        session.execute(
            select(ScopeGrant)
            .where(ScopeGrant.workspace_id == scope)
            .order_by(ScopeGrant.created_at)
        )
        .scalars()
        .all()
    )
    return [
        ScopeGrantRead(
            id=grant.id,
            kind=grant.kind,
            value=grant.value,
            chain_id=grant.chain_id,
            safe_harbour=grant.safe_harbour,
            reference=grant.reference,
            expires_at=grant.expires_at.isoformat() if grant.expires_at else None,
            created_at=grant.created_at.isoformat(),
        )
        for grant in grants
    ]


@router.post(
    "/grants",
    status_code=status.HTTP_201_CREATED,
    summary="Declare that something is in bounds",
)
def create_grant(
    payload: ScopeGrantCreate,
    session: SessionDep,
    principal: CurrentPrincipal,
    workspace_id: uuid.UUID | None = Query(default=None),
) -> ScopeGrantRead:
    """Record a scope grant for this workspace."""
    scope = _workspace_id(principal, workspace_id)
    if payload.kind not in {"programme", "contract", "chain"}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="kind must be one of 'programme', 'contract' or 'chain'",
        )
    if not payload.value.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="value must not be empty",
        )

    grant = ScopeGrant(
        workspace_id=scope,
        kind=payload.kind,
        value=payload.value.strip(),
        chain_id=payload.chain_id,
        safe_harbour=payload.safe_harbour,
        reference=payload.reference,
    )
    session.add(grant)
    session.flush()
    # The request-scoped session is closed, not committed, when the
    # request ends: a flush alone would be thrown away. A declaration
    # that is not persisted is not a declaration.
    session.commit()
    return ScopeGrantRead(
        id=grant.id,
        kind=grant.kind,
        value=grant.value,
        chain_id=grant.chain_id,
        safe_harbour=grant.safe_harbour,
        reference=grant.reference,
        expires_at=grant.expires_at.isoformat() if grant.expires_at else None,
        created_at=grant.created_at.isoformat(),
    )


@router.get("/status", summary="Say whether a target is in the authorised scope")
def scope_status(
    session: SessionDep,
    principal: CurrentPrincipal,
    chain_id: int | None = None,
    address: str | None = None,
    workspace_id: uuid.UUID | None = Query(default=None),
) -> ScopeStatusRead:
    """Report the authorisation for a target."""
    scope = _workspace_id(principal, workspace_id)
    decision = evaluate_scope(
        session,
        scope,
        chain_id=chain_id,
        address=address or "",
    )
    return ScopeStatusRead(
        status=decision.status,
        reason=decision.reason,
        statement=decision.statement,
        grant_id=decision.grant_id,
        reference=decision.reference,
        safe_harbour=decision.safe_harbour,
    )


__all__ = [
    "IN_SCOPE",
    "OUT_OF_SCOPE",
    "UNKNOWN_SCOPE",
    "router",
]
