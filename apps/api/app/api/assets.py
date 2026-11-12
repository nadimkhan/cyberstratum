"""Tracked-asset endpoints.

A tracked asset is an address a workspace follows: its own deployment, a
contract it is about to ship, or anything autonomous discovery turned up.

Every scan of that address is attached to the asset, so the asset's
history is the dated record of what was found and when. This is the
product's answer to "keep track of my progress": the open-finding count
of an address is the number that moves when a fix ships.

Tenant scoping follows the conventions in :mod:`app.core.security`:

* a tenant principal only ever sees its own workspace,
* an asset belonging to another workspace is reported as **404**, exactly
  like one that does not exist,
* the administrative service key may act across tenants, and only it.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.core.security import (
    CurrentPrincipal,
    Principal,
    SessionDep,
    read_scope,
    write_workspace_id,
)
from app.db.enums import ScanJobStatus, ScanStatus
from app.db.models.assets import TrackedAsset
from app.db.models.identity import Chain, Workspace
from app.queue.connection import get_queue
from app.schemas.assets import (
    AssetCreateRequest,
    AssetDetail,
    AssetHistoryResponse,
    AssetListResponse,
    AssetProgress,
    AssetRead,
    AssetTimelineEntry,
)
from app.schemas.scans import ScanAcceptedResponse
from app.services.assets import (
    AssetFindingSummary,
    AssetScanSummary,
    InvalidAddressError,
    asset_timeline,
    finding_summaries,
    normalise_address,
    scan_summaries,
    upsert_asset,
)
from app.services.scan_requests import create_scan, resolve_chain
from app.worker import enqueue_scan

log = get_logger(__name__)

router = APIRouter(prefix="/api/v1/assets", tags=["assets"])


def _resolve_asset(
    session: Session,
    principal: Principal,
    asset_id: uuid.UUID,
    workspace_id: uuid.UUID | None = None,
) -> TrackedAsset:
    """Return the asset, or 404 when it is not the caller's to see."""
    scope = read_scope(principal, workspace_id)
    stmt = select(TrackedAsset).where(TrackedAsset.id == asset_id)
    if scope is not None:
        stmt = stmt.where(TrackedAsset.workspace_id == scope)
    asset = session.execute(stmt).scalar_one_or_none()
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="asset not found")
    return asset


def _write_workspace(
    session: Session, principal: Principal, requested: uuid.UUID | None
) -> Workspace:
    """Return the workspace a new asset is filed under."""
    effective = write_workspace_id(principal, requested)
    if effective is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="workspace not found")
    workspace = session.get(Workspace, effective)
    if workspace is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="workspace not found")
    return workspace


def _progress(scans: AssetScanSummary, findings: AssetFindingSummary) -> AssetProgress:
    """Build the progress block from the computed summaries."""
    return AssetProgress(
        scan_count=scans.scan_count,
        last_scanned_at=scans.last_scanned_at,
        finding_count=findings.finding_count,
        open_finding_count=findings.open_finding_count,
        by_status=dict(findings.by_status),
        by_severity=dict(findings.by_severity),
    )


def _timeline_entry(row: object) -> AssetTimelineEntry:
    """Turn a timeline row into its API shape."""
    return AssetTimelineEntry(
        scan_id=row.scan_id,  # type: ignore[attr-defined]
        created_at=row.created_at,  # type: ignore[attr-defined]
        status=row.status,  # type: ignore[attr-defined]
        finding_count=row.finding_count,  # type: ignore[attr-defined]
        by_status=dict(row.by_status),  # type: ignore[attr-defined]
        by_severity=dict(row.by_severity),  # type: ignore[attr-defined]
    )


def _detail(
    session: Session,
    asset: TrackedAsset,
    *,
    scans: AssetScanSummary | None = None,
    findings: AssetFindingSummary | None = None,
    evm_chain_id: int | None = None,
    timeline: list[AssetTimelineEntry] | None = None,
) -> AssetDetail:
    """Build the detail view of one asset."""
    if scans is None:
        scans = scan_summaries(session, [asset.id]).get(asset.id, AssetScanSummary())
    if findings is None:
        findings = finding_summaries(session, [asset.id]).get(asset.id, AssetFindingSummary())
    if evm_chain_id is None:
        chain = session.get(Chain, asset.chain_id)
        evm_chain_id = chain.chain_id if chain is not None else 0
    return AssetDetail(
        asset=AssetRead.model_validate(asset),
        evm_chain_id=evm_chain_id,
        progress=_progress(scans, findings),
        timeline=timeline or [],
    )


@router.get("", response_model=AssetListResponse, summary="List tracked assets")
def list_assets(
    session: SessionDep,
    principal: CurrentPrincipal,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    workspace_id: uuid.UUID | None = Query(default=None),
) -> AssetListResponse:
    """List the addresses the caller's workspace follows.

    The list only ever contains the caller's own assets. A
    ``workspace_id`` naming another workspace is refused with ``403``.
    """
    scope = read_scope(principal, workspace_id)

    stmt = select(TrackedAsset).order_by(TrackedAsset.created_at.desc())
    count_stmt = select(func.count()).select_from(TrackedAsset)
    if scope is not None:
        stmt = stmt.where(TrackedAsset.workspace_id == scope)
        count_stmt = count_stmt.where(TrackedAsset.workspace_id == scope)

    total = int(session.execute(count_stmt).scalar_one())
    assets = session.scalars(stmt.limit(limit).offset(offset)).all()
    if not assets:
        return AssetListResponse(items=[], total=total)

    asset_ids = [asset.id for asset in assets]
    scans = scan_summaries(session, asset_ids)
    findings = finding_summaries(session, asset_ids)
    chains = {
        chain.id: chain.chain_id
        for chain in session.scalars(
            select(Chain).where(Chain.id.in_([asset.chain_id for asset in assets]))
        ).all()
    }

    items = [
        _detail(
            session,
            asset,
            scans=scans.get(asset.id, AssetScanSummary()),
            findings=findings.get(asset.id, AssetFindingSummary()),
            evm_chain_id=chains.get(asset.chain_id, 0),
        )
        for asset in assets
    ]
    return AssetListResponse(items=items, total=total)


@router.post(
    "",
    response_model=AssetDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Track an address",
)
def create_asset(
    payload: AssetCreateRequest,
    session: SessionDep,
    principal: CurrentPrincipal,
) -> AssetDetail:
    """Register an address to follow.

    Registration is idempotent: tracking the same address twice returns
    the same asset rather than a second row, because two rows would split
    the contract's history in half.
    """
    workspace = _write_workspace(session, principal, payload.workspace_id)
    chain = resolve_chain(session, payload.chain_id)
    try:
        address = normalise_address(payload.address)
    except InvalidAddressError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    asset = upsert_asset(
        session,
        workspace,
        chain,
        address,
        label=payload.label,
        kind=payload.kind,
        notes=payload.notes,
    )
    # The request-scoped session is closed, not committed, at the end of
    # the request: an endpoint that persists something has to say so.
    session.commit()
    session.refresh(asset)
    return _detail(session, asset)


@router.get("/{asset_id}", response_model=AssetDetail, summary="Inspect a tracked asset")
def get_asset(
    asset_id: uuid.UUID,
    session: SessionDep,
    principal: CurrentPrincipal,
    workspace_id: uuid.UUID | None = Query(default=None),
) -> AssetDetail:
    """Return one asset with its progress and recent history."""
    asset = _resolve_asset(session, principal, asset_id, workspace_id)
    timeline = [_timeline_entry(row) for row in asset_timeline(session, asset, limit=20)]
    return _detail(session, asset, timeline=timeline)


@router.get(
    "/{asset_id}/history",
    response_model=AssetHistoryResponse,
    summary="The dated history of a tracked asset",
)
def get_asset_history(
    asset_id: uuid.UUID,
    session: SessionDep,
    principal: CurrentPrincipal,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    workspace_id: uuid.UUID | None = Query(default=None),
) -> AssetHistoryResponse:
    """Return every scan taken against an address, newest first.

    This is the progress log: each entry carries the date, the outcome
    of the scan and what it found.
    """
    asset = _resolve_asset(session, principal, asset_id, workspace_id)
    scans = scan_summaries(session, [asset.id]).get(asset.id, AssetScanSummary())
    findings = finding_summaries(session, [asset.id]).get(asset.id, AssetFindingSummary())
    rows = asset_timeline(session, asset, limit=limit, offset=offset)
    chain = session.get(Chain, asset.chain_id)
    return AssetHistoryResponse(
        asset=AssetRead.model_validate(asset),
        evm_chain_id=chain.chain_id if chain is not None else 0,
        progress=_progress(scans, findings),
        timeline=[_timeline_entry(row) for row in rows],
        total=scans.scan_count,
    )


@router.post(
    "/{asset_id}/scan",
    response_model=ScanAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Scan a tracked asset again",
)
def rescan_asset(
    asset_id: uuid.UUID,
    session: SessionDep,
    principal: CurrentPrincipal,
) -> ScanAcceptedResponse:
    """Queue a fresh scan of a tracked address.

    The new scan is attached to the asset, so the history grows: this is
    how a user checks whether the fix they shipped actually moved the
    number.
    """
    asset = _resolve_asset(session, principal, asset_id)
    workspace = session.get(Workspace, asset.workspace_id)
    chain = session.get(Chain, asset.chain_id)
    if workspace is None or chain is None:  # pragma: no cover - FKs protect this
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="asset not found")

    scan, job = create_scan(
        session,
        workspace=workspace,
        chain=chain,
        address=asset.address,
        label=asset.label,
        requested_by=principal.user_id,
        asset=asset,
        queue_name=get_queue().name,
    )

    try:
        rq_job_id = enqueue_scan(scan.id, job.id)
    except Exception as exc:  # noqa: BLE001 - a queue failure is reported, not raised
        log.error("asset_rescan_enqueue_failed", asset_id=str(asset.id), error=str(exc))
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


@router.delete(
    "/{asset_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Stop tracking an address",
)
def stop_tracking(
    asset_id: uuid.UUID,
    session: SessionDep,
    principal: CurrentPrincipal,
) -> Response:
    """Stop following an address.

    The scans and findings stay: the history of a contract outlives the
    decision to keep watching it.
    """
    asset = _resolve_asset(session, principal, asset_id)
    asset.active = False
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
