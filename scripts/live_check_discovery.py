"""Live check of the merged discovery layer.

Exercises the three routes the registry claims to support, against the real
Blockscout ecosystem:

1. An instance-backed chain (Ethereum).
2. A PRO-only chain (Arbitrum One -- its instance is Cloudflare-blocked).
3. An unreachable chain (Base -- blocked instance *and* a plan-gated PRO).

The Blockscout PRO key is read from ``watchdog/.env`` or the environment and
is never printed. The script prints counts, routes and verification states
only.

Usage::

    node scripts/py.mjs scripts/live_check_discovery.py
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))

from app.services.blockscout import (  # noqa: E402
    BlockscoutClient,
    BlockscoutUnavailableError,
)
from app.services.chains import (  # noqa: E402
    explorer_host_for,
    get_chain,
    pro_only_chains,
    unreachable_chains,
)

KEY_PATTERN = re.compile(r"^\s*BLOCKSCOUT_API_KEY\s*=\s*(.+?)\s*$", re.MULTILINE)


def _read_key() -> str:
    """Find the PRO key without ever writing it anywhere."""
    env_key = os.environ.get("BLOCKSCOUT_API_KEY", "").strip()
    if env_key:
        return env_key
    for candidate in (
        REPO_ROOT / ".env",
        Path("E:/projects/watchdog/.env"),
    ):
        if not candidate.exists():
            continue
        match = KEY_PATTERN.search(candidate.read_text(encoding="utf-8"))
        if match:
            value = match.group(1).strip().strip('"').strip("'")
            if value:
                return value
    return ""


async def _probe(client: BlockscoutClient, chain_id: int, label: str) -> bool:
    """One chain, one listing, reported honestly."""
    chain = get_chain(chain_id)
    host = explorer_host_for(chain_id)
    print(f"\n--- {label} (chain {chain_id}) ---")
    print(f"  instance host : {host or 'none'}")
    print(f"  PRO status    : {chain.pro_status if chain else 'unknown'}")
    print(f"  routes        : {chain.routes if chain else ()}")

    started = time.monotonic()
    try:
        contracts = await client.list_contracts(chain_id, page_size=10)
    except BlockscoutUnavailableError as exc:
        elapsed = time.monotonic() - started
        print(f"  RESULT        : unavailable after {elapsed:.1f}s -- {exc}")
        return False
    elapsed = time.monotonic() - started

    if not contracts:
        print(f"  RESULT        : empty listing after {elapsed:.1f}s")
        return False

    verified = sum(1 for c in contracts if c.is_verified)
    routes_used = sorted({c.route for c in contracts if c.route})
    print(f"  RESULT        : {len(contracts)} contracts in {elapsed:.1f}s")
    print(f"  route taken   : {routes_used}")
    print(f"  verified      : {verified}/{len(contracts)}")
    for contract in contracts[:3]:
        print(
            f"    {contract.address}  verified={contract.is_verified}  "
            f"route={contract.route}"
        )
    return True


async def main() -> int:
    # Derive the probe targets from the registry rather than hard-coding them,
    # so the check always exercises whatever the registry currently claims.
    pro_targets = [c.chain_id for c in pro_only_chains()]
    unreachable_targets = [c.chain_id for c in unreachable_chains()]
    if not pro_targets or not unreachable_targets:
        print("registry has no PRO-only or unreachable chain to probe")
        return 1
    pro_only_chain_id = pro_targets[0]
    unreachable_chain_id = unreachable_targets[0]

    key = _read_key()
    print("Blockscout live check of the merged discovery layer")
    print(f"PRO key present: {'yes' if key else 'no (PRO route unavailable)'}")

    async with BlockscoutClient(api_key=key) as client:
        instance_ok = await _probe(client, 1, "Route A - instance-backed")
        pro_ok = await _probe(client, pro_only_chain_id, "Route B - PRO fallback")
        unreachable_ok = await _probe(
            client, unreachable_chain_id, "No route"
        )

    print("\n=== verdict ===")
    print(f"  instance route works        : {instance_ok}")
    print(f"  PRO fallback works          : {pro_ok}")
    print(f"  unreachable chain reports it: {not unreachable_ok}")
    return 0 if instance_ok and pro_ok and not unreachable_ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
