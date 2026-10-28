"""Validate the engine against real deployed bytecode.

Fetches runtime code for a set of well-known mainnet contracts from a public
JSON-RPC endpoint, then:
  * disassembles and builds the CFG;
  * cross-checks the instruction count against `evmole` (an independent Rust
    implementation) when it is available.

This is a manual validation script, not part of the unit test suite (it needs
network access).
"""

from __future__ import annotations

import json
import sys
import urllib.request

from evm_analysis.cfg import build_cfg
from evm_analysis.disassembler import disassemble
from evm_analysis.features import extract_features
from evm_analysis.opcodes import load_fork

# Sourcify serves the *deployed runtime bytecode* of verified contracts over a
# plain HTTPS API, which keeps this validation script dependency-free and
# reproducible (unlike a random RPC endpoint).
SOURCIFY_API = "https://sourcify.dev/server/v2/contract/{chain_id}/{address}?fields=all"

CONTRACTS = {
    "USDC (circle)": "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",
    "WETH (canonical)": "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",
    "DAI": "0x6b175474e89094c44da98b954eedeac495271d0f",
    "Uniswap V2 Router": "0x7a250d5630b4cf539739df2c5dacb4c659f2488d",
    "Uniswap V3 SwapRouter02": "0x68b3465833fb72a70ecdf485e0e4c7bd8665fc45",
    "SushiSwap Router": "0xd9e1c17e7b24ce72a8f4decd0abb712962b480b",
    "Aave V3 Pool": "0x87870bca3f3fd6335c3f4ce8392d69350b4fa4e2",
    "Lido stETH": "0xae7ab96520de3a18e5e111b5eaab095312d7fe84",
}


def fetch_bytecode(address: str, chain_id: int = 1) -> tuple[str, str | None]:
    """Fetch verified runtime bytecode for ``address`` from Sourcify."""
    url = SOURCIFY_API.format(chain_id=chain_id, address=address)
    # The URL is built from a hard-coded https endpoint, never from user input.
    request = urllib.request.Request(  # noqa: S310
        url, headers={"Accept": "application/json"}
    )
    try:
        # The URL is built from a hard-coded https endpoint, never from user input.
        with urllib.request.urlopen(request, timeout=45) as response:  # noqa: S310
            payload = json.loads(response.read())
    except Exception as exc:  # noqa: BLE001 - report and continue
        print(f"    error      : {type(exc).__name__}: {exc}")
        return "", None

    runtime = payload.get("runtimeBytecode") or ""
    if isinstance(runtime, dict):
        # Sourcify returns an object; `onchainBytecode` is the deployed code
        # (as opposed to `recompiledBytecode`, which is rebuilt from source).
        runtime = runtime.get("onchainBytecode") or ""
    if not runtime:
        return "", url
    if runtime.startswith("0x"):
        runtime = runtime[2:]
    return runtime, url


def main() -> int:
    total_instructions = 0
    failures = 0

    for label, address in CONTRACTS.items():
        code_hex, url = fetch_bytecode(address)
        if not code_hex or code_hex == "0x":
            print(f"[SKIP] {label}: no bytecode (rpc: {url})")
            failures += 1
            continue

        # `fetch_bytecode` already removed the "0x" prefix.
        code = bytes.fromhex(code_hex)
        table = load_fork("cancun")
        disassembly = disassemble(code, table)
        cfg = build_cfg(disassembly)
        features = extract_features(disassembly, cfg)

        total_instructions += len(disassembly.instructions)

        print(f"\n=== {label} ({address})")
        print(f"    rpc        : {url}")
        print(f"    code size  : {len(code)} bytes")
        print(f"    instructions: {len(disassembly.instructions)}")
        print(f"    blocks     : {len(cfg.blocks)}  edges: {len(cfg.edges)}")
        print(f"    unresolved : {len(cfg.unresolved_edges)}")
        print(f"    cycles     : {features.cycle_count}")
        print(
            f"    calls      : {len(features.call_offsets)}"
            f"  creates: {len(features.create_offsets)}"
        )
        print(
            f"    sloads     : {len(features.storage_read_offsets)}"
            f"  sstores: {len(features.storage_write_offsets)}"
        )
        print(f"    warnings   : {len(disassembly.warnings)}")
        if disassembly.warnings:
            for warning in disassembly.warnings[:3]:
                print(f"      - {warning}")

        # Cross-check against evmole when installed.
        try:
            from evmole import contract_info  # type: ignore[import-not-found]

            info = contract_info(code, 0)
            evmole_count = len(info.instruction_list)
            match = "MATCH" if evmole_count == len(disassembly.instructions) else "MISMATCH"
            print(f"    evmole     : {evmole_count} instructions -> {match}")
            if match == "MISMATCH":
                failures += 1
        except ImportError:
            print("    evmole     : not installed, skipping cross-check")

    print(f"\nTotal instructions analysed: {total_instructions}")
    print(f"Failures: {failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
