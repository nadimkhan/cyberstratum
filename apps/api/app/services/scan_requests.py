"""Creating a scan and the job that runs it.

The API and the autonomous discovery path both create scans. They have to
create them the same way: a scan that only one path can produce would
give the product two different notions of what a scan is, and the tracked
history would be half empty.

This module owns the shared parts:

* the contract target (one row per workspace, chain and address),
* the scan row,
* the queue job that runs it.

Queueing itself stays with the caller, because the API reports a queue
outage as a ``503`` to the developer while discovery records it against
the run and carries on.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.enums import ScanJobStatus, ScanJobType, ScanStatus
from app.db.models.assets import TrackedAsset
from app.db.models.identity import Chain, ContractTarget, Workspace
from app.db.models.scans import Scan, ScanJob


def resolve_chain(session: Session, chain_id: int) -> Chain:
    """Return the chain row for an EVM chain id, creating it when new.

    A chain this product has not heard of is still usable: the row is
    created on demand so a scan of an unlisted chain is not refused for
    administrative reasons.
    """
    chain = session.scalars(select(Chain).where(Chain.chain_id == chain_id)).one_or_none()
    if chain is None:
        chain = Chain(name=f"Chain {chain_id}", chain_id=chain_id, environment="mainnet")
        session.add(chain)
        session.flush()
    return chain


def upsert_target(
    session: Session,
    workspace: Workspace,
    chain: Chain,
    address: str,
    label: str | None,
    inline_bytecode: bytes | None = None,
    inline_bytecode_source: str | None = None,
    source_object_key: str | None = None,
    provenance: str | None = None,
) -> ContractTarget:
    """Return the existing target for ``address`` or create one.

    When ``inline_bytecode`` is given, it is stored on the target so that
    the worker analyses exactly those bytes instead of contacting an RPC.

    ``inline_bytecode_source`` says how those bytes came to be: the
    developer pasted them, or the server compiled the developer's source
    and these are what came out. The two are not interchangeable -- a
    compiled source carries a source map, which is what lets a finding
    point at a line -- so the difference is recorded rather than assumed.

    ``source_object_key`` and ``provenance`` describe the source the
    bytes came from, when there was one.
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
            inline_bytecode_source=inline_bytecode_source,
            source_object_key=source_object_key,
            provenance=provenance,
        )
        session.add(target)
        session.flush()
    else:
        if label:
            target.label = label
        if inline_bytecode is not None:
            target.inline_bytecode = inline_bytecode
        if inline_bytecode_source is not None:
            target.inline_bytecode_source = inline_bytecode_source
        if source_object_key is not None:
            target.source_object_key = source_object_key
        if provenance is not None:
            target.provenance = provenance
        session.flush()
    return target


def create_scan(
    session: Session,
    *,
    workspace: Workspace,
    chain: Chain,
    address: str,
    label: str | None = None,
    requested_by: uuid.UUID | None = None,
    inline_bytecode: bytes | None = None,
    inline_bytecode_source: str | None = None,
    source_object_key: str | None = None,
    provenance: str | None = None,
    asset: TrackedAsset | None = None,
    fork: str = "",
    queue_name: str | None = None,
) -> tuple[Scan, ScanJob]:
    """Create a queued scan and the job that will run it.

    The scan is attached to ``asset`` when one is given. That attachment
    is what turns a one-off scan into a tracked history: without it, the
    findings of yesterday's scan are unreachable from the address.
    """
    target = upsert_target(
        session,
        workspace,
        chain,
        address,
        label,
        inline_bytecode,
        inline_bytecode_source=inline_bytecode_source,
        source_object_key=source_object_key,
        provenance=provenance,
    )

    scan = Scan(
        workspace_id=workspace.id,
        target_id=target.id,
        asset_id=asset.id if asset is not None else None,
        status=ScanStatus.QUEUED,
        requested_by=requested_by,
        fork=fork,
        bytecode_source=(
            (inline_bytecode_source or "upload") if inline_bytecode is not None else "rpc"
        ),
        queued_at=datetime.now(UTC),
    )
    session.add(scan)
    session.flush()

    job = ScanJob(
        scan_id=scan.id,
        job_type=ScanJobType.SCAN,
        status=ScanJobStatus.QUEUED,
        attempt=0,
    )
    if queue_name is not None:
        job.queue_name = queue_name
    session.add(job)
    session.flush()
    return scan, job
