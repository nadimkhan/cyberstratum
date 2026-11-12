"""Listing the workspaces a principal may act in.

A verdict about a finding belongs to one tenant. Before a reviewer can
apply one verdict to many findings, the product has to say which
tenant's findings they are looking at, and a bulk action has to be
refused when that is not known.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import func, select

from app.core.security import CurrentPrincipal, SessionDep, read_scope
from app.db.enums import FindingStatus
from app.db.models.identity import Workspace
from app.db.models.scans import Finding

router = APIRouter(prefix="/api/v1/workspaces", tags=["workspaces"])


class WorkspaceSummary(BaseModel):
    """One workspace and how much of it is still waiting to be reviewed."""

    id: uuid.UUID
    name: str
    slug: str
    open_findings: int


@router.get("", response_model=list[WorkspaceSummary], summary="List the workspaces in scope")
def list_workspaces(
    session: SessionDep,
    principal: CurrentPrincipal,
) -> list[WorkspaceSummary]:
    """Return the workspaces the caller may act in.

    A tenant sees its own workspace and nothing else. The administrative
    service key sees every workspace, because that is what it is for --
    and each row carries how many findings are still open, so a
    reviewer can pick the tenant whose work they are about to do.
    """
    scope = read_scope(principal, None)

    query = select(Workspace).order_by(Workspace.name)
    if scope is not None:
        query = query.where(Workspace.id == scope)

    rows = session.scalars(query).all()
    if not rows:
        return []

    counts = dict(
        session.execute(
            select(Finding.workspace_id, func.count())
            .where(
                Finding.workspace_id.in_([row.id for row in rows]),
                Finding.status.notin_([FindingStatus.CONFIRMED, FindingStatus.FALSE_POSITIVE]),
            )
            .group_by(Finding.workspace_id)
        ).all()
    )

    return [
        WorkspaceSummary(
            id=row.id,
            name=row.name,
            slug=row.slug,
            open_findings=int(counts.get(row.id, 0)),
        )
        for row in rows
    ]
