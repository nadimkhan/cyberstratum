"""Static jump-target resolution by abstract stack simulation.

The CFG builder needs to know, for every ``JUMP``/``JUMPI``, where control
can go. Solidity's compiler emits the destination as a constant on the stack
just before the branch, but it frequently shuffles that value around
(``DUP``, ``SWAP``) before branching, so "the instruction right before the
branch is a ``PUSH``" is not a complete rule.

This module runs a small abstract interpreter over the block graph:

* a top-anchored window of known stack constants is propagated forward
  through the graph;
* each block is then simulated to track which stack slots hold known
  constants, and a branch whose destination slot holds a constant is
  resolved;
* anything that cannot be resolved stays unresolved -- the resolver never
  guesses.

Two paths that reach the same block are merged conservatively: a slot that
only one of them knows becomes unknown, because the other path may hold a
different value there. The merge is aligned at the *top* of the stack,
because that is the end of the stack the window describes.

The fixpoint is deterministic: blocks are always processed in ascending
offset order and the target map only ever grows.
"""

from __future__ import annotations

from .cfg import ControlFlowGraph, Edge, EdgeType
from .disassembler import Disassembly
from .stack import Slot, Stack, simulate_block

#: Maximum number of dataflow rounds before the fixpoint gives up. Loops
#: converge quickly in practice; the cap only exists so that a pathological
#: input cannot hang the scanner.
_MAX_ROUNDS = 16


def resolve_jump_targets(disassembly: Disassembly, cfg: ControlFlowGraph) -> dict[int, int]:
    """Resolve as many jump targets as the abstract interpreter can.

    Returns a mapping from the offset of the jump instruction to its
    destination offset. Instructions that are not in the mapping are
    genuinely unresolved.
    """
    states, resolved = run_dataflow(disassembly, cfg)

    # Only keep targets that really are jump destinations.
    jumpdests = set(disassembly.jumpdests)
    return {
        offset: target
        for offset, target in resolved.items()
        if target in jumpdests and target in cfg.blocks
    }


def run_dataflow(
    disassembly: Disassembly, cfg: ControlFlowGraph
) -> tuple[dict[int, Stack | None], dict[int, int]]:
    """Run the dataflow fixpoint and return the block states.

    The first element maps a block's start offset to the stack window known
    on entry to it, or to ``None`` when no path has reached the block yet.
    The second element maps the offset of a jump instruction to the
    destination the analysis could determine.

    The function is public so that diagnostics can inspect the same states
    the resolver actually uses, instead of re-implementing the fixpoint.
    """
    if not cfg.blocks:
        return {}, {}

    by_offset = {instr.offset: instr for instr in disassembly.instructions}
    if not by_offset:
        return {}, {}

    # The window known on entry to each block, top-anchored. ``None`` means
    # "nothing has arrived yet" and is *not* the same as an empty window:
    # merging an empty window with an incoming one is a real conflict
    # between two paths, while merging the initial state simply takes the
    # first path that reaches the block. Treating them alike throws away
    # every value the first arriving path brought with it.
    states: dict[int, Stack | None] = dict.fromkeys(cfg.blocks)

    resolved: dict[int, int] = {}

    # Adjacency map: scanning every edge for every block would be quadratic.
    out_edges: dict[int, list[Edge]] = {}
    for edge in cfg.edges:
        out_edges.setdefault(edge.source, []).append(edge)

    for _ in range(_MAX_ROUNDS):
        changed = False

        for start in sorted(cfg.blocks):
            known = states[start]
            entry = known if known is not None else []
            simulation = simulate_block(cfg.blocks[start].instructions, entry)
            resolved.update(simulation.jump_targets)

            for edge in out_edges.get(start, ()):
                if edge.target is None:
                    # A dynamic transfer. The destination is unknown, so no
                    # stack state can be propagated through it: doing so
                    # would flood every JUMPDEST block with a stack shape
                    # that belongs to a single path, and the resulting
                    # contradictions would poison the whole dataflow.
                    # Blocks that are only reachable dynamically therefore
                    # keep an empty window, which is the honest answer.
                    continue

                if edge.target not in states:
                    continue
                current = states[edge.target]
                if current is None:
                    # First path to reach this block: take its window as is.
                    states[edge.target] = list(simulation.exit_slots)
                    changed = True
                    continue
                merged, did_change = _merge(current, simulation.exit_slots)
                if did_change:
                    states[edge.target] = merged
                    changed = True

        if not changed:
            break

    return states, resolved


def _merge(current: Stack, incoming: Stack) -> tuple[Stack, bool]:
    """Merge an incoming stack window into the one already known.

    The windows are aligned at the top of the stack. A slot that both paths
    agree on is known; a slot that only one path knows, or that the paths
    disagree on, becomes unknown -- keeping one path's value would be a
    guess.
    """
    size = max(len(current), len(incoming))
    left = [None] * (size - len(current)) + list(current)
    right = [None] * (size - len(incoming)) + list(incoming)

    merged = list(left)
    changed = False
    for index, (a, b) in enumerate(zip(left, right, strict=False)):
        if a is not None and b is not None and a == b:
            continue
        if (a is not None or b is not None) and merged[index] is not None:
            merged[index] = None
            changed = True
    if not changed and merged != current:
        changed = True
    return merged, changed


def resolved_targets_by_offset(disassembly: Disassembly, cfg: ControlFlowGraph) -> dict[int, int]:
    """Public alias kept for readability at the call site."""
    return resolve_jump_targets(disassembly, cfg)


__all__ = [
    "Edge",
    "EdgeType",
    "Slot",
    "Stack",
    "resolved_targets_by_offset",
    "resolve_jump_targets",
    "run_dataflow",
]
