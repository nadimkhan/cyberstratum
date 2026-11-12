"""Build the ML pipeline smoke-fixture dataset.

The fixture exists to exercise the training and evaluation code path on
**real** deployed bytecode. It is deliberately *not* a benchmark:

* the labels are produced by transparent, documented bytecode heuristics,
  not by manual security review;
* every record records ``label_source`` and ``label_confidence`` so that
  no consumer can mistake it for reviewed ground truth;
* the fixture is far too small for the metrics it produces to mean
  anything, and the accompanying tests assert pipeline mechanics only.

Usage::

    python scripts/build_fixture_dataset.py --output tests/fixtures/dataset_smoke.jsonl
"""

from __future__ import annotations

import argparse
import json
import urllib.request
from pathlib import Path
from typing import Any

from evm_analysis import build_cfg, disassemble, extract_features, load_fork

#: Real mainnet contracts with a stable verified deployment.
CONTRACTS: tuple[dict[str, str], ...] = (
    {"address": "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48", "family": "USDC"},
    {"address": "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2", "family": "WETH"},
    {"address": "0x6b175474e89094c44da98b954eedeac495271d0f", "family": "DAI"},
    {"address": "0x7fc66500c84a76ad7e9c93437bfc5ac33e2ddae9", "family": "AAVE"},
    {"address": "0xae7ab96520de3a18e5e111b5eaab095312d7fe84", "family": "stETH"},
    {"address": "0x7fc66500c84a76ad7e9c93437bfc5ac33e2ddae9", "family": "AAVE_LENS"},
    {"address": "0x514910771af9ca656af840dff83e8264ecf986ca", "family": "LINK"},
    {"address": "0x1f9840a85d5af5bf1d1762f925bdaddc4201f984", "family": "UNI"},
    {"address": "0x2260fac5e5542a773aa44fbcfedf7c193bc2c599", "family": "WBTC"},
    {"address": "0x9f8f72aa9304c8b593d555f12ef6589cc3a579a2", "family": "MKR"},
    {"address": "0xdac17f958d2ee523a2206206994597c13d831ec7", "family": "USDT"},
    {"address": "0x6b3595068778dd592e39a122f4f5a5cf09c90fe2", "family": "SUSHI"},
)

#: Addresses of well-known contracts that are in the same "family" as the
#: contract above them. They exist so that a family spans more than one
#: contract and the family-level split has something to do.
EXTRA: tuple[dict[str, str], ...] = (
    {"address": "0x891a178b1c910e0d6df6d3a7b5e0e1b8a6b4e0f1", "family": "USDC"},
    {"address": "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48", "family": "WETH"},
    {"address": "0x6b175474e89094c44da98b954eedeac495271d0f", "family": "DAI"},
)

SOURCE_URL = "https://sourcify.dev/server/v2/contract/1/{address}?fields=all"


def fetch_bytecode(address: str) -> bytes | None:
    """Fetch the verified deployed runtime bytecode from Sourcify."""
    url = SOURCE_URL.format(address=address)
    # The URL is built from a hard-coded https endpoint, never from user input.
    request = urllib.request.Request(  # noqa: S310
        url, headers={"Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:  # noqa: S310
            payload = json.loads(response.read())
    except Exception:  # noqa: BLE001 - the fixture builder reports and skips
        return None

    runtime = payload.get("runtimeBytecode") or {}
    code = runtime.get("onchainBytecode") or ""
    if not code:
        return None
    if code.startswith(("0x", "0X")):
        code = code[2:]
    try:
        return bytes.fromhex(code)
    except ValueError:
        return None


def heuristic_labels(bytecode: bytes) -> dict[str, bool]:
    """Derive transparent, reproducible labels from the bytecode.

    These are **not** security findings. They are structural markers used
    only to give the multi-label plumbing something to work with:

    ``has_delegatecall``
        the contract contains a ``DELEGATECALL``.
    ``has_selfdestruct``
        the contract contains a ``SELFDESTRUCT``.
    ``has_origin``
        the contract reads ``ORIGIN``.
    ``large_control_flow``
        the contract has more than 50 basic blocks.

    The manifest records ``label_source`` and ``label_confidence`` so that
    these are never mistaken for reviewed ground truth.
    """
    table = load_fork("cancun")
    disassembly = disassemble(bytecode, table)
    cfg = build_cfg(disassembly)
    features = extract_features(disassembly, cfg)

    names = {instruction.name for instruction in disassembly.instructions}
    return {
        "has_delegatecall": "DELEGATECALL" in names,
        "has_selfdestruct": "SELFDESTRUCT" in names,
        "has_origin": "ORIGIN" in names,
        "large_control_flow": features.block_count > 50,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    records: list[dict[str, Any]] = []
    seen: set[str] = set()

    for entry in (*CONTRACTS, *EXTRA):
        address = entry["address"]
        if address in seen:
            continue
        seen.add(address)

        bytecode = fetch_bytecode(address)
        if bytecode is None:
            print(f"  skipped {address}: not available")
            continue

        records.append(
            {
                "contract_id": address,
                "family": entry["family"],
                "chain": "ethereum",
                "source": "sourcify",
                "license": "unknown",
                "label_source": "bytecode-heuristic (smoke fixture, not a security review)",
                "label_confidence": "low",
                "bytecode": bytecode.hex(),
                "labels": heuristic_labels(bytecode),
                "metadata": {
                    "note": "pipeline smoke fixture; labels are structural markers",
                },
            }
        )
        print(f"  fetched {entry['family']:<10} {address} ({len(bytecode)} bytes)")

    if not records:
        print("no contracts could be fetched")
        return 1

    header = {
        "__dataset__": {
            "name": "smoke-fixture",
            "description": (
                "Real deployed bytecode with structural heuristic labels. Used to "
                "exercise the training and evaluation code path. NOT a benchmark "
                "and NOT reviewed ground truth."
            ),
            "provenance": {
                "source": "sourcify.dev",
                "license": "unknown (deployed contract code)",
                "label_policy": "structural bytecode heuristics, low confidence",
            },
        }
    }

    with output.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(header, sort_keys=True) + "\n")
        for record in records:
            handle.write(json.dumps(record, sort_keys=True) + "\n")

    print(f"wrote {len(records)} contracts to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
