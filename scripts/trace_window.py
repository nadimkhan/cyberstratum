"""Trace the stack window along one chain of blocks.

Prints the top-anchored window the resolver knows at each block of a
chain, so a carried value can be followed from where it is pushed to the
jump that consumes it. The states come from the production dataflow, so
the trace cannot drift away from what the resolver actually does.
"""

from __future__ import annotations

import sys

from evm_analysis import build_cfg, disassemble, load_fork
from evm_analysis.resolver import run_dataflow

sys.path.insert(0, "scripts")
from crosscheck_evmole import CONTRACTS, fetch_bytecode  # noqa: E402


def main() -> int:
    label = sys.argv[1] if len(sys.argv) > 1 else "USDC (circle)"
    chain = [int(x) for x in sys.argv[2].split(",")] if len(sys.argv) > 2 else []

    code = fetch_bytecode(CONTRACTS[label])
    dis = disassemble(code, load_fork("cancun"))
    cfg = build_cfg(dis)
    states, resolved = run_dataflow(dis, cfg)

    out_edges: dict[int, list] = {}
    for edge in cfg.edges:
        out_edges.setdefault(edge.source, []).append(edge)

    print(f"{label}: {len(cfg.blocks)} blocks")
    for start in chain:
        if start not in cfg.blocks:
            print(f"  block {start}: not a block start")
            continue
        block = cfg.blocks[start]
        body = " ".join(i.name for i in block.instructions)
        print(f"  block {start:>5} window={states[start]}")
        print(f"          {body}")
        for e in out_edges.get(start, ()):
            print(
                f"          -> {e.edge_type.value} target={e.target} "
                f"@off {e.instruction_offset}"
            )
    print(f"  resolved jumps: {len(resolved)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
