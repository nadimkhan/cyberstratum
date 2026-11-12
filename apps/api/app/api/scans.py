"""Scan endpoints: submit, list and inspect scans.

Tenant scoping
--------------

Every route in this module is scoped to a workspace, following the
conventions defined in :mod:`app.core.security`:

* A tenant principal's effective workspace is always its own workspace. A
  ``workspace_id`` query parameter naming a different workspace is refused
  with ``403`` on a read, and is never honoured on a write: a submitted scan
  is always filed inside the caller's own workspace.
* The configured service key is an explicit administrative credential and
  may act across every tenant; it is the only principal for which a
  ``workspace_id`` selects another workspace.
* A scan belonging to another workspace is reported as **404 Not Found**,
  exactly like a scan that does not exist, so the API never confirms that
  an id exists in another tenant. This applies to the detail endpoint, the
  per-scan findings endpoint, the report download and the action
  endpoints.
* A list endpoint only ever contains the caller's own scans.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, selectinload

from app.core.logging import get_logger
from app.core.security import (
    CurrentPrincipal,
    Principal,
    SessionDep,
    may_read_workspace,
    read_scope,
    write_workspace_id,
)
from app.db.enums import AssetKind, ScanJobStatus, ScanJobType, ScanStatus
from app.db.models.assets import TrackedAsset
from app.db.models.identity import Chain, ContractTarget, Workspace
from app.db.models.scans import (
    CorrespondenceProof,
    Finding,
    Scan,
    ScanArtifact,
    ScanJob,
)
from app.queue.connection import get_correspondence_queue, get_mythril_queue, get_queue
from app.schemas.findings import FindingListResponse, FindingRead
from app.schemas.scans import (
    CorrespondenceProofRead,
    CorrespondenceRunResponse,
    MythrilRunResponse,
    ScanAcceptedResponse,
    ScanCreateRequest,
    ScanDetail,
    ScanListResponse,
    ScanSourceRead,
    ScanSummary,
    SourceFileRead,
)
from app.services import storage
from app.services.assets import InvalidAddressError, normalise_address, upsert_asset
from app.services.model_manifest import ModelManifestError, read_model_manifest
from app.services.report import (
    ReportLabUnavailableError,
    build_report_data,
    render_report,
    report_sha256,
)
from app.services.scan_requests import create_scan, resolve_chain, upsert_target
from app.services.source_compile import (
    CompilationError,
    bytecode_address,
    compile_source,
    pasted_address,
)
from app.worker import enqueue_correspondence, enqueue_mythril, enqueue_scan

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


def _resolve_workspace(
    session: Session,
    principal: Principal,
    requested: uuid.UUID | None,
) -> Workspace:
    """Resolve the workspace a scan should be filed under.

    A tenant principal is always filed inside its own workspace: a
    ``requested`` workspace naming a different one is ignored, so a tenant
    can never file a scan inside another tenant's workspace. The
    administrative service key may name any workspace, and falls back to
    the default workspace when it names none.

    Ignoring the request is not the same as honouring it: the scan is
    filed under the caller's own workspace, and the override is logged so
    an operator can see that a client asked for a workspace it does not
    have.
    """
    effective = write_workspace_id(principal, requested)
    if requested is not None and effective != requested:
        log.warning(
            "scan_workspace_override",
            requested_workspace_id=str(requested),
            effective_workspace_id=str(effective),
            principal_user_id=str(principal.user_id),
        )
    if effective is not None:
        workspace = session.get(Workspace, effective)
        if workspace is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Workspace {effective} not found.",
            )
        return workspace
    return _default_workspace(session)


def _resolve_chain(session: Session, chain_id: int) -> Chain:
    """Return the chain row for an EVM chain id."""
    return resolve_chain(session, chain_id)


def _track_asset(
    session: Session,
    workspace: Workspace,
    chain: Chain,
    address: str,
    label: str | None,
) -> TrackedAsset | None:
    """Register the address as a tracked asset, when it is one.

    A scan of the user's own contract starts a history. The findings of
    this scan and of every later one are then reachable from the
    address, which is what lets the user see that a fix moved the
    number. An address that is not a valid 20-byte address is not
    tracked: the scan still runs, it simply has nothing to attach its
    history to.
    """
    try:
        normalised = normalise_address(address)
    except InvalidAddressError:
        return None
    return upsert_asset(
        session, workspace, chain, normalised, label=label, kind=AssetKind.OWNED
    )


def _upsert_target(
    session: Session,
    workspace: Workspace,
    chain: Chain,
    address: str,
    label: str | None,
    inline_bytecode: bytes | None = None,
) -> ContractTarget:
    """Return the existing target for ``address`` or create one.

    When ``inline_bytecode`` is given, it is stored on the target so that
    the worker analyses exactly those bytes instead of contacting an RPC.
    """
    return upsert_target(session, workspace, chain, address, label, inline_bytecode)


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
    workspace = _resolve_workspace(session, principal, payload.workspace_id)
    chain = _resolve_chain(session, payload.chain_id)

    inline_bytecode: bytes | None = None
    inline_bytecode_source: str | None = None
    source_object_key: str | None = None
    provenance: str | None = None
    address = payload.contract_address or ""

    if payload.source_code is not None:
        # The developer pasted source. It is compiled here, on the server,
        # and what the compiler produced is what gets analysed -- the same
        # bytes a chain would have returned for a deployed contract.
        try:
            compiled = compile_source(
                payload.source_code,
                solc_version=payload.solc_version,
            ).compiled
        except CompilationError as exc:
            # The compiler's own message is what the developer needs to
            # read next, so it is passed through rather than summarised.
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            ) from exc

        inline_bytecode = compiled.runtime_bytecode
        inline_bytecode_source = "compiled"
        source_object_key = storage.put_bytes(
            f"pasted/{storage.sha256_hex(payload.source_code.encode('utf-8'))}.sol",
            payload.source_code.encode("utf-8"),
        )
        provenance = json.dumps(
            {
                "kind": "pasted_source",
                "contract": compiled.contract_name,
                "solc": compiled.solc_version,
                "source_name": compiled.source_name,
                "source_map": compiled.source_map,
                "warnings": list(compiled.warnings),
            }
        )
        if not address:
            # A pasted contract is not deployed anywhere, but it still
            # needs an identity: the same source filed under the same
            # address, so that its history accumulates.
            address = pasted_address(payload.source_code)
    elif payload.bytecode_hex is not None:
        inline_bytecode = bytes.fromhex(payload.bytecode_hex)
        inline_bytecode_source = "upload"
        if not address:
            # Pasted bytes are not deployed anywhere either, but they
            # still need an identity: the same bytes filed under the
            # same address, so that their history accumulates.
            address = bytecode_address(inline_bytecode)

    asset = _track_asset(session, workspace, chain, address, payload.label)

    scan, job = create_scan(
        session,
        workspace=workspace,
        chain=chain,
        address=address,
        label=payload.label,
        requested_by=principal.user_id,
        inline_bytecode=inline_bytecode,
        inline_bytecode_source=inline_bytecode_source,
        source_object_key=source_object_key,
        provenance=provenance,
        asset=asset,
        fork=payload.fork or "",
        queue_name=get_queue().name,
    )

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
    """List scans with their status, newest first.

    The list only ever contains the caller's own scans. A ``workspace_id``
    naming another workspace is refused with ``403`` rather than silently
    honoured or silently ignored.
    """
    stmt = select(Scan).order_by(Scan.created_at.desc())
    count_stmt = select(func.count()).select_from(Scan)

    workspace_filter = read_scope(principal, workspace_id)
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
    """Return a scan with its jobs, artifacts and findings.

    A scan belonging to another workspace is reported as not found.
    """
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

    if not may_read_workspace(principal, scan.workspace_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Scan {scan_id} not found."
        )

    detail = ScanDetail.model_validate(scan)
    detail.findings = [FindingRead.model_validate(finding) for finding in scan.findings]
    counts = _finding_counts(session, [scan.id]).get(scan.id, {})
    detail.finding_counts = counts
    detail.total_findings = sum(counts.values())

    # The correspondence proof is attached explicitly: it is a first-class
    # evidence object, not a column on the scan row.
    proof = session.scalars(
        select(CorrespondenceProof)
        .where(CorrespondenceProof.scan_id == scan.id)
        .order_by(CorrespondenceProof.created_at.desc())
    ).first()
    if proof is not None:
        detail.correspondence = CorrespondenceProofRead.model_validate(proof)
    return detail


@router.get(
    "/{scan_id}/source",
    response_model=ScanSourceRead,
    summary="Get the source that was analysed",
)
def get_scan_source(
    scan_id: uuid.UUID,
    session: SessionDep,
    principal: CurrentPrincipal,
) -> ScanSourceRead:
    """Return the source that was analysed, when the scan stored one.

    A scan made from runtime bytecode alone has no source to show, and
    this says so in words rather than returning an empty file list that
    reads like "there was nothing there". The findings of such a scan
    still stand: they are properties of the deployed code.
    """
    scan = session.scalars(select(Scan).where(Scan.id == scan_id)).one_or_none()
    if scan is None or not may_read_workspace(principal, scan.workspace_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Scan {scan_id} not found."
        )

    artifact = session.scalars(
        select(ScanArtifact)
        .where(ScanArtifact.scan_id == scan.id, ScanArtifact.kind == "source")
        .order_by(ScanArtifact.created_at.desc())
    ).first()
    if artifact is None:
        return ScanSourceRead(
            available=False,
            reason=(
                "This scan was analysed from runtime bytecode alone, so there is no "
                "source to show."
            ),
        )

    try:
        raw = storage.get_bytes(artifact.object_key)
        payload = json.loads(raw.decode("utf-8"))
    except (storage.ObjectStorageError, UnicodeDecodeError, ValueError) as exc:
        log.warning(
            "scan_source_unreadable", scan_id=str(scan.id), error=str(exc)
        )
        return ScanSourceRead(
            available=False,
            reason="The stored source could not be read back.",
        )

    if not isinstance(payload, dict):
        return ScanSourceRead(
            available=False,
            reason="The stored source was not in the expected shape.",
        )

    files: list[SourceFileRead] = []
    for entry in payload.get("files") or []:
        if not isinstance(entry, dict):
            continue
        content = entry.get("content")
        if not isinstance(content, str):
            continue
        path = entry.get("path") or entry.get("name") or entry.get("file")
        files.append(
            SourceFileRead(
                path=path if isinstance(path, str) else None,
                content=content,
            )
        )

    if not files:
        return ScanSourceRead(
            available=False,
            reason="The stored source carried no file content.",
        )

    def _text(value: object) -> str | None:
        return value if isinstance(value, str) else None

    verified = payload.get("verified")
    return ScanSourceRead(
        available=True,
        language=_text(payload.get("language")),
        compiler_version=_text(payload.get("compilerVersion")),
        verified=verified if isinstance(verified, bool) else None,
        source_uri=_text(payload.get("sourceUri")),
        files=files,
    )


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
    list lives at ``GET /api/v1/findings``. A scan belonging to another
    workspace is reported as not found.
    """
    scan = session.get(Scan, scan_id)
    if scan is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Scan {scan_id} not found."
        )

    if not may_read_workspace(principal, scan.workspace_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Scan {scan_id} not found."
        )

    stmt = select(Finding).where(Finding.scan_id == scan_id).order_by(Finding.created_at.desc())
    count_stmt = select(func.count()).select_from(Finding).where(Finding.scan_id == scan_id)

    total = session.scalar(count_stmt) or 0
    rows = session.scalars(stmt.offset(offset).limit(limit)).all()
    return FindingListResponse(
        items=[FindingRead.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


def _get_scan_for_principal(
    session: Session,
    principal: CurrentPrincipal,
    scan_id: uuid.UUID,
) -> Scan:
    """Return a scan the caller is allowed to see, or raise 404.

    A scan belonging to another workspace is reported as *not found* rather
    than as forbidden, so the endpoint does not confirm that the id exists.
    """
    scan = session.get(Scan, scan_id)
    if scan is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Scan {scan_id} not found."
        )
    if not may_read_workspace(principal, scan.workspace_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Scan {scan_id} not found."
        )
    return scan


@router.post(
    "/{scan_id}/mythril",
    response_model=MythrilRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Queue an on-demand Mythril deep analysis",
)
def trigger_mythril(
    scan_id: uuid.UUID,
    session: SessionDep,
    principal: CurrentPrincipal,
) -> MythrilRunResponse:
    """Queue an on-demand Mythril deep analysis for one scan.

    Mythril is manual-only. Nothing on this path starts a symbolic
    execution automatically, and the response says only that the work was
    *queued*: the verdict does not exist yet. A run that later produces no
    verdict is recorded as "no verdict" and never as a clean contract.
    """
    scan = _get_scan_for_principal(session, principal, scan_id)

    job = ScanJob(
        scan_id=scan.id,
        job_type=ScanJobType.MYTHRIL,
        queue_name=get_mythril_queue().name,
        status=ScanJobStatus.QUEUED,
        attempt=0,
    )
    session.add(job)
    session.flush()

    try:
        rq_job_id = enqueue_mythril(scan.id, job.id)
    except Exception as exc:  # noqa: BLE001 - queue failure must be reported, not crash
        log.error("mythril_enqueue_failed", scan_id=str(scan.id), error=str(exc))
        job.status = ScanJobStatus.FAILED
        session.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The job queue is unavailable. Please retry later.",
        ) from exc

    job.rq_job_id = rq_job_id
    session.commit()

    return MythrilRunResponse(
        scan_id=scan.id,
        job_id=job.id,
        status="queued",
        queue_name=job.queue_name,
        message=(
            "Mythril deep analysis queued. It runs out of process on its own "
            "queue and will not change this scan until it completes."
        ),
    )


@router.post(
    "/{scan_id}/correspondence",
    response_model=CorrespondenceRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Queue an on-demand source-to-bytecode correspondence proof",
)
def trigger_correspondence(
    scan_id: uuid.UUID,
    session: SessionDep,
    principal: CurrentPrincipal,
) -> CorrespondenceRunResponse:
    """Queue an on-demand correspondence proof for one scan.

    The proof recompiles the contract's verified source and compares the
    result with the deployed runtime, so it is a compiler run rather than a
    bytecode scan. It is therefore manual-only, and it runs on its own
    queue with its own budget.

    The response says only that the work was *queued*. No source line may be
    claimed until a proof with the ``established`` status exists.
    """
    scan = _get_scan_for_principal(session, principal, scan_id)

    job = ScanJob(
        scan_id=scan.id,
        job_type=ScanJobType.CORRESPONDENCE,
        queue_name=get_correspondence_queue().name,
        status=ScanJobStatus.QUEUED,
        attempt=0,
    )
    session.add(job)
    session.flush()

    try:
        rq_job_id = enqueue_correspondence(scan.id, job.id)
    except Exception as exc:  # noqa: BLE001 - queue failure must be reported, not crash
        log.error("correspondence_enqueue_failed", scan_id=str(scan.id), error=str(exc))
        job.status = ScanJobStatus.FAILED
        session.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The job queue is unavailable. Please retry later.",
        ) from exc

    job.rq_job_id = rq_job_id
    session.commit()

    return CorrespondenceRunResponse(
        scan_id=scan.id,
        job_id=job.id,
        status="queued",
        queue_name=job.queue_name,
        message=(
            "Correspondence proof queued. It recompiles the verified source "
            "and compares it with the deployed runtime; no source line may be "
            "claimed until a proof with the 'established' status exists."
        ),
    )


@router.get(
    "/{scan_id}/correspondence",
    response_model=CorrespondenceProofRead,
    summary="Get the source-to-bytecode correspondence proof",
)
def get_correspondence(
    scan_id: uuid.UUID,
    session: SessionDep,
    principal: CurrentPrincipal,
) -> CorrespondenceProofRead:
    """Return the stored correspondence proof for one scan.

    A proof is the only thing that licenses the product to print an exact
    source path and line against a finding. The endpoint distinguishes
    ``mismatch`` (the source genuinely does not describe the deployed
    contract) from ``unavailable`` (the check could not be performed), and
    a missing proof is a 404 - never an implied mismatch.
    """
    scan = _get_scan_for_principal(session, principal, scan_id)
    proof = session.scalars(
        select(CorrespondenceProof)
        .where(CorrespondenceProof.scan_id == scan.id)
        .order_by(CorrespondenceProof.created_at.desc())
    ).first()
    if proof is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "No correspondence proof has been recorded for this scan. "
                "The absence of a proof is not evidence of a mismatch."
            ),
        )
    return CorrespondenceProofRead.model_validate(proof)


def _report_engine_rows(
    scan: Scan,
    findings: list[Finding],
) -> list[dict[str, Any]]:
    """Describe which engines ran on a scan, and which produced no verdict.

    Every engine is listed, including the ones that did not run. A report
    that silently omits the source engine would be indistinguishable from
    a report where the source engine found nothing.
    """
    counts: dict[str, int] = {}
    for finding in findings:
        counts[finding.source] = counts.get(finding.source, 0) + 1

    return [
        {
            "name": "bytecode_rules",
            "ran": True,
            "finding_count": counts.get("rule", 0),
            "detail": "Licence-clean bytecode engine; always part of a scan.",
        },
        {
            "name": "source_audit",
            "ran": bool(scan.source_audited),
            "finding_count": counts.get("slither", 0),
            "detail": scan.source_audit_skipped
            or (
                "Source engine ran over verified source."
                if scan.source_audited
                else "No recorded outcome."
            ),
        },
        {
            "name": "mythril",
            "ran": bool(scan.mythril_ran),
            "finding_count": counts.get("mythril", 0),
            "detail": scan.mythril_skipped
            or (
                "Mythril produced a verdict for this scan."
                if scan.mythril_ran
                else "Mythril did not run for this scan."
            ),
        },
        {
            "name": "ml_model",
            "ran": bool(scan.model_version),
            "finding_count": counts.get("ml", 0),
            "detail": (
                f"Model {scan.model_version}."
                if scan.model_version
                else "No model was applied to this scan."
            ),
        },
    ]


#: The artefact kind under which a rendered report is stored. The report
#: is a first-class artefact of the scan: it has a location, a size and a
#: digest, exactly like the bytecode and the disassembly.
REPORT_ARTIFACT_KIND = "report"


def _model_manifest_reference() -> dict[str, str] | None:
    """Return the reference to the installed model's manifest, if any.

    A manifest that cannot be read is not cited. The report then shows
    the manifest as unavailable, which is true; it never shows a
    manifest it could not verify.
    """
    try:
        manifest = read_model_manifest()
    except ModelManifestError:
        return None
    if manifest is None:
        return None
    return manifest.as_reference()


def _store_report_artifact(
    session: Session,
    scan: Scan,
    pdf_bytes: bytes,
    digest: str,
) -> str:
    """Store the rendered report as an artefact of the scan.

    The object key is deterministic, so rendering the same evidence twice
    stores the same bytes at the same place rather than accumulating
    copies. The artefact row is replaced rather than appended, so the
    registry holds one report per scan.

    Returns:
        The artefact's object key, or an empty string when the artefact
        store could not be written. A failed write does not stop the
        download: the report is still the correct document, it simply
        could not be filed, and that is logged rather than hidden.
    """
    key = f"scans/{scan.id}/report.pdf"
    try:
        storage.put_bytes(key, pdf_bytes)
    except storage.ObjectStorageError as exc:
        log.warning("report_artifact_not_stored", scan_id=str(scan.id), error=str(exc))
        return ""

    session.execute(
        delete(ScanArtifact).where(
            ScanArtifact.scan_id == scan.id,
            ScanArtifact.kind == REPORT_ARTIFACT_KIND,
        )
    )
    session.add(
        ScanArtifact(
            scan_id=scan.id,
            kind=REPORT_ARTIFACT_KIND,
            content_type="application/pdf",
            object_key=key,
            byte_size=len(pdf_bytes),
            sha256=digest,
        )
    )
    session.commit()
    return key


@router.get(
    "/{scan_id}/report.pdf",
    summary="Download the deterministic PDF report",
    response_class=Response,
    responses={
        200: {"content": {"application/pdf": {}}, "description": "The PDF report."},
        404: {"description": "The scan does not exist."},
        503: {"description": "The PDF renderer is unavailable."},
    },
)
def download_report(
    scan_id: uuid.UUID,
    session: SessionDep,
    principal: CurrentPrincipal,
) -> Response:
    """Render the scan's PDF report.

    The report is deterministic: the same evidence always renders the same
    document, byte for byte. The digest of the rendered document is returned
    in ``X-Report-SHA256`` so a recipient can verify it.
    """
    scan = _get_scan_for_principal(session, principal, scan_id)

    findings = session.scalars(select(Finding).where(Finding.scan_id == scan.id)).all()
    artifacts = session.scalars(select(ScanArtifact).where(ScanArtifact.scan_id == scan.id)).all()
    proof = session.scalars(
        select(CorrespondenceProof)
        .where(CorrespondenceProof.scan_id == scan.id)
        .order_by(CorrespondenceProof.created_at.desc())
    ).first()

    target = scan.target
    chain_id = None
    contract_address = ""
    if target is not None:
        contract_address = target.address or ""
        chain_id = getattr(target.chain, "chain_id", None)

    correspondence_payload = None
    if proof is not None:
        correspondence_payload = {
            "status": proof.status.value if hasattr(proof.status, "value") else str(proof.status),
            "compiler": proof.compiler_version or "",
            "settings": proof.source_path or "",
            "statement": proof.skipped or "",
        }

    model_manifest_reference = _model_manifest_reference()

    data = build_report_data(
        limitations=scan.limitations,
        coverage=scan.coverage,
        model_scores=scan.model_scores,
        scan_id=str(scan.id),
        contract_address=contract_address,
        chain_id=chain_id,
        fork=scan.fork,
        fork_source=scan.fork_source,
        fork_conflict=scan.fork_conflict,
        scan_status=scan.status.value,
        findings=[
            {
                "detector_id": finding.detector_id,
                "category": finding.category,
                "title": finding.title,
                "description": finding.description,
                "severity": finding.severity.value
                if hasattr(finding.severity, "value")
                else str(finding.severity),
                "confidence": finding.confidence,
                "source": finding.source,
                "evidence": finding.evidence_json,
                "limitations": finding.limitations,
                "status": finding.status.value
                if hasattr(finding.status, "value")
                else str(finding.status),
            }
            for finding in findings
        ],
        artifacts=[
            {
                "kind": artifact.kind,
                "object_key": artifact.object_key,
                "content_type": artifact.content_type,
                "byte_size": artifact.byte_size,
                "sha256": artifact.sha256 or "",
            }
            # The report itself is deliberately excluded: a document that
            # contained its own digest could never render to the same bytes
            # twice, and the report has to be reproducible.
            for artifact in artifacts
            if artifact.kind != REPORT_ARTIFACT_KIND
        ],
        model_manifest=model_manifest_reference,
        tool_versions={
            "parser": scan.parser_version or "",
            "ruleset": scan.ruleset_version or "",
            "model": scan.model_version or "",
        },
        correspondence=correspondence_payload,
        source_audited=scan.source_audited,
        source_audit_skipped=scan.source_audit_skipped,
        engines=_report_engine_rows(scan, list(findings)),
    )

    try:
        pdf_bytes = render_report(data)
    except ReportLabUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The PDF renderer is not available in this environment.",
        ) from exc

    digest = report_sha256(pdf_bytes)
    artifact_key = _store_report_artifact(session, scan, pdf_bytes, digest)

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (f'attachment; filename="cyberstratum-{scan.id}.pdf"'),
            "X-Report-SHA256": digest,
            "X-Report-Artifact": artifact_key,
            "Cache-Control": "no-store",
        },
    )


__all__ = ["router"]
