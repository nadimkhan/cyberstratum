"""Discovery endpoints: run the feed, list its runs, list what it found.

These routes are the operator-facing side of the continuous discovery feed.
A discovery cycle is deliberately *not* a scan: it reads many chains and
analyses nothing, so it gets its own resource rather than being folded into
``/api/v1/scans``.

Tenant scoping
--------------

Discovery is deliberately **shared**, and that sharing is a product
decision rather than an oversight. The feed reads public chains and
publishes what it finds into a single *discovery* workspace, so every
tenant sees the same public-contract corpus. A discovered contract is
promoted into a tenant's own workspace deliberately, by that tenant.

What this means for these routes:

* Every query is scoped to the discovery workspace by construction. No
  route in this module reads or writes a tenant's own workspace, so a
  tenant principal can neither read another tenant's data nor write into
  another tenant's workspace through this module.
* The discovery workspace is shared, so the data these routes return is
  shared too: it is the same for every caller. That is intended, and it
  is why these routes are not filtered by the caller's workspace.
* The configured service key is the administrative credential and behaves
  exactly the same way here, because discovery data is not tenant data.

The tenant-facing rules (own workspace always, cross-tenant reads answer
404, a stored key without a membership is denied with 403) are defined in
:mod:`app.core.security` and apply to every other router.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.core.security import CurrentPrincipal, SessionDep
from app.db.models.discovery import DiscoveryRun, FeedCursor
from app.db.models.identity import Chain, ContractTarget, Workspace
from app.queue.connection import get_discovery_queue
from app.services.discovery import (
    DEFAULT_BATCH_SIZE,
    get_or_create_discovery_workspace,
)
from app.worker import enqueue_discovery

log = get_logger(__name__)

router = APIRouter(prefix="/api/v1/discovery", tags=["discovery"])


class DiscoveryRunRequest(BaseModel):
    """A request to run one discovery cycle.

    Attributes:
        chain_ids: The chains to consider. ``None`` means every chain in
            the registry.
        batch_size: How many chains to sweep in this cycle.
    """

    model_config = ConfigDict(extra="forbid")

    chain_ids: list[int] | None = Field(default=None)
    batch_size: int = Field(default=DEFAULT_BATCH_SIZE, ge=1, le=60)


class DiscoveryRunAccepted(BaseModel):
    """The acknowledgement of a queued discovery cycle.

    Attributes:
        id: The queued job's id.
        status: The job's status.
        status_url: Where to look for the cycle's progress.
        queue_name: The queue the job was placed on.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    status: str
    status_url: str
    queue_name: str


class DiscoveryRunRead(BaseModel):
    """One discovery cycle.

    Attributes:
        id: The run's id.
        status: ``running``, ``completed``, ``partial`` or ``failed``.
        started_at: When the cycle began.
        finished_at: When the cycle ended, when it has.
        chains_covered: How many chains answered.
        chains_failed: How many chains could not be read.
        contracts_found: How many contracts the routes returned.
        contracts_new: How many were new.
        contracts_updated: How many were re-verified.
        errors: The per-chain failures.
    """

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: uuid.UUID
    status: str
    started_at: datetime
    finished_at: datetime | None = None
    chains_covered: int
    chains_failed: int
    contracts_found: int
    contracts_new: int
    contracts_updated: int
    errors: list[dict[str, object]] | None = None


class DiscoveryRunListResponse(BaseModel):
    """A page of discovery cycles.

    Attributes:
        items: The cycles, newest first.
        total: How many cycles exist.
        limit: The page size.
        offset: The page offset.
    """

    model_config = ConfigDict(extra="forbid")

    items: list[DiscoveryRunRead]
    total: int
    limit: int
    offset: int


class DiscoveredContractRead(BaseModel):
    """A contract the feed found.

    Attributes:
        id: The target's id.
        address: The contract address.
        label: A human readable label.
        chain_id: The EIP-155 chain id.
        chain_name: The chain's name.
        verification_state: ``verified``, ``unverified`` or ``unknown``.
        verified_at: When the contract was verified.
        discovery_route: Which Blockscout route found it.
        source_uri: A link to the contract on a block explorer.
    """

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: uuid.UUID
    address: str | None = None
    label: str
    chain_id: int
    chain_name: str
    verification_state: str | None = None
    verified_at: datetime | None = None
    discovery_route: str | None = None
    source_uri: str | None = None


class DiscoveredContractListResponse(BaseModel):
    """A page of discovered contracts.

    Attributes:
        items: The contracts, newest first.
        total: How many contracts the feed has found.
        limit: The page size.
        offset: The page offset.
    """

    model_config = ConfigDict(extra="forbid")

    items: list[DiscoveredContractRead]
    total: int
    limit: int
    offset: int


def _discovery_workspace(session: Session) -> Workspace:
    """The workspace that holds discovered contracts."""
    return get_or_create_discovery_workspace(session)


@router.post(
    "/runs",
    response_model=DiscoveryRunAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Queue a discovery cycle",
)
def queue_discovery_cycle(
    payload: DiscoveryRunRequest,
    session: SessionDep,
    principal: CurrentPrincipal,
) -> DiscoveryRunAccepted:
    """Queue one discovery cycle on the discovery queue.

    The cycle runs on the worker, not in the request, because a sweep of
    many chains can take a minute and must not hold an HTTP connection
    open for that long.
    """
    # Resolve the workspace up front so the run is guaranteed to have one
    # by the time the worker picks the job up.
    _discovery_workspace(session)
    session.commit()

    try:
        rq_job_id = enqueue_discovery(batch_size=payload.batch_size, chain_ids=payload.chain_ids)
    except Exception as exc:  # noqa: BLE001 - queue failure must be reported
        log.error("discovery_enqueue_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The job queue is unavailable. Please retry later.",
        ) from exc

    return DiscoveryRunAccepted(
        id=rq_job_id,
        status="queued",
        status_url="/api/v1/discovery/runs",
        queue_name=get_discovery_queue().name,
    )


@router.get("/runs", response_model=DiscoveryRunListResponse, summary="List discovery cycles")
def list_discovery_runs(
    session: SessionDep,
    principal: CurrentPrincipal,
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> DiscoveryRunListResponse:
    """List the discovery cycles, newest first."""
    workspace = _discovery_workspace(session)
    session.flush()

    stmt = (
        select(DiscoveryRun)
        .where(DiscoveryRun.workspace_id == workspace.id)
        .order_by(DiscoveryRun.started_at.desc())
    )
    count_stmt = (
        select(func.count())
        .select_from(DiscoveryRun)
        .where(DiscoveryRun.workspace_id == workspace.id)
    )

    total = session.scalar(count_stmt) or 0
    rows = session.scalars(stmt.offset(offset).limit(limit)).all()
    return DiscoveryRunListResponse(
        items=[DiscoveryRunRead.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/contracts",
    response_model=DiscoveredContractListResponse,
    summary="List the contracts the feed has found",
)
def list_discovered_contracts(
    session: SessionDep,
    principal: CurrentPrincipal,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    chain_id: int | None = Query(default=None),
    verified_only: bool = Query(default=False),
) -> DiscoveredContractListResponse:
    """List the contracts the feed has found, newest first.

    These live in the discovery workspace, so they never show up in a
    tenant's own contract list until they are promoted.
    """
    workspace = _discovery_workspace(session)
    session.flush()

    stmt = (
        select(ContractTarget, Chain.chain_id, Chain.name)
        .join(Chain, Chain.id == ContractTarget.chain_id)
        .where(ContractTarget.workspace_id == workspace.id)
        .order_by(ContractTarget.created_at.desc())
    )
    count_stmt = (
        select(func.count())
        .select_from(ContractTarget)
        .where(ContractTarget.workspace_id == workspace.id)
    )

    if chain_id is not None:
        stmt = stmt.where(Chain.chain_id == chain_id)
        count_stmt = count_stmt.join(Chain, Chain.id == ContractTarget.chain_id).where(
            Chain.chain_id == chain_id
        )
    if verified_only:
        stmt = stmt.where(ContractTarget.verification_state == "verified")
        count_stmt = count_stmt.where(ContractTarget.verification_state == "verified")

    total = session.scalar(count_stmt) or 0
    rows = session.execute(stmt.offset(offset).limit(limit)).all()

    items = [
        DiscoveredContractRead(
            id=target.id,
            address=target.address,
            label=target.label,
            chain_id=eip155,
            chain_name=chain_name,
            verification_state=target.verification_state,
            verified_at=target.verified_at,
            discovery_route=target.discovery_route,
            source_uri=target.source_uri,
        )
        for target, eip155, chain_name in rows
    ]
    return DiscoveredContractListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get(
    "/cursors",
    response_model=list[dict[str, object]],
    summary="Show how far the feed has read on each chain",
)
def list_feed_cursors(
    session: SessionDep,
    principal: CurrentPrincipal,
) -> list[dict[str, object]]:
    """Return the per-chain feed cursors."""
    workspace = _discovery_workspace(session)
    session.flush()

    rows = session.execute(
        select(FeedCursor, Chain.chain_id, Chain.name)
        .join(Chain, Chain.id == FeedCursor.chain_id)
        .where(FeedCursor.workspace_id == workspace.id)
        .order_by(Chain.chain_id)
    ).all()

    return [
        {
            "chain_id": eip155,
            "chain_name": chain_name,
            "last_address": cursor.last_address,
            "contracts_seen": cursor.contracts_seen,
            "next_page": cursor.next_page,
            "last_verified_at": cursor.last_verified_at,
            "updated_at": cursor.updated_at,
        }
        for cursor, eip155, chain_name in rows
    ]


__all__ = [
    "DiscoveryRunAccepted",
    "DiscoveryRunListResponse",
    "DiscoveryRunRead",
    "DiscoveryRunRequest",
    "DiscoveredContractListResponse",
    "DiscoveredContractRead",
    "router",
]
