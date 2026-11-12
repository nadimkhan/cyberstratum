"""Produce the definitive per-chain Blockscout PRO capability map.

Run with::

    node scripts/py.mjs scripts/pro_map.py

The PRO route is concurrency-limited: four simultaneous calls succeed, six
return HTTP 429. The probe therefore caps concurrency at three and retries on
429 with a short backoff, so the result reflects the API's real capability
rather than the probe's own burstiness.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import re
from pathlib import Path

import httpx

BASE = "https://api.blockscout.com/v2/api"

CHAIN_IDS = [
    1,
    10,
    30,
    61,
    100,
    122,
    130,
    137,
    177,
    239,
    291,
    314,
    324,
    360,
    42220,
    4326,
    480,
    488,
    592,
    698,
    714,
    747,
    869,
    957,
    102030,
    1135,
    1729,
    1829,
    1868,
    1890,
    2020,
    2288,
    2366,
    34443,
    42161,
    42170,
    42793,
    4663,
    5042,
    529375,
    57073,
    6497,
    6498,
    7000,
    8021,
    8453,
    97741,
    98866,
    13371,
    1514,
    190415,
    245022934,
    612055,
    685689,
    97477,
    101010,
    32769,
    1088,
    1313161554,
    534352,
]


def read_key() -> str | None:
    for name in ("BLOCKSCOUT_API_KEY", "BLOCKSCOUT_PRO_API_KEY"):
        import os

        value = os.environ.get(name)
        if value:
            return value.strip()
    for candidate in (Path(".env"), Path("../watchdog/.env")):
        if not candidate.exists():
            continue
        match = re.search(
            r"BLOCKSCOUT[A-Z_]*KEY\s*=\s*(\S+)",
            candidate.read_text(encoding="utf-8", errors="ignore"),
        )
        if match:
            return match.group(1).strip().strip('"').strip("'")
    return None


async def main() -> None:
    key = read_key()
    if key is None:
        print("  no PRO api key found")
        return

    semaphore = asyncio.Semaphore(3)

    async with httpx.AsyncClient(timeout=60) as client:

        async def one(chain_id: int) -> tuple[int, int, int]:
            async with semaphore:
                for _ in range(4):
                    try:
                        response = await client.get(
                            BASE,
                            params={
                                "chainid": chain_id,
                                "module": "contract",
                                "action": "listcontracts",
                                "items_count": 10,
                                "apikey": key,
                            },
                        )
                    except httpx.HTTPError:
                        await asyncio.sleep(2.0)
                        continue
                    if response.status_code == 429:
                        await asyncio.sleep(2.0)
                        continue
                    count = 0
                    with contextlib.suppress(ValueError):
                        count = len(response.json().get("result") or [])
                    return chain_id, response.status_code, count
                return chain_id, 429, 0

        outcomes = await asyncio.gather(*(one(c) for c in CHAIN_IDS))

    result = {cid: (status, count) for cid, status, count in outcomes}
    Path(".dev-logs/pro_map.json").write_text(
        json.dumps({str(k): v for k, v in result.items()}, indent=1),
        encoding="utf-8",
    )

    ok = sorted(c for c, (s, _) in result.items() if s == 200)
    plan = sorted(c for c, (s, _) in result.items() if s == 402)
    unsupported = sorted(c for c, (s, _) in result.items() if s == 404)
    other = {c: v for c, v in result.items() if v[0] not in (200, 402, 404)}

    print(f"  PRO 200 ok        ({len(ok):>2}): {ok}")
    print(f"  PRO 402 plan req  ({len(plan):>2}): {plan}")
    print(f"  PRO 404 not supp  ({len(unsupported):>2}): {unsupported}")
    print(f"  PRO other         ({len(other):>2}): {other}")


if __name__ == "__main__":
    asyncio.run(main())
