"""Show the dataflow rounds for one block.

Prints, for each round, the window the resolver holds for a block and the
window each predecessor hands over, so a lost value can be traced to the
exact round and edge that dropped it.
"""

from __future__ import annotations

import sys

from evm_analysis import build_cfg, disassemble, load_fork
from evm_analysis.resolver import _merge
from evm_analysis.stack import simulate_block

sys.path.insert(0, "scripts")
from crosscheck_evmole import CONTRACTS, fetch_bytecode  # noqa: E402


def main() -> int:
    label = sys.argv[1]
    watch = int(sys.argv[2])

    code = fetch_bytecode(CONTRACTS[label])
    dis = disassemble(code, load_fork("cancun"))
    cfg = build_cfg(dis)

    states: dict[int, list] = {start: [] for start in cfg.blocks}
    out_edges: dict[int, list] = {}
    for edge in cfg.edges:
        out_edges.setdefault(edge.source, []).append(edge)
    in_edges: dict[int, list] = {}
    for edge in cfg.edges:
        if edge.target is not None:
            in_edges.setdefault(edge.target, []).append(edge)

    for rnd in range(1, 9):
        changed = False
        for start in sorted(cfg.blocks):
            sim = simulate_block(cfg.blocks[start].instructions, states[start])
            if start == watch:
                print(
                    f"round {rnd}: block {start} entry={states[start]} "
                    f"exit={sim.exit_slots} jumps={sim.jump_targets}"
                )
            for edge in out_edges.get(start, ()):
                if edge.target is None:
                    continue
                before = states[edge.target]
                merged, did = _merge(before, sim.exit_slots)
                if did:
                    states[edge.target] = merged
                    changed = True
                    if edge.target == watch:
                        print(
                            f"round {rnd}:   merge into {watch} from "
                            f"{start} (off {edge.instruction_offset}) "
                            f"{before} + {sim.exit_slots} -> {merged}"
                        )
        if not changed:
            print(f"round {rnd}: fixpoint")
            break
    return 0


if __name__ == "__main__":
    sys.exit(main())
