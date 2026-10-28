#!/usr/bin/env python
"""Cross-validate the CyberStratum tokenizer against the independent `evmole` engine.

`evmole` is a Rust implementation of the same EVM disassembly problem, so it is
a useful independent oracle for the tokenizer: if the two disagree on the
instruction stream of real deployed bytecode, at least one of them is wrong.

The check is instruction-by-instruction:

* the number of instructions must match exactly;
* every instruction must share the same byte offset;
* every instruction must resolve to the same opcode name.

Run with::

    .venv/Scripts/python.exe scripts/crosscheck_evmole.py
"""

from __future__ import annotations

import json
import sys
import urllib.request
from dataclasses import dataclass

from evm_analysis.cfg import build_cfg
from evm_analysis.disassembler import disassemble
from evm_analysis.opcodes import canonical_opcode_name, load_fork

SOURCIFY_API = "https://sourcify.dev/server/v2/contract/{chain_id}/{address}?fields=all"

#: Well-known mainnet contracts with public verified source on Sourcify.
CONTRACTS: dict[str, str] = {
    "USDC (circle)": "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",
    "WETH (canonical)": "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",
    "DAI": "0x6b175474e89094c44da98b954eedeac495271d0f",
    "Uniswap V2 Router": "0x7a250d5630b4cf539739df2c5dacb4c659f2488d",
    "Uniswap V3 SwapRouter02": "0x68b3465833fb72a70ecdf485e0e4c7bd8665fc45",
    "Aave V3 Pool": "0x87870bca3f3fd6335c3f4ce8392d69350b4fa4e2",
    "Lido stETH": "0xae7ab96520de3a18e5e111b5eaab095312d7fe84",
}


@dataclass
class Mismatch:
    index: int
    offset: int
    ours: str
    theirs: str


def fetch_bytecode(address: str, chain_id: int = 1) -> bytes:
    url = SOURCIFY_API.format(chain_id=chain_id, address=address)
    # The URL is built from a hard-coded https endpoint, never from user input.
    request = urllib.request.Request(  # noqa: S310
        url, headers={"Accept": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=45) as response:  # noqa: S310
        payload = json.loads(response.read())
    runtime = payload.get("runtimeBytecode") or {}
    if isinstance(runtime, dict):
        runtime = runtime.get("onchainBytecode") or ""
    if runtime.startswith("0x"):
        runtime = runtime[2:]
    return bytes.fromhex(runtime)


def evmole_names(disassembled: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """Normalise evmole's ``(offset, "PUSH1 60")`` form to ``(offset, "PUSH1")``.

    Two normalisations are applied:

    * the immediate operand is stripped, because only the opcode name is
      compared;
    * ``KECCAK256`` is folded to ``KECCAK``, which is the name used by
      ``ethereum/execution-specs`` and therefore by the vendored table.

    evmole prints ``?`` for a byte it cannot decode; that is the same
    condition the CyberStratum tokenizer reports as ``INVALID``, so it is
    normalised too.
    """
    names: list[tuple[int, str]] = []
    for offset, text in disassembled:
        parts = text.split()
        name = parts[0] if parts else text
        if name == "?":
            name = "INVALID"
        names.append((offset, canonical_opcode_name(name)))
    return names


def compare(ours: list[tuple[int, str]], theirs: list[tuple[int, str]]) -> list[Mismatch]:
    mismatches: list[Mismatch] = []
    for index in range(max(len(ours), len(theirs))):
        our_offset, our_name = ours[index] if index < len(ours) else (-1, "<missing>")
        their_offset, their_name = theirs[index] if index < len(theirs) else (-1, "<missing>")
        if our_offset != their_offset or our_name != their_name:
            mismatches.append(Mismatch(index, our_offset, our_name, their_name))
    return mismatches


def evmole_jump_targets(blocks) -> set[int]:
    """Collect the statically resolved jump targets from evmole's CFG.

    evmole reports, per block, either a ``Jump`` (with a static target), a
    ``Jumpi`` (with a static true-target and a fall-through), or a
    ``DynamicJump``/``DynamicJumpi`` (with no static target). Comparing the
    *set* of static jump targets is independent of how each engine chooses to
    split basic blocks, so it isolates jump-resolution correctness from
    block-splitting conventions.
    """
    targets: set[int] = set()
    for block in blocks:
        btype = block.btype
        kind = type(btype).__name__
        if kind == "Jump":
            targets.add(btype.to)
        elif kind == "Jumpi":
            targets.add(btype.true_to)
        elif kind in ("DynamicJump", "DynamicJumpi"):
            # evmole lists the candidate destinations of a dynamic transfer.
            for candidate in btype.to:
                targets.add(candidate.to)
    return targets


def our_jump_targets(cfg) -> set[int]:
    """Collect the targets of every resolved or inferred jump edge."""
    from evm_analysis.cfg import EdgeType

    jump_types = {EdgeType.UNCONDITIONAL_JUMP, EdgeType.CONDITIONAL_JUMP}
    return {
        e.target
        for e in cfg.edges
        if e.target is not None and e.edge_type in jump_types
    }


def evmole_static_jumps(blocks, disassembly) -> dict[int, int]:
    """Map the offset of every statically resolved jump to its destination.

    ``evmole`` stores the branch inside the block it ends, and the block's
    ``end`` is the offset of that branch instruction rather than an
    exclusive upper bound, so the branch is the last instruction at or
    before ``block.end``.
    """
    offsets = [i.offset for i in disassembly.instructions]
    jumps: dict[int, int] = {}
    for block in blocks:
        btype = block.btype
        kind = type(btype).__name__
        if kind == "Jump":
            destination = btype.to
        elif kind == "Jumpi":
            destination = btype.true_to
        else:
            continue
        candidates = [o for o in offsets if block.start <= o <= block.end]
        if not candidates:
            continue
        jumps[max(candidates)] = destination
    return jumps


def our_static_jumps(cfg) -> dict[int, int]:
    """Map the offset of every resolved jump to its destination."""
    from evm_analysis.cfg import EdgeType

    jump_types = {EdgeType.UNCONDITIONAL_JUMP, EdgeType.CONDITIONAL_JUMP}
    return {
        e.instruction_offset: e.target
        for e in cfg.edges
        if e.target is not None and e.edge_type in jump_types
    }


def main() -> int:
    table = load_fork("cancun")
    failures = 0
    total_instructions = 0

    for label, address in CONTRACTS.items():
        try:
            code = fetch_bytecode(address)
        except Exception as exc:  # noqa: BLE001 - network flakiness must not abort the run
            print(f"[SKIP] {label}: {type(exc).__name__}: {exc}")
            failures += 1
            continue

        from evmole import contract_info  # imported late so a missing wheel is reported clearly

        info = contract_info(code, disassemble=True, basic_blocks=True, control_flow_graph=True)
        theirs = evmole_names(info.disassembled or [])

        disassembly = disassemble(code, table)
        cfg = build_cfg(disassembly)
        ours = [(i.offset, i.name) for i in disassembly.instructions]

        # evmole decodes the Solidity metadata trailer as if it were code, so
        # the comparison is limited to the executable prefix.
        executable = len(ours)
        if disassembly.metadata is not None:
            executable = min(executable, len(theirs))
        mismatches = compare(ours[:executable], theirs[:executable])

        total_instructions += len(ours)
        their_blocks = len(info.basic_blocks or [])

        their_targets = evmole_jump_targets(info.control_flow_graph.blocks)
        our_targets = our_jump_targets(cfg)
        only_ours = our_targets - their_targets
        only_theirs = their_targets - our_targets

        # The strongest invariant: for every jump both engines resolve, the
        # destination must be the same. A jump we resolve to a different
        # place is a wrong edge in the CFG; a jump we do not resolve is a
        # limitation, not an error, because the analysis reports it as
        # unresolved instead of guessing.
        their_jumps = evmole_static_jumps(info.control_flow_graph.blocks, disassembly)
        our_jumps = our_static_jumps(cfg)
        disagreements = {
            offset: (destination, their_jumps[offset])
            for offset, destination in our_jumps.items()
            if offset in their_jumps and their_jumps[offset] != destination
        }
        missed = sorted(set(their_jumps) - set(our_jumps))
        common = sorted(set(their_jumps) & set(our_jumps))
        agreed = sum(1 for o in common if their_jumps[o] == our_jumps[o])

        metadata = disassembly.metadata
        # evmole only builds blocks for reachable code, so the reachable
        # block count is the apples-to-apples figure. The total also counts
        # the Solidity data segments, which are unreachable.
        reachable = cfg.reachable_block_count

        status = "OK" if not mismatches else f"FAIL ({len(mismatches)} mismatches)"
        if only_ours:
            status += f" FALSE-POSITIVE TARGETS {sorted(only_ours)[:5]}"
        if disagreements:
            status += f" WRONG DESTINATION {sorted(disagreements)[:5]}"
        print(
            f"{label:<26} ours={len(ours):>6} instr  evmole={len(theirs):>6} instr  "
            f"blocks ours={reachable:>5} evmole={their_blocks:>5} "
            f"(total {len(cfg.blocks)})  {status}"
        )
        print(
            f"    jump targets: ours={len(our_targets):>4} evmole={len(their_targets):>4} "
            f"| only ours={sorted(only_ours)[:6]} only evmole={sorted(only_theirs)[:6]}"
        )
        if their_jumps:
            rate = 100.0 * agreed / len(their_jumps)
            print(
                f"    static jumps: evmole={len(their_jumps):>4} agreed={agreed:>4} "
                f"({rate:5.1f}%)  unresolved by us={len(missed):>3}  "
                f"wrong destination={len(disagreements):>3}"
            )
        for offset, (ours_, theirs_) in sorted(disagreements.items())[:5]:
            print(
                f"    jump at {offset}: ours={ours_} evmole={theirs_}"
            )
        if metadata is not None:
            print(
                f"    metadata: {metadata.length} bytes at offset {metadata.start_offset}, "
                f"solc {metadata.compiler_version or 'unknown'}"
            )
        for mismatch in mismatches[:5]:
            print(
                f"    idx {mismatch.index}: offset {mismatch.offset} "
                f"ours={mismatch.ours} evmole={mismatch.theirs}"
            )
        if mismatches or only_ours or disagreements:
            failures += 1

    print(f"\ntotal instructions cross-checked: {total_instructions}")
    print(f"contracts with mismatches      : {failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
