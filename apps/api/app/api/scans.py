"""Scan endpoints: submit, list and inspect scans."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.logging import get_logger
from app.core.security import CurrentPrincipal, SessionDep
from app.db.enums import ScanJobStatus, ScanJobType, ScanStatus
from app.db.models.identity import Chain, ContractTarget, Workspace
from app.db.models.scans import Finding, Scan, ScanJob
from app.queue.connection import get_queue
from app.schemas.findings import FindingListResponse, FindingRead
from app.schemas.scans import (
    ScanAcceptedResponse,
    ScanCreateRequest,
    ScanDetail,
    ScanListResponse,
    ScanSummary,
)
from app.worker import enqueue_scan

log = get_logger(__name__)

router = APIRouter(prefix="/api/v1/scans", tags=["scans"])

#: Slug of the workspace used when the caller does not specify one.
DEFAULT_WORKSPACE_SLUG = "default"


def _default_workspace(session: Session) -> Workspace:
    """Return the default workspace, creating it when it does not exist."""
    workspace = session.scalars(
        select(Workspace).where(Workspace.slug == DEFAULT_WORKSPACE_SLUG)
    ).one_or_none()
    if workspace is None:
        workspace = Workspace(name="Default workspace", slug=DEFAULT_WORKSPACE_SLUG)
        session.add(workspace)
        session.flush()
    return workspace


def _resolve_workspace(session: Session, requested: uuid.UUID | None) -> Workspace:
    """Resolve the workspace a scan should be filed under."""
    if requested is not None:
        workspace = session.get(Workspace, requested)
        if workspace is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Workspace {requested} not found.",
            )
        return workspace
    return _default_workspace(session)


def _resolve_chain(session: Session, chain_id: int) -> Chain:
    """Return the chain row for an EVM chain id."""
    chain = session.scalars(select(Chain).where(Chain.chain_id == chain_id)).one_or_none()
    if chain is None:
        chain = Chain(name=f"Chain {chain_id}", chain_id=chain_id, environment="mainnet")
        session.add(chain)
        session.flush()
    return chain


def _upsert_target(
    session: Session,
    workspace: Workspace,
    chain: Chain,
    address: str,
    label: str | None,
    inline_bytecode: bytes | None = None,
) -> ContractTarget:
    """Return the existing target for ``address`` or create one.

    When ``inline_bytecode`` is given, it is stored on the target so that the
    worker analyses exactly those bytes instead of contacting an RPC.
    """
    target = session.scalars(
        select(ContractTarget).where(
            ContractTarget.workspace_id == workspace.id,
            ContractTarget.chain_id == chain.id,
            ContractTarget.address == address,
        )
    ).one_or_none()
    if target is None:
        target = ContractTarget(
            workspace_id=workspace.id,
            chain_id=chain.id,
            address=address,
            label=label or address,
            bytecode_type="runtime",
            authorization_status="unknown",
            inline_bytecode=inline_bytecode,
        )
        session.add(target)
        session.flush()
    else:
        if label:
            target.label = label
        if inline_bytecode is not None:
            target.inline_bytecode = inline_bytecode
        session.flush()
    return target


@router.post(
    "",
    response_model=ScanAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Queue a scan of a contract",
)
def submit_scan(
    payload: ScanCreateRequest,
    session: SessionDep,
    principal: CurrentPrincipal,
) -> ScanAcceptedResponse:
    """Create a scan and enqueue the corresponding RQ job.

    Returns ``202 Accepted`` with a scan id and a status URL, per design doc
    section 10.1.
    """
    workspace = _resolve_workspace(session, payload.workspace_id)
    chain = _resolve_chain(session, payload.chain_id)

    inline_bytecode: bytes | None = None
    if payload.bytecode_hex is not None:
        inline_bytecode = bytes.fromhex(payload.bytecode_hex)

    target = _upsert_target(
        session,
        workspace,
        chain,
        payload.contract_address,
        payload.label,
        inline_bytecode=inline_bytecode,
    )

    scan = Scan(
        workspace_id=workspace.id,
        target_id=target.id,
        status=ScanStatus.QUEUED,
        requested_by=principal.user_id,
        fork=payload.fork,
        bytecode_source="upload" if inline_bytecode is not None else "rpc",
        queued_at=datetime.now(UTC),
    )
    session.add(scan)
    session.flush()

    job = ScanJob(
        scan_id=scan.id,
        job_type=ScanJobType.SCAN,
        queue_name=get_queue().name,
        status=ScanJobStatus.QUEUED,
        attempt=0,
    )
    session.add(job)
    session.flush()

    try:
        rq_job_id = enqueue_scan(scan.id, job.id)
    except Exception as exc:  # noqa: BLE001 - queue failure must be reported, not crash
        log.error("scan_enqueue_failed", scan_id=str(scan.id), error=str(exc))
        job.status = ScanJobStatus.FAILED
        scan.status = ScanStatus.FAILED
        scan.error_code = "queue_unavailable"
        scan.error_message_redacted = "The job queue is unavailable; the scan was not queued."
        session.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The job queue is unavailable. Please retry later.",
        ) from exc

    job.rq_job_id = rq_job_id
    session.commit()

    return ScanAcceptedResponse(
        id=scan.id,
        status=scan.status,
        status_url=f"/api/v1/scans/{scan.id}",
        queue_name=job.queue_name,
    )


def _finding_counts(session: Session, scan_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict[str, int]]:
    """Return the finding count per severity for each of ``scan_ids``.

    One grouped query serves the whole page, so listing scans does not
    issue a query per row.
    """
    if not scan_ids:
        return {}
    rows = session.execute(
        select(Finding.scan_id, Finding.severity, func.count())
        .where(Finding.scan_id.in_(scan_ids))
        .group_by(Finding.scan_id, Finding.severity)
    ).all()
    counts: dict[uuid.UUID, dict[str, int]] = {}
    for scan_id, severity, amount in rows:
        key = severity.value if hasattr(severity, "value") else str(severity)
        counts.setdefault(scan_id, {})[key] = int(amount)
    return counts


def _summary(session: Session, scan: Scan) -> ScanSummary:
    """Build a scan summary, including its finding counts."""
    summary = ScanSummary.model_validate(scan)
    counts = _finding_counts(session, [scan.id]).get(scan.id, {})
    summary.finding_counts = counts
    summary.total_findings = sum(counts.values())
    return summary


@router.get("", response_model=ScanListResponse, summary="List scans")
def list_scans(
    session: SessionDep,
    principal: CurrentPrincipal,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    scan_status: ScanStatus | None = Query(default=None, alias="status"),
    workspace_id: uuid.UUID | None = Query(default=None),
) -> ScanListResponse:
    """List scans with their status, newest first."""
    stmt = select(Scan).order_by(Scan.created_at.desc())
    count_stmt = select(func.count()).select_from(Scan)

    workspace_filter = workspace_id or principal.workspace_id
    if workspace_filter is not None:
        stmt = stmt.where(Scan.workspace_id == workspace_filter)
        count_stmt = count_stmt.where(Scan.workspace_id == workspace_filter)
    if scan_status is not None:
        stmt = stmt.where(Scan.status == scan_status)
        count_stmt = count_stmt.where(Scan.status == scan_status)

    total = session.scalar(count_stmt) or 0
    rows = session.scalars(stmt.offset(offset).limit(limit)).all()

    counts = _finding_counts(session, [row.id for row in rows])
    items: list[ScanSummary] = []
    for row in rows:
        summary = ScanSummary.model_validate(row)
        row_counts = counts.get(row.id, {})
        summary.finding_counts = row_counts
        summary.total_findings = sum(row_counts.values())
        items.append(summary)

    return ScanListResponse(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{scan_id}", response_model=ScanDetail, summary="Get scan detail")
def get_scan(
    scan_id: uuid.UUID,
    session: SessionDep,
    principal: CurrentPrincipal,
) -> ScanDetail:
    """Return a scan with its jobs, artifacts and findings."""
    scan = session.scalars(
        select(Scan)
        .options(
            selectinload(Scan.jobs),
            selectinload(Scan.artifacts),
            selectinload(Scan.findings),
        )
        .where(Scan.id == scan_id)
    ).one_or_none()
    if scan is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Scan {scan_id} not found."
        )

    workspace_filter = principal.workspace_id
    if workspace_filter is not None and scan.workspace_id != workspace_filter:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Scan {scan_id} not found."
        )

    detail = ScanDetail.model_validate(scan)
    detail.findings = [FindingRead.model_validate(finding) for finding in scan.findings]
    counts = _finding_counts(session, [scan.id]).get(scan.id, {})
    detail.finding_counts = counts
    detail.total_findings = sum(counts.values())
    return detail


@router.get(
    "/{scan_id}/findings",
    response_model=FindingListResponse,
    summary="List the findings of one scan",
)
def list_scan_findings(
    scan_id: uuid.UUID,
    session: SessionDep,
    principal: CurrentPrincipal,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> FindingListResponse:
    """Return the findings produced by one scan, newest first.

    This is the per-scan view of the findings resource. The workspace-wide
    list lives at ``GET /api/v1/findings``.
    """
    scan = session.get(Scan, scan_id)
    if scan is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Scan {scan_id} not found."
        )

    workspace_filter = principal.workspace_id
    if workspace_filter is not None and scan.workspace_id != workspace_filter:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Scan {scan_id} not found."
        )

    stmt = (
        select(Finding)
        .where(Finding.scan_id == scan_id)
        .order_by(Finding.created_at.desc())
    )
    count_stmt = select(func.count()).select_from(Finding).where(Finding.scan_id == scan_id)

    total = session.scalar(count_stmt) or 0
    rows = session.scalars(stmt.offset(offset).limit(limit)).all()
    return FindingListResponse(
        items=[FindingRead.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


__all__ = ["router"]
