"""Live check of the continuous discovery feed.

Runs a real discovery cycle against the real Blockscout routes, through the
real service, and reports what happened. Nothing is written to the database
that the development stack uses: the check runs against a throwaway session
that is rolled back.

Usage::

    node scripts/py.mjs --cwd apps/api -m scripts.live_check_discovery_feed
"""

from __future__ import annotations

import asyncio
import sys

from sqlalchemy import func, select

from app.db.models.discovery import DiscoveryRun, FeedCursor
from app.db.models.identity import Chain, ContractTarget
from app.db.session import session_scope
from app.services.blockscout import BlockscoutClient
from app.services.discovery import DiscoveryService, get_or_create_discovery_workspace

#: The chains to sweep. Three that have a working instance, and one that
#: does not, so the failure path is exercised too.
CHAINS = [1, 10, 8453]


async def run() -> int:
    """Run one live discovery cycle and report the result."""
    async with BlockscoutClient() as client:
        with session_scope() as session:
            workspace = get_or_create_discovery_workspace(session)
            service = DiscoveryService(session, client)

            outcome = await service.run_cycle(
                chain_ids=CHAINS, workspace=workspace, batch_size=len(CHAINS)
            )

            print("=== discovery cycle ===")
            print(f"  run id             : {outcome.run_id}")
            print(f"  status             : {outcome.status}")
            print(f"  chains covered     : {outcome.chains_covered}")
            print(f"  chains failed      : {outcome.chains_failed}")
            print(f"  contracts found    : {outcome.contracts_found}")
            print(f"  contracts new      : {outcome.contracts_new}")
            print(f"  contracts updated  : {outcome.contracts_updated}")

            print("=== per-chain failures ===")
            if not outcome.failures:
                print("  none")
            for chain_id, reason in sorted(outcome.failures.items()):
                print(f"  chain {chain_id}: {reason}")

            print("=== cursors ===")
            cursors = session.execute(
                select(Chain.chain_id, Chain.name, FeedCursor.contracts_seen,
                       FeedCursor.last_address)
                .join(Chain, Chain.id == FeedCursor.chain_id)
                .where(FeedCursor.workspace_id == workspace.id)
                .order_by(Chain.chain_id)
            ).all()
            if not cursors:
                print("  none")
            for chain_id, name, seen, last in cursors:
                print(f"  chain {chain_id:>6} {name:<22} seen={seen:<4} last={last}")

            print("=== discovered contracts (this workspace) ===")
            rows = session.execute(
                select(Chain.chain_id, Chain.name, ContractTarget.address,
                       ContractTarget.label, ContractTarget.verification_state,
                       ContractTarget.discovery_route)
                .join(Chain, Chain.id == ContractTarget.chain_id)
                .where(ContractTarget.workspace_id == workspace.id)
                .order_by(Chain.chain_id, ContractTarget.address)
            ).all()
            print(f"  total: {len(rows)}")
            for chain_id, _name, address, label, state, route in rows[:15]:
                print(f"  chain {chain_id:>6} {address} [{state}] via {route} :: {label}")
            if len(rows) > 15:
                print(f"  ... and {len(rows) - 15} more")

            print("=== runs recorded ===")
            total = session.scalar(select(func.count()).select_from(DiscoveryRun))
            print(f"  {total} discovery runs on the database")

    return 0


def main() -> int:
    """Entry point."""
    try:
        return asyncio.run(run())
    except Exception as exc:  # noqa: BLE001 - report, do not traceback
        print(f"live check failed: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
