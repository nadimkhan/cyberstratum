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
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select

from app.core.security import CurrentPrincipal, SessionDep, read_scope
from app.db.enums import FindingStatus, Severity
from app.db.models.identity import AuditEvent
from app.db.models.scans import Finding
from app.schemas.findings import (
    BulkFindingReviewRequest,
    BulkFindingReviewResponse,
    FindingListResponse,
    FindingRead,
    FindingReviewRequest,
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


@router.post(
    "/{finding_id}/review",
    response_model=FindingRead,
    summary="Record a review verdict",
)
def review_finding(
    finding_id: uuid.UUID,
    payload: FindingReviewRequest,
    session: SessionDep,
    principal: CurrentPrincipal,
    workspace_id: uuid.UUID | None = Query(default=None),
) -> FindingRead:
    """Record a human verdict on a finding.

    This is where the labels come from. The verdict, the reviewer, the
    time and the reason are all stored, because a label that cannot be
    attributed cannot be checked and a label without a reason cannot be
    learned from.

    A finding belonging to another tenant is answered with ``404``, not
    ``403``: the existence of another tenant's finding is not something
    this endpoint confirms.
    """
    if payload.status is FindingStatus.NEW:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="'new' is not a review verdict; use 'triage' for an untouched finding",
        )
    note = (payload.note or "").strip()
    if payload.status is FindingStatus.FALSE_POSITIVE and not note:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "a false-positive verdict needs a reason: without one it "
                "cannot be told apart from a mistaken verdict"
            ),
        )

    scope = read_scope(principal, workspace_id)
    stmt = select(Finding).where(Finding.id == finding_id)
    if scope is not None:
        stmt = stmt.where(Finding.workspace_id == scope)
    finding = session.execute(stmt).scalar_one_or_none()
    if finding is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="finding not found"
        )

    finding.status = payload.status
    finding.reviewed_by = principal.user_id
    finding.reviewed_at = datetime.now(UTC)
    finding.review_note = note or None

    session.add(
        AuditEvent(
            workspace_id=finding.workspace_id,
            actor_user_id=principal.user_id,
            action="finding.reviewed",
            resource_type="finding",
            resource_id=str(finding.id),
            metadata_redacted={
                "status": payload.status.value,
                "hasNote": bool(note),
            },
        )
    )
    session.flush()
    # The request-scoped session is closed, not committed, when the request
    # ends: a flush alone would be thrown away. Endpoints that persist
    # something say so.
    session.commit()
    return FindingRead.model_validate(finding)


@router.post(
    "/review-bulk",
    response_model=BulkFindingReviewResponse,
    summary="Settle every open finding of one detector",
)
def review_findings_bulk(
    payload: BulkFindingReviewRequest,
    session: SessionDep,
    principal: CurrentPrincipal,
    workspace_id: uuid.UUID | None = Query(default=None),
) -> BulkFindingReviewResponse:
    """Apply one verdict to every open finding of one detector.

    The rules are the rules of a single verdict: ``new`` is not a
    verdict, a false positive needs a reason, and a finding belonging to
    another tenant is never touched. A finding that has already been
    settled is not overwritten -- it is counted and left alone, because
    a reviewed label is not something to refresh without a reason.

    The scope is always exactly one workspace: the caller's own, or the
    one they named. A bulk action that reaches every tenant is not a
    verdict, so the administrative service key has to name the
    workspace it acts in.
    """
    if payload.status is FindingStatus.NEW:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="'new' is not a review verdict; use 'triage' for an untouched finding",
        )
    note = (payload.note or "").strip()
    if payload.status is FindingStatus.FALSE_POSITIVE and not note:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "a false-positive verdict needs a reason: without one it "
                "cannot be told apart from a mistaken verdict"
            ),
        )

    scope = read_scope(principal, workspace_id)
    if scope is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "a bulk verdict must name the workspace it acts in: the service key "
                "acts across every tenant, and a verdict that reaches every tenant "
                "is not a verdict"
            ),
        )
    base_filters = [
        Finding.detector_id == payload.detector_id,
        Finding.workspace_id == scope,
    ]

    settled_stmt = (
        select(func.count())
        .select_from(Finding)
        .where(
            *base_filters,
            Finding.status.in_([FindingStatus.CONFIRMED, FindingStatus.FALSE_POSITIVE]),
        )
    )
    settled = session.scalar(settled_stmt) or 0

    open_stmt = select(Finding).where(
        *base_filters,
        Finding.status.notin_([FindingStatus.CONFIRMED, FindingStatus.FALSE_POSITIVE]),
    )
    rows = session.scalars(open_stmt.limit(payload.limit)).all()

    now = datetime.now(UTC)
    for finding in rows:
        finding.status = payload.status
        finding.reviewed_by = principal.user_id
        finding.reviewed_at = now
        finding.review_note = note or None
        session.add(
            AuditEvent(
                workspace_id=finding.workspace_id,
                actor_user_id=principal.user_id,
                action="finding.reviewed",
                resource_type="finding",
                resource_id=str(finding.id),
                metadata_redacted={
                    "status": payload.status.value,
                    "hasNote": bool(note),
                    "bulk": True,
                    "detectorId": payload.detector_id,
                },
            )
        )
    session.flush()
    session.commit()
    return BulkFindingReviewResponse(
        detector_id=payload.detector_id,
        status=payload.status,
        applied=len(rows),
        skipped=settled,
        finding_ids=[finding.id for finding in rows],
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
