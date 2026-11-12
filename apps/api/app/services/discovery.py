"""The continuous discovery feed.

This is the "Watchdog" half of the merged product: a sweep that finds newly
verified contracts across many chains and hands them to the analysis
pipeline. It is deliberately separate from the scan pipeline -- a discovery
cycle reads many chains and analyses nothing, while a scan analyses one
contract and reads nothing.

Four properties matter more than anything else here, because a feed that
gets them wrong is worse than no feed:

1. **A failing chain costs that chain, not the cycle.** Polygon is
   unreachable today. The other 57 chains must still be swept.
2. **The cursor advances before the analysis starts.** A crash then costs at
   most one contract, rather than re-fetching the same contract on every
   cycle forever.
3. **Discovery is idempotent.** The same contract found twice is one row,
   and the second sighting only records that it was re-verified.
4. **Discovered contracts do not land in a tenant's list.** They land in
   the discovery workspace, and a customer promotes one deliberately.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.discovery import DiscoveryRun, FeedCursor
from app.db.models.identity import Chain, ContractTarget, Workspace
from app.db.models.scans import Scan
from app.services.blockscout import (
    BlockscoutClient,
    BlockscoutUnavailableError,
    DiscoveredContract,
)
from app.services.chains import SUPPORTED_CHAINS
from app.services.promotion import (
    DEFAULT_MAX_SCANS_PER_CYCLE,
    promote_contracts,
)

log = logging.getLogger("cyberstratum.discovery")

#: The slug of the workspace that holds discovered contracts.
DISCOVERY_WORKSPACE_SLUG = "discovery"

#: How many chains one cycle sweeps by default.
DEFAULT_BATCH_SIZE = 10

#: How many pages of the feed one chain reads in a cycle by default.
#:
#: One page is the newest contracts. Reading more pages walks into the
#: history of the chain, which is how the contracts that were verified
#: before this product started watching are found.
DEFAULT_PAGES_PER_CHAIN = 1


@dataclass
class DiscoveryOutcome:
    """What one discovery cycle achieved.

    Attributes:
        run_id: The persisted run's id.
        chains_covered: How many chains answered.
        chains_failed: How many chains could not be read.
        contracts_found: How many contracts the routes returned.
        contracts_new: How many were not in the workspace before.
        contracts_updated: How many were re-verified since the last cycle.
        scans_queued: How many scans the cycle queued for the contracts
            it found.
        failures: The per-chain failures, as ``{chain_id: reason}``.
        errors: The same failures, in the shape stored on the run.
    """

    run_id: uuid.UUID
    chains_covered: int = 0
    chains_failed: int = 0
    contracts_found: int = 0
    contracts_new: int = 0
    contracts_updated: int = 0
    scans_queued: int = 0
    failures: dict[int, str] = field(default_factory=dict)

    @property
    def errors(self) -> list[dict[str, object]]:
        """The failures, in the shape stored on the run row."""
        return [
            {"chainId": chain_id, "reason": reason}
            for chain_id, reason in sorted(self.failures.items())
        ]

    @property
    def status(self) -> str:
        """The run's status: complete, partial, or failed."""
        if self.chains_covered == 0 and self.chains_failed:
            return "failed"
        if self.chains_failed:
            return "partial"
        return "completed"


def get_or_create_discovery_workspace(session: Session) -> Workspace:
    """The workspace that holds discovered contracts.

    It is created on first use so the feed works on a fresh database with no
    manual setup.

    Args:
        session: The database session.

    Returns:
        The discovery workspace.
    """
    workspace = session.execute(
        select(Workspace).where(Workspace.slug == DISCOVERY_WORKSPACE_SLUG)
    ).scalar_one_or_none()
    if workspace is not None:
        return workspace

    workspace = Workspace(
        name="Discovery",
        slug=DISCOVERY_WORKSPACE_SLUG,
        kind="discovery",
    )
    session.add(workspace)
    session.flush()
    log.info("created the discovery workspace")
    return workspace


def _chain_row(session: Session, chain_id: int) -> Chain | None:
    """The database row for a chain, if it is registered."""
    return session.execute(
        select(Chain).where(Chain.chain_id == chain_id)
    ).scalar_one_or_none()


def _ensure_chain(session: Session, chain_id: int, name: str) -> Chain:
    """The database row for a chain, created if it is not registered.

    The chain registry in :mod:`app.services.chains` is the source of truth
    for which chains exist. The database only holds the ones this
    installation has actually seen.
    """
    row = _chain_row(session, chain_id)
    if row is not None:
        return row
    row = Chain(name=name, chain_id=chain_id, environment="mainnet")
    session.add(row)
    session.flush()
    return row


def select_batch(
    session: Session,
    workspace_id: uuid.UUID,
    chain_ids: Sequence[int],
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> list[int]:
    """Choose which chains this cycle sweeps.

    The chains whose cursors were touched longest ago go first, and chains
    that have never been seen go before any that have. That gives a
    round-robin sweep across far more chains than one cycle can cover,
    without needing a separate rotation counter.

    Args:
        session: The database session.
        workspace_id: The discovery workspace.
        chain_ids: The chains that are candidates.
        batch_size: How many chains to take.

    Returns:
        The chain ids to sweep, in the order to sweep them.
    """
    if not chain_ids:
        return []

    # The cursor stores the chain's internal id, while the batch works in
    # EIP-155 chain ids, so the two are joined rather than compared.
    cursors = dict(
        session.execute(
            select(Chain.chain_id, FeedCursor.updated_at)
            .join(Chain, Chain.id == FeedCursor.chain_id)
            .where(FeedCursor.workspace_id == workspace_id)
        ).all()
    )

    def sort_key(chain_id: int) -> tuple[int, float]:
        updated = cursors.get(chain_id)
        if updated is None:
            # Never seen: first.
            return (0, 0.0)
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=UTC)
        return (1, updated.timestamp())

    ordered = sorted(chain_ids, key=sort_key)
    return ordered[:batch_size]


def _cursor_for(
    session: Session, chain_row: Chain, workspace_id: uuid.UUID
) -> FeedCursor:
    """The cursor for one chain, created if it does not exist."""
    cursor = session.execute(
        select(FeedCursor).where(
            FeedCursor.chain_id == chain_row.id,
            FeedCursor.workspace_id == workspace_id,
        )
    ).scalar_one_or_none()
    if cursor is not None:
        return cursor
    cursor = FeedCursor(chain_id=chain_row.id, workspace_id=workspace_id)
    session.add(cursor)
    session.flush()
    return cursor


def _unscanned_targets(
    session: Session, workspace_id: uuid.UUID, chain_row: Chain, limit: int = 200
) -> list[ContractTarget]:
    """The contracts of this workspace and chain that have never been scanned.

    A contract the promotion cap left alone must be offered again
    later, or the cap would strand it for ever: the feed offers what
    it touched, and a contract that was touched once and capped once
    would never be offered again.
    """
    scanned = select(Scan.target_id).where(Scan.target_id.is_not(None))
    stmt = (
        select(ContractTarget)
        .where(
            ContractTarget.workspace_id == workspace_id,
            ContractTarget.chain_id == chain_row.id,
            ContractTarget.id.not_in(scanned),
        )
        .limit(limit)
    )
    return list(session.execute(stmt).scalars().all())


def _verification_state(contract: DiscoveredContract) -> str:
    """The verification state of a discovered contract."""
    if contract.is_verified is True:
        return "verified"
    if contract.is_verified is False:
        return "unverified"
    return "unknown"


def _parse_verified_at(contract: DiscoveredContract) -> datetime | None:
    """The verification timestamp, when the route reported a usable one."""
    if not contract.verified_at:
        return None
    try:
        parsed = datetime.fromisoformat(contract.verified_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _label_for(contract: DiscoveredContract) -> str:
    """A human-readable label for a discovered contract."""
    if contract.name:
        return contract.name
    return f"{contract.chain_id}:{contract.address}"


def persist_contracts(
    session: Session,
    workspace: Workspace,
    chain_row: Chain,
    run: DiscoveryRun,
    contracts: Iterable[DiscoveredContract],
) -> tuple[int, int]:
    """Store discovered contracts, idempotently.

    A contract already in the workspace is not duplicated. If it has been
    re-verified since the last sighting, the stored verification timestamp
    is updated and the contract is counted as updated -- which is the signal
    that it is worth re-analysing, because the source may have changed.

    Args:
        session: The database session.
        workspace: The discovery workspace.
        chain_row: The chain the contracts live on.
        run: The run that found them.
        contracts: The contracts the route returned.

    Returns:
        How many were new, and how many were updated.
    """
    new_count = 0
    updated_count = 0

    for contract in contracts:
        address = contract.address.lower()
        existing = session.execute(
            select(ContractTarget).where(
                ContractTarget.workspace_id == workspace.id,
                ContractTarget.chain_id == chain_row.id,
                ContractTarget.address == address,
            )
        ).scalar_one_or_none()

        verified_at = _parse_verified_at(contract)
        state = _verification_state(contract)

        if existing is None:
            session.add(
                ContractTarget(
                    workspace_id=workspace.id,
                    chain_id=chain_row.id,
                    address=address,
                    label=_label_for(contract),
                    source_uri=contract.source_uri,
                    provenance=(
                        f"Discovered via the {contract.route} route "
                        f"in run {run.id}."
                    ),
                    authorization_status="unknown",
                    discovery_run_id=run.id,
                    discovery_route=contract.route,
                    verification_state=state,
                    verified_at=verified_at,
                )
            )
            new_count += 1
            continue

        # Already known. Re-verification is the interesting event.
        if verified_at is not None and (
            existing.verified_at is None or verified_at > existing.verified_at
        ):
            existing.verified_at = verified_at
            existing.verification_state = state
            existing.discovery_run_id = run.id
            existing.discovery_route = contract.route
            updated_count += 1
        elif existing.verification_state is None:
            existing.verification_state = state

    session.flush()
    return new_count, updated_count


class DiscoveryService:
    """Runs discovery cycles.

    Attributes:
        session: The database session.
        client: The Blockscout client used to read the chains.
    """

    def __init__(self, session: Session, client: BlockscoutClient) -> None:
        self.session = session
        self.client = client

    async def run_cycle(
        self,
        chain_ids: Sequence[int] | None = None,
        workspace: Workspace | None = None,
        batch_size: int = DEFAULT_BATCH_SIZE,
        pages: int = DEFAULT_PAGES_PER_CHAIN,
    ) -> DiscoveryOutcome:
        """Run one discovery cycle.

        Args:
            chain_ids: The chains to consider. Defaults to every chain in
                the registry.
            workspace: The discovery workspace. Created on first use.
            batch_size: How many chains to sweep in this cycle.
            pages: How many pages of the feed each chain reads. More
                than one page walks into the history of the chain.

        Returns:
            What the cycle achieved, including the per-chain failures.
        """
        target_workspace = workspace or get_or_create_discovery_workspace(self.session)

        candidates = (
            list(chain_ids)
            if chain_ids is not None
            else [chain.chain_id for chain in SUPPORTED_CHAINS]
        )
        batch = select_batch(
            self.session, target_workspace.id, candidates, batch_size
        )

        run = DiscoveryRun(workspace_id=target_workspace.id, status="running")
        self.session.add(run)
        self.session.flush()

        outcome = DiscoveryOutcome(run_id=run.id)
        # The promotion budget belongs to the cycle, not to each chain:
        # a cycle queues at most this many scans in total.
        budget = DEFAULT_MAX_SCANS_PER_CYCLE

        for chain_id in batch:
            chain = next(
                (c for c in SUPPORTED_CHAINS if c.chain_id == chain_id), None
            )
            name = chain.name if chain is not None else f"chain-{chain_id}"
            try:
                found, new, updated, queued = await self._sweep_chain(
                    chain_id, name, target_workspace, run, pages=pages, limit=budget
                )
                budget = max(0, budget - queued)
            except BlockscoutUnavailableError as exc:
                log.warning("discovery: chain %s unavailable: %s", chain_id, exc)
                outcome.chains_failed += 1
                outcome.failures[chain_id] = str(exc)
                continue
            except Exception as exc:  # noqa: BLE001 - one chain must not kill the cycle
                log.exception("discovery: chain %s failed", chain_id)
                outcome.chains_failed += 1
                outcome.failures[chain_id] = f"{type(exc).__name__}: {exc}"[:300]
                continue

            outcome.chains_covered += 1
            outcome.contracts_found += found
            outcome.contracts_new += new
            outcome.contracts_updated += updated
            outcome.scans_queued += queued

        run.status = outcome.status
        run.finished_at = datetime.now(UTC)
        run.chains_covered = outcome.chains_covered
        run.chains_failed = outcome.chains_failed
        run.contracts_found = outcome.contracts_found
        run.contracts_new = outcome.contracts_new
        run.contracts_updated = outcome.contracts_updated
        run.scans_queued = outcome.scans_queued
        run.errors = outcome.errors
        self.session.flush()

        log.info(
            "discovery cycle %s: %d chains covered, %d failed, %d contracts "
            "(%d new, %d updated), %d scans queued",
            run.id,
            outcome.chains_covered,
            outcome.chains_failed,
            outcome.contracts_found,
            outcome.contracts_new,
            outcome.contracts_updated,
            outcome.scans_queued,
        )
        return outcome

    async def _sweep_chain(
        self,
        chain_id: int,
        chain_name: str,
        workspace: Workspace,
        run: DiscoveryRun,
        *,
        pages: int = DEFAULT_PAGES_PER_CHAIN,
        limit: int = DEFAULT_MAX_SCANS_PER_CYCLE,
    ) -> tuple[int, int, int, int]:
        """Sweep one chain.

        The cursor is advanced *before* the contracts are analysed, so a
        failure downstream cannot cause the same contract to be fetched
        again on every cycle.

        The walk continues from the page the cursor reached last time,
        so the pages behind the newest one -- the history of the chain
        -- are read as well. When the walk runs off the end of the feed
        it returns to page one, which is where the next new contract
        will appear.

        Returns:
            How many contracts were found, how many were new, how many
            were updated, and how many scans were queued for them.
        """
        chain_row = _ensure_chain(self.session, chain_id, chain_name)
        cursor = _cursor_for(self.session, chain_row, workspace.id)

        found = 0
        new_count = 0
        updated_count = 0
        queued = 0
        touched: list[ContractTarget] = []

        page = max(1, cursor.next_page or 1)
        for _ in range(max(1, pages)):
            contracts = await self.client.list_contracts(chain_id, page=page)
            if not contracts:
                # There is no page here: the walk has reached the end of
                # the history, and returns to the newest page.
                cursor.next_page = 1
                self.session.flush()
                break

            # The cursor moves before anything downstream can fail.
            cursor.last_address = contracts[-1].address.lower()
            cursor.contracts_seen += len(contracts)
            newest: datetime | None = None
            for contract in contracts:
                seen = _parse_verified_at(contract)
                if seen is not None and (newest is None or seen > newest):
                    newest = seen
            if newest is not None and (
                cursor.last_verified_at is None or newest > cursor.last_verified_at
            ):
                cursor.last_verified_at = newest
            cursor.next_page = page + 1
            page += 1
            self.session.flush()

            new, updated = persist_contracts(
                self.session, workspace, chain_row, run, contracts
            )
            found += len(contracts)
            new_count += new
            updated_count += updated

            touched.extend(
                self.session.execute(
                    select(ContractTarget).where(
                        ContractTarget.workspace_id == workspace.id,
                        ContractTarget.chain_id == chain_row.id,
                        ContractTarget.discovery_run_id == run.id,
                    )
                )
                .scalars()
                .all()
            )

        # The feed's job is not complete until the contracts it found have
        # been analysed. Everything this sweep touched -- new and
        # re-verified alike -- is offered to the promotion pass, which
        # decides what has not been seen before and keeps the queue inside
        # its limits. Then everything of this chain that has never been
        # scanned is offered as well, so that a contract the cap left
        # alone is offered again rather than stranded for ever.
        offered = list(touched)
        seen_ids = {target.id for target in offered}
        for target in _unscanned_targets(self.session, workspace.id, chain_row):
            if target.id not in seen_ids:
                offered.append(target)
                seen_ids.add(target.id)

        promotion = promote_contracts(
            self.session,
            workspace,
            chain_row,
            offered,
            limit=max(0, limit - queued),
        )
        queued += promotion.queued
        if promotion.errors:
            log.warning(
                "discovery: %d contracts could not be queued for scanning",
                promotion.failed,
            )
        return (found, new_count, updated_count, queued)


__all__ = [
    "DEFAULT_BATCH_SIZE",
    "DEFAULT_PAGES_PER_CHAIN",
    "DISCOVERY_WORKSPACE_SLUG",
    "DiscoveryOutcome",
    "DiscoveryService",
    "get_or_create_discovery_workspace",
    "persist_contracts",
    "select_batch",
]
