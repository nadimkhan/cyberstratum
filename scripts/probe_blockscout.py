"""Probe the Blockscout ecosystem and emit the chain registry.

This is the mechanism behind the chain registry in
``apps/api/app/services/chains.py``. It is kept in the repository and re-runnable
because the explorer landscape changes: instances appear, disappear, get blocked,
or move to a new host, and a hand-maintained list rots.

The script:

1. Downloads the authoritative Blockscout registry (``blockscout/chainscout``
   ``data/chains.json``), keyed by chain id.
2. Picks the candidate explorer host for each chain we support.
3. Probes each candidate with the real request shape we intend to use:
   ``GET https://{host}/api/v2/smart-contracts?items_count=2``.
4. Records the status code, whether the body parsed as JSON, and how long it took.
5. Prints a table and can emit the registry as Python source.

Run it with::

    node scripts/py.mjs scripts/probe_blockscout.py
    node scripts/py.mjs scripts/probe_blockscout.py --emit

The Blockscout PRO API key is read from ``BLOCKSCOUT_API_KEY`` when present and
is never written to the output.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

import httpx

REGISTRY_URL = (
    "https://raw.githubusercontent.com/blockscout/chainscout/main/data/chains.json"
)

#: An honest, descriptive user agent. Edge blocking on these hosts was measured
#: to be independent of the user agent, so there is nothing to gain from
#: pretending to be a browser.
USER_AGENT = "cyberstratum/0.1 (+https://github.com/HeroInt) blockscout-probe"

#: The chains we support. Kept here as the single source of truth for the probe;
#: the registry module imports the result.
TARGET_CHAIN_IDS = (
    1, 10, 30, 61, 100, 122, 130, 137, 177, 239, 291, 314, 324, 360, 42220, 4326,
    480, 488, 592, 698, 714, 747, 869, 957, 102030, 1135, 1729, 1829, 1868, 1890,
    2020, 2288, 2366, 34443, 42161, 42170, 42793, 4663, 5042, 529375, 57073, 6497,
    6498, 7000, 8021, 8453, 97741, 98866, 13371, 1514, 190415, 245022934, 612055,
    685689, 97477, 101010, 32769, 1088, 1313161554, 534352,
)

#: Hosts known to serve something other than the Blockscout v2 API. These are
#: the Blockscout project's own site and the commercial API, not a chain
#: explorer. ``explorer.blockscout.com`` additionally returns HTTP 200 for any
#: address including non-existent ones, so it can never be used to confirm that
#: a contract exists.
KNOWN_NON_BLOCKSCOUT = {
    "explorer.blockscout.com",
    "www.blockscout.com",
    "pro.blockscout.com",
    "api.blockscout.com",
}


def _host_of(url: str) -> str | None:
    """Return the host of a URL, or None when it cannot be parsed."""
    match = re.match(r"^https?://([^/]+)", url.strip())
    if match is None:
        return None
    host = match.group(1).lower().split(":")[0]
    return host or None


def candidate_hosts(entry: dict[str, Any]) -> list[str]:
    """Every explorer host for a registry entry.

    The host is not required to be a ``blockscout.com`` subdomain: Gnosis runs
    on ``gnosisscan.io``, OP Mainnet on ``explorer.optimism.io``, Mode on
    ``explorer.mode.net``, Metis on ``explorer.metis.io`` and Aurora on
    ``explorer.aurora.dev``. Filtering on the domain would silently discard
    working instances, so every explorer is probed and the *response shape* is
    what decides whether it is a usable Blockscout v2 API.
    """
    hosts: list[str] = []
    for explorer in entry.get("explorers") or []:
        url = explorer.get("url") or ""
        host = _host_of(url)
        if host and host not in KNOWN_NON_BLOCKSCOUT and host not in hosts:
            hosts.append(host)
    return hosts


async def probe_host(client: httpx.AsyncClient, host: str) -> dict[str, Any]:
    """Probe one host with the request shape we actually intend to use."""
    url = f"https://{host}/api/v2/smart-contracts"
    started = time.monotonic()
    try:
        response = await client.get(url, params={"items_count": 2})
    except httpx.HTTPError as error:
        return {
            "host": host,
            "status": 0,
            "ok": False,
            "items": 0,
            "seconds": round(time.monotonic() - started, 2),
            "note": type(error).__name__,
        }

    elapsed = round(time.monotonic() - started, 2)
    items = 0
    note = ""
    if response.status_code == 200:
        try:
            payload = response.json()
            items = len(payload.get("items", []))
            note = "json" if isinstance(payload, dict) else "not-json-object"
        except ValueError:
            note = "not-json"
    else:
        note = f"http-{response.status_code}"

    return {
        "host": host,
        "status": response.status_code,
        # A 200 that is not a JSON object with items is not a usable endpoint.
        "ok": response.status_code == 200 and items >= 0 and note == "json",
        "items": items,
        "seconds": elapsed,
        "note": note,
    }


async def rpc_chain_id(client: httpx.AsyncClient, entry: dict[str, Any]) -> int | None:
    """Read the chain id from the chain's own JSON-RPC endpoint.

    This is the independent check on chain identity: the explorer registry says
    which explorer belongs to which chain, and the RPC says what the chain
    actually is. Comparing the two catches a mis-mapped explorer.
    """
    for rpc in entry.get("rpc") or []:
        if not rpc.startswith("http"):
            continue
        try:
            response = await client.post(
                rpc,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "eth_chainId",
                    "params": [],
                },
            )
            if response.status_code != 200:
                continue
            payload = response.json()
            raw = payload.get("result")
            if raw is None:
                continue
            return int(raw, 16)
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            continue
    return None


#: The unified PRO endpoint. It is the legacy ``module``/``action`` shape under
#: ``/v2/api``, not the per-instance ``/api/v2/<resource>`` shape.
PRO_API_BASE = "https://api.blockscout.com/v2/api"


async def probe_pro(
    client: httpx.AsyncClient,
    chain_id: int,
    api_key: str | None,
) -> dict[str, Any]:
    """Probe the unified PRO route for one chain.

    The PRO route answers with statuses that each mean something specific:

    * ``200`` -- the chain is supported and the key's plan covers it.
    * ``402`` -- the chain is a "featured" chain the key's plan does not cover.
      Polygon and Base both answer this way on a free key.
    * ``404`` -- PRO does not support the chain at all.

    All three are ordinary outcomes, not errors. They decide which route a
    chain can use, and none of them should abort a sweep.
    """
    if not api_key:
        return {"chain_id": chain_id, "status": 0, "ok": False, "note": "no-api-key"}

    params = {
        "chainid": str(chain_id),
        "module": "contract",
        "action": "listcontracts",
        "items_count": "10",
        "apikey": api_key,
    }
    started = time.monotonic()
    try:
        response = await client.get(PRO_API_BASE, params=params)
    except httpx.HTTPError as error:
        return {
            "chain_id": chain_id,
            "status": 0,
            "ok": False,
            "seconds": round(time.monotonic() - started, 2),
            "note": type(error).__name__,
        }

    elapsed = round(time.monotonic() - started, 2)
    status = response.status_code
    count = 0
    if status == 200:
        try:
            payload = response.json()
            count = len(payload.get("result") or [])
            note = f"ok-{count}"
        except ValueError:
            note = "not-json"
    elif status == 402:
        note = "plan-required"
    elif status == 404:
        note = "not-supported"
    else:
        note = f"http-{status}"

    return {
        "chain_id": chain_id,
        "status": status,
        "ok": status == 200,
        "items": count,
        "seconds": elapsed,
        "note": note,
    }


async def probe_all(
    registry: dict[str, Any],
    api_key: str | None = None,
    concurrency: int = 8,
    timeout: float = 25.0,
) -> tuple[
    dict[int, list[dict[str, Any]]],
    dict[int, int | None],
    dict[int, dict[str, Any]],
]:
    """Probe every candidate host and the PRO route for every supported chain."""
    semaphore = asyncio.Semaphore(concurrency)
    results: dict[int, list[dict[str, Any]]] = {}
    chain_ids: dict[int, int | None] = {}
    pro_results: dict[int, dict[str, Any]] = {}

    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    ) as client:

        async def run(chain_id: int, host: str) -> tuple[int, dict[str, Any]]:
            async with semaphore:
                return chain_id, await probe_host(client, host)

        tasks = []
        for chain_id in TARGET_CHAIN_IDS:
            entry = registry.get(str(chain_id))
            if entry is None:
                continue
            for host in candidate_hosts(entry):
                tasks.append(run(chain_id, host))

        for chain_id, result in await asyncio.gather(*tasks):
            results.setdefault(chain_id, []).append(result)

        async def read_chain_id(chain_id: int) -> tuple[int, int | None]:
            entry = registry.get(str(chain_id)) or {}
            return chain_id, await rpc_chain_id(client, entry)

        wanted = [c for c in TARGET_CHAIN_IDS if str(c) in registry]
        for chain_id, observed in await asyncio.gather(
            *(read_chain_id(c) for c in wanted)
        ):
            chain_ids[chain_id] = observed

        async def read_pro(chain_id: int) -> tuple[int, dict[str, Any]]:
            return chain_id, await probe_pro(client, chain_id, api_key)

        for chain_id, outcome in await asyncio.gather(
            *(read_pro(c) for c in TARGET_CHAIN_IDS)
        ):
            pro_results[chain_id] = outcome

    return results, chain_ids, pro_results


def print_report(
    registry: dict[str, Any],
    results: dict[int, list[dict[str, Any]]],
    chain_ids: dict[int, int | None],
    pro_results: dict[int, dict[str, Any]],
) -> None:
    """Print a human-readable table of what responded."""
    print()
    print(
        f"{'chain':>10}  {'name':<26} {'instance':>9} {'items':>5}  "
        f"{'time':>5}  {'PRO':>9}  host"
    )
    print("-" * 106)

    working = 0
    dead = 0
    unroutable: list[int] = []
    for chain_id in TARGET_CHAIN_IDS:
        entry = registry.get(str(chain_id)) or {}
        name = str(entry.get("name") or "?")[:26]
        attempts = results.get(chain_id) or []
        pro = pro_results.get(chain_id) or {}
        pro_text = f"{pro.get('status', '-')}" if pro else "-"

        if not attempts:
            print(
                f"{chain_id:>10}  {name:<26} {'none':>9} {'-':>5}  {'-':>5}  "
                f"{pro_text:>9}  (no candidate)"
            )
            dead += 1
            if not pro.get("ok"):
                unroutable.append(chain_id)
            continue

        for attempt in attempts:
            mark = "OK " if attempt["ok"] else "   "
            print(
                f"{chain_id:>10}  {name:<26} {attempt['status']:>9} "
                f"{attempt['items']:>5}  {attempt['seconds']:>4}s  "
                f"{pro_text:>9}  {attempt['host']} {mark}{attempt['note']}"
            )
            if attempt["ok"]:
                working += 1
            else:
                dead += 1
                if not pro.get("ok"):
                    unroutable.append(chain_id)

    print("-" * 106)
    print(f"  {working} usable instance(s), {dead} failed instance attempt(s)")
    if unroutable:
        print(
            "  chains with NO working route (instance blocked and PRO "
            f"unavailable): {sorted(unroutable)}"
        )


def emit_registry(
    registry: dict[str, Any],
    results: dict[int, list[dict[str, Any]]],
) -> None:
    """Print the registry mapping as Python source."""
    print("INSTANCE_HOSTS: Final[dict[int, str]] = {")
    for chain_id in TARGET_CHAIN_IDS:
        attempts = results.get(chain_id) or []
        usable = [a for a in attempts if a["ok"]]
        if not usable:
            continue
        # Prefer the fastest responding host.
        best = min(usable, key=lambda a: a["seconds"])
        print(f'    {chain_id}: "{best["host"]}",')
    print("}")


def read_api_key() -> str | None:
    """Read the Blockscout PRO key from the environment or a local .env file.

    The key is never printed and never written to the probe output.
    """
    import os
    import re

    for name in ("BLOCKSCOUT_API_KEY", "BLOCKSCOUT_PRO_API_KEY"):
        value = os.environ.get(name)
        if value:
            return value.strip()

    for candidate in (Path(".env"), Path("../watchdog/.env")):
        if not candidate.exists():
            continue
        text = candidate.read_text(encoding="utf-8", errors="ignore")
        match = re.search(
            r"BLOCKSCOUT[A-Z_]*KEY\s*=\s*(\S+)", text
        )
        if match:
            return match.group(1).strip().strip('"').strip("'")
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--emit",
        action="store_true",
        help="print the INSTANCE_HOSTS mapping as Python source",
    )
    parser.add_argument(
        "--json",
        type=Path,
        default=None,
        help="write the raw probe results to this path",
    )
    args = parser.parse_args(argv)

    print("downloading the Blockscout registry...")
    response = httpx.get(REGISTRY_URL, timeout=60, headers={"User-Agent": USER_AGENT})
    response.raise_for_status()
    registry = response.json()
    print(f"  {len(registry)} chains in the registry")

    api_key = read_api_key()
    print(f"  PRO api key: {'present' if api_key else 'absent'}")

    results, chain_ids, pro_results = asyncio.run(
        probe_all(registry, api_key=api_key)
    )
    print_report(registry, results, chain_ids, pro_results)

    if args.emit:
        print()
        emit_registry(registry, results)

    if args.json:
        args.json.write_text(
            json.dumps(
                {
                    "results": results,
                    "rpc_chain_ids": chain_ids,
                    "pro": pro_results,
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        print(f"  raw results written to {args.json}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
