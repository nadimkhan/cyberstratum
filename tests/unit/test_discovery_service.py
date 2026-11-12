"""Tests for the continuous discovery feed.

The feed is tested against a stub Blockscout client, so the suite never
touches the network. The properties under test are the ones that make the
feed safe to run unattended:

- A chain that fails costs that chain, not the cycle.
- The cursor advances before the analysis.
- Discovery is idempotent.
- Discovered contracts land in the discovery workspace, not a tenant's.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.enums import ScanStatus
from app.db.models.discovery import DiscoveryRun, FeedCursor
from app.db.models.identity import Chain, ContractTarget, Workspace
from app.db.models.scans import Scan
from app.services.blockscout import (
    BlockscoutUnavailableError,
    DiscoveredContract,
)
from app.services.discovery import (
    DISCOVERY_WORKSPACE_SLUG,
    DiscoveryService,
    get_or_create_discovery_workspace,
    persist_contracts,
    select_batch,
)
from app.services.promotion import promote_contracts


class StubClient:
    """A Blockscout client that answers from a canned map."""

    def __init__(
        self,
        contracts: dict[int, list[DiscoveredContract]] | None = None,
        failures: dict[int, Exception] | None = None,
        pages: dict[int, dict[int, list[DiscoveredContract]]] | None = None,
    ) -> None:
        self.contracts = contracts or {}
        self.failures = failures or {}
        self.pages = pages or {}
        self.calls: list[int] = []
        self.pages_requested: list[tuple[int, int]] = []

    async def list_contracts(
        self, chain_id: int, page: int = 1, **_: Any
    ) -> list[DiscoveredContract]:
        """Return the canned contracts, or raise the canned failure."""
        self.calls.append(chain_id)
        self.pages_requested.append((chain_id, page))
        if chain_id in self.failures:
            raise self.failures[chain_id]
        if chain_id in self.pages:
            return list(self.pages[chain_id].get(page, []))
        return list(self.contracts.get(chain_id, []))


def make_contract(
    chain_id: int = 1,
    address: str = "0x" + "aa" * 20,
    *,
    name: str | None = "Token",
    verified: bool = True,
    verified_at: str | None = "2026-01-01T00:00:00Z",
    route: str = "instance",
) -> DiscoveredContract:
    """Build a discovered contract."""
    return DiscoveredContract(
        chain_id=chain_id,
        address=address,
        name=name,
        is_verified=verified,
        verified_at=verified_at,
        source_uri=f"https://example.test/address/{address}",
        route=route,
    )


def test_discovery_workspace_is_created_once(db_session: Session) -> None:
    """The discovery workspace is created on first use, then reused."""
    first = get_or_create_discovery_workspace(db_session)
    second = get_or_create_discovery_workspace(db_session)

    assert first.id == second.id
    assert first.kind == "discovery"
    assert first.slug == DISCOVERY_WORKSPACE_SLUG


def test_contracts_land_in_the_discovery_workspace(db_session: Session) -> None:
    """Discovered contracts do not appear in a tenant's contract list."""
    tenant = Workspace(name="Acme", slug=f"tenant-{uuid.uuid4().hex}")
    db_session.add(tenant)
    db_session.flush()

    space = get_or_create_discovery_workspace(db_session)
    chain_row = Chain(name="Ethereum", chain_id=1, environment="mainnet")
    db_session.add(chain_row)
    db_session.flush()

    run = DiscoveryRun(workspace_id=space.id, status="running")
    db_session.add(run)
    db_session.flush()

    new, updated = persist_contracts(
        db_session, space, chain_row, run, [make_contract()]
    )

    assert (new, updated) == (1, 0)
    rows = db_session.execute(select(ContractTarget)).scalars().all()
    assert len(rows) == 1
    assert rows[0].workspace_id == space.id
    assert rows[0].workspace_id != tenant.id
    assert rows[0].discovery_route == "instance"
    assert rows[0].verification_state == "verified"


def test_discovery_is_idempotent(db_session: Session) -> None:
    """The same contract found twice is one row."""
    space = get_or_create_discovery_workspace(db_session)
    chain_row = Chain(name="Ethereum", chain_id=1, environment="mainnet")
    db_session.add(chain_row)
    db_session.flush()

    run = DiscoveryRun(workspace_id=space.id, status="running")
    db_session.add(run)
    db_session.flush()

    contract = make_contract()
    persist_contracts(db_session, space, chain_row, run, [contract])
    new, updated = persist_contracts(db_session, space, chain_row, run, [contract])

    assert (new, updated) == (0, 0)
    assert len(db_session.execute(select(ContractTarget)).scalars().all()) == 1


def test_reverification_is_recorded_as_an_update(db_session: Session) -> None:
    """A contract re-verified later is counted as updated."""
    space = get_or_create_discovery_workspace(db_session)
    chain_row = Chain(name="Ethereum", chain_id=1, environment="mainnet")
    db_session.add(chain_row)
    db_session.flush()

    run = DiscoveryRun(workspace_id=space.id, status="running")
    db_session.add(run)
    db_session.flush()

    persist_contracts(
        db_session, space, chain_row, run, [make_contract(verified_at="2026-01-01T00:00:00Z")]
    )
    new, updated = persist_contracts(
        db_session, space, chain_row, run, [make_contract(verified_at="2026-06-01T00:00:00Z")]
    )

    assert (new, updated) == (0, 1)
    row = db_session.execute(select(ContractTarget)).scalar_one()
    assert row.verified_at is not None
    assert row.verified_at.year == 2026
    assert row.verified_at.month == 6


async def test_one_failing_chain_does_not_kill_the_cycle(db_session: Session) -> None:
    """A chain that fails costs that chain, not the cycle."""
    client = StubClient(
        contracts={
            1: [make_contract(chain_id=1, address="0x" + "11" * 20)],
            10: [make_contract(chain_id=10, address="0x" + "22" * 20)],
        },
        failures={137: BlockscoutUnavailableError(137, "cloudflare 403")},
    )
    service = DiscoveryService(db_session, client)

    outcome = await service.run_cycle(chain_ids=[1, 137, 10])

    assert outcome.chains_covered == 2
    assert outcome.chains_failed == 1
    assert outcome.contracts_found == 2
    assert outcome.contracts_new == 2
    assert 137 in outcome.failures
    assert "cloudflare 403" in outcome.failures[137]
    assert outcome.status == "partial"


async def test_an_unexpected_chain_error_is_contained(db_session: Session) -> None:
    """An unexpected error on one chain is contained, not fatal."""
    client = StubClient(
        contracts={1: [make_contract(chain_id=1)]},
        failures={10: RuntimeError("boom")},
    )
    service = DiscoveryService(db_session, client)

    outcome = await service.run_cycle(chain_ids=[1, 10])

    assert outcome.chains_covered == 1
    assert outcome.chains_failed == 1
    assert "RuntimeError" in outcome.failures[10]
    assert outcome.contracts_new == 1


async def test_the_cursor_advances_with_the_cycle(db_session: Session) -> None:
    """The cursor records how far the chain has been read."""
    client = StubClient(
        contracts={
            1: [
                make_contract(chain_id=1, address="0x" + "11" * 20),
                make_contract(chain_id=1, address="0x" + "22" * 20),
            ]
        }
    )
    service = DiscoveryService(db_session, client)

    await service.run_cycle(chain_ids=[1])

    cursor = db_session.execute(select(FeedCursor)).scalar_one()
    assert cursor.contracts_seen == 2
    assert cursor.last_address == "0x" + "22" * 20
    assert cursor.last_verified_at is not None


async def test_the_cursor_advances_even_when_a_chain_fails(db_session: Session) -> None:
    """A downstream failure cannot rewind the cursor."""
    client = StubClient(contracts={1: [make_contract(chain_id=1)]})
    service = DiscoveryService(db_session, client)

    await service.run_cycle(chain_ids=[1])
    first = db_session.execute(select(FeedCursor)).scalar_one()
    seen = first.contracts_seen
    assert seen == 1

    # A second cycle with no contracts must not reset the cursor.
    client.contracts = {}
    await service.run_cycle(chain_ids=[1])
    again = db_session.execute(select(FeedCursor)).scalar_one()
    assert again.contracts_seen == seen
    assert again.last_address == first.last_address


async def test_the_run_row_records_the_cycle(db_session: Session) -> None:
    """The persisted run carries the cycle's counters."""
    client = StubClient(contracts={1: [make_contract(chain_id=1)]})
    service = DiscoveryService(db_session, client)

    outcome = await service.run_cycle(chain_ids=[1])

    run = db_session.execute(select(DiscoveryRun)).scalar_one()
    assert run.id == outcome.run_id
    assert run.status == "completed"
    assert run.chains_covered == 1
    assert run.contracts_new == 1
    assert run.finished_at is not None
    assert run.errors == []


def test_batch_selection_prefers_unseen_chains(db_session: Session) -> None:
    """Chains that have never been swept come first."""
    space = get_or_create_discovery_workspace(db_session)
    chain_row = Chain(name="Ethereum", chain_id=1, environment="mainnet")
    db_session.add(chain_row)
    db_session.flush()

    old = datetime.now(UTC) - timedelta(days=2)
    db_session.add(
        FeedCursor(
            chain_id=chain_row.id,
            workspace_id=space.id,
            updated_at=old,
        )
    )
    db_session.flush()

    batch = select_batch(db_session, space.id, [1, 2, 3], batch_size=2)

    assert 1 not in batch
    assert set(batch) <= {2, 3}
    assert len(batch) == 2


def test_batch_selection_respects_the_size(db_session: Session) -> None:
    """The batch never exceeds the requested size."""
    space = get_or_create_discovery_workspace(db_session)
    batch = select_batch(db_session, space.id, list(range(1, 60)), batch_size=10)
    assert len(batch) == 10


def test_an_empty_chain_list_selects_nothing(db_session: Session) -> None:
    """An empty candidate list produces an empty batch."""
    space = get_or_create_discovery_workspace(db_session)
    assert select_batch(db_session, space.id, [], batch_size=10) == []
async def test_the_walk_continues_where_the_cursor_left_off(
    db_session: Session,
) -> None:
    """The pages behind the newest one are read as well."""
    client = StubClient(
        pages={
            1: {
                1: [make_contract(chain_id=1, address="0x" + "11" * 20)],
                2: [make_contract(chain_id=1, address="0x" + "22" * 20)],
            }
        }
    )
    service = DiscoveryService(db_session, client)

    outcome = await service.run_cycle(chain_ids=[1], pages=2)

    assert outcome.contracts_found == 2
    assert outcome.contracts_new == 2
    assert client.pages_requested == [(1, 1), (1, 2)]
    cursor = db_session.execute(select(FeedCursor)).scalar_one()
    assert cursor.next_page == 3


async def test_the_walk_returns_to_the_newest_page_at_the_end(
    db_session: Session,
) -> None:
    """The end of the feed sends the walk back to page one."""
    client = StubClient(pages={1: {1: [make_contract(chain_id=1)]}})
    service = DiscoveryService(db_session, client)

    await service.run_cycle(chain_ids=[1], pages=3)

    cursor = db_session.execute(select(FeedCursor)).scalar_one()
    assert cursor.next_page == 1
    assert (1, 2) in client.pages_requested


async def test_the_backfill_analyses_the_contracts_it_finds(
    db_session: Session,
) -> None:
    """A contract found on an older page is scanned, not only recorded."""
    client = StubClient(
        pages={
            1: {
                1: [make_contract(chain_id=1, address="0x" + "11" * 20)],
                2: [make_contract(chain_id=1, address="0x" + "22" * 20)],
            }
        }
    )
    service = DiscoveryService(db_session, client)

    await service.run_cycle(chain_ids=[1], pages=2)

    scans = db_session.execute(select(Scan)).scalars().all()
    assert len(scans) == 2


async def test_a_contract_the_cap_left_alone_is_offered_again(
    db_session: Session,
) -> None:
    """A contract found but never scanned is offered again, not stranded."""
    space = get_or_create_discovery_workspace(db_session)
    chain_row = Chain(name="Ethereum", chain_id=1, environment="mainnet")
    db_session.add(chain_row)
    db_session.flush()
    run = DiscoveryRun(workspace_id=space.id, status="running")
    db_session.add(run)
    db_session.flush()
    persist_contracts(
        db_session, space, chain_row, run, [make_contract(chain_id=1)]
    )

    # The feed returns nothing this cycle: the contract was found
    # earlier and never scanned, and must still be offered.
    client = StubClient(pages={1: {}})
    service = DiscoveryService(db_session, client)

    await service.run_cycle(chain_ids=[1])

    scans = db_session.execute(select(Scan)).scalars().all()
    assert len(scans) == 1
async def _a_target_with_a_failed_scan(
    db_session: Session, error_code: str
) -> tuple[object, object, object]:
    """A discovered contract whose last scan failed, for a given reason."""
    space = get_or_create_discovery_workspace(db_session)
    chain_row = Chain(name="Ethereum", chain_id=1, environment="mainnet")
    db_session.add(chain_row)
    db_session.flush()
    run = DiscoveryRun(workspace_id=space.id, status="running")
    db_session.add(run)
    db_session.flush()
    persist_contracts(db_session, space, chain_row, run, [make_contract(chain_id=1)])
    target = db_session.execute(select(ContractTarget)).scalar_one()
    scan = Scan(
        workspace_id=space.id,
        target_id=target.id,
        status=ScanStatus.FAILED,
        requested_by=None,
        fork="",
        bytecode_source="rpc",
        error_code=error_code,
    )
    db_session.add(scan)
    db_session.flush()
    return space, chain_row, target


async def test_a_contract_that_failed_for_a_transient_reason_is_looked_at_again(
    db_session: Session,
) -> None:
    """A rate-limited fetch is a fact about the moment, not the contract."""
    space, chain_row, target = await _a_target_with_a_failed_scan(
        db_session, "sourcify_unavailable"
    )

    outcome = promote_contracts(db_session, space, chain_row, [target], enqueue=False)

    assert outcome.queued == 1


async def test_a_contract_that_failed_for_a_real_reason_is_left_alone(
    db_session: Session,
) -> None:
    """A contract with no deployed code will not have one next time."""
    space, chain_row, target = await _a_target_with_a_failed_scan(
        db_session, "bytecode_empty"
    )

    outcome = promote_contracts(db_session, space, chain_row, [target], enqueue=False)

    assert outcome.queued == 0
    assert outcome.skipped_already_scanned == 1


async def test_a_contract_that_keeps_failing_is_not_tried_for_ever(
    db_session: Session,
) -> None:
    """The retries are bounded, so a broken endpoint is not hammered."""
    space, chain_row, target = await _a_target_with_a_failed_scan(
        db_session, "rpc_unreachable"
    )
    for _ in range(2):
        db_session.add(
            Scan(
                workspace_id=space.id,
                target_id=target.id,
                status=ScanStatus.FAILED,
                requested_by=None,
                fork="",
                bytecode_source="rpc",
                error_code="rpc_unreachable",
            )
        )
    db_session.flush()

    outcome = promote_contracts(db_session, space, chain_row, [target], enqueue=False)

    assert outcome.queued == 0
async def test_a_contract_that_failed_transiently_is_offered_again(
    db_session: Session,
) -> None:
    """The sweep offers a contract whose last scan failed for a moment."""
    space = get_or_create_discovery_workspace(db_session)
    chain_row = Chain(name="Ethereum", chain_id=1, environment="mainnet")
    db_session.add(chain_row)
    db_session.flush()
    run = DiscoveryRun(workspace_id=space.id, status="running")
    db_session.add(run)
    db_session.flush()
    persist_contracts(db_session, space, chain_row, run, [make_contract(chain_id=1)])
    target = db_session.execute(select(ContractTarget)).scalar_one()
    db_session.add(
        Scan(
            workspace_id=space.id,
            target_id=target.id,
            status=ScanStatus.FAILED,
            requested_by=None,
            fork="",
            bytecode_source="rpc",
            error_code="sourcify_unavailable",
        )
    )
    db_session.flush()

    # The feed returns nothing this cycle: the contract was found
    # earlier, and its scan failed for a reason that may pass.
    client = StubClient(pages={1: {}})
    service = DiscoveryService(db_session, client)

    await service.run_cycle(chain_ids=[1])

    scans = db_session.execute(select(Scan)).scalars().all()
    assert len(scans) == 2
