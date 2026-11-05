"""Findings endpoints: list/filter findings and a severity breakdown.

Tenant scoping
--------------

Findings belong to the workspace of the scan that produced them. Following
the conventions defined in :mod:`app.core.security`:

* A tenant principal's effective workspace is always its own workspace. A
  ``workspace_id`` query parameter naming a different workspace is refused
  with ``403`` rather than silently honoured or silently ignored.
* The configured service key is an explicit administrative credential and
  may act across every tenant.
* A list endpoint only ever contains the caller's own findings. Filtering
  by a ``scan_id`` from another tenant simply yields an empty list, exactly
  as a ``scan_id`` that does not exist does -- the endpoint never confirms
  that the id exists in another tenant.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from app.core.security import CurrentPrincipal, SessionDep, read_scope
from app.db.enums import FindingStatus, Severity
from app.db.models.scans import Finding
from app.schemas.findings import (
    FindingListResponse,
    FindingRead,
    SeverityBreakdown,
    SeverityCount,
    StatusCount,
)

router = APIRouter(prefix="/api/v1/findings", tags=["findings"])


@router.get("", response_model=FindingListResponse, summary="List findings")
def list_findings(
    session: SessionDep,
    principal: CurrentPrincipal,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    severity: Severity | None = Query(default=None),
    status_filter: FindingStatus | None = Query(default=None, alias="status"),
    category: str | None = Query(default=None),
    scan_id: uuid.UUID | None = Query(default=None),
    workspace_id: uuid.UUID | None = Query(default=None),
) -> FindingListResponse:
    """List findings with optional severity/status/category filters.

    The list only ever contains the caller's own findings. A
    ``workspace_id`` naming another workspace is refused with ``403``.
    """
    stmt = select(Finding).order_by(Finding.created_at.desc())
    count_stmt = select(func.count()).select_from(Finding)

    workspace_filter = read_scope(principal, workspace_id)
    if workspace_filter is not None:
        stmt = stmt.where(Finding.workspace_id == workspace_filter)
        count_stmt = count_stmt.where(Finding.workspace_id == workspace_filter)
    if severity is not None:
        stmt = stmt.where(Finding.severity == severity)
        count_stmt = count_stmt.where(Finding.severity == severity)
    if status_filter is not None:
        stmt = stmt.where(Finding.status == status_filter)
        count_stmt = count_stmt.where(Finding.status == status_filter)
    if category is not None:
        stmt = stmt.where(Finding.category == category)
        count_stmt = count_stmt.where(Finding.category == category)
    if scan_id is not None:
        stmt = stmt.where(Finding.scan_id == scan_id)
        count_stmt = count_stmt.where(Finding.scan_id == scan_id)

    total = session.scalar(count_stmt) or 0
    rows = session.scalars(stmt.offset(offset).limit(limit)).all()

    return FindingListResponse(
        items=[FindingRead.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/summary", response_model=SeverityBreakdown, summary="Severity breakdown")
def severity_breakdown(
    session: SessionDep,
    principal: CurrentPrincipal,
    scan_id: uuid.UUID | None = Query(default=None),
    workspace_id: uuid.UUID | None = Query(default=None),
) -> SeverityBreakdown:
    """Return aggregate counts of findings by severity and triage status.

    The counts only ever cover the caller's own findings. A
    ``workspace_id`` naming another workspace is refused with ``403``.
    """
    workspace_filter = read_scope(principal, workspace_id)

    filters = []
    if workspace_filter is not None:
        filters.append(Finding.workspace_id == workspace_filter)
    if scan_id is not None:
        filters.append(Finding.scan_id == scan_id)

    severity_rows = session.execute(
        select(Finding.severity, func.count()).where(*filters).group_by(Finding.severity)
    ).all()
    status_rows = session.execute(
        select(Finding.status, func.count()).where(*filters).group_by(Finding.status)
    ).all()
    confidence_rows = session.execute(
        select(func.coalesce(func.avg(Finding.confidence), 0.0)).where(*filters)
    ).all()

    by_severity = [
        SeverityCount(severity=severity, count=count) for severity, count in severity_rows
    ]
    by_status = [StatusCount(status=st, count=count) for st, count in status_rows]
    total = sum(item.count for item in by_severity)

    return SeverityBreakdown(
        total=total,
        by_severity=by_severity,
        by_status=by_status,
        average_confidence=round(float(confidence_rows[0][0]), 4) if confidence_rows else 0.0,
    )


__all__ = ["router"]
