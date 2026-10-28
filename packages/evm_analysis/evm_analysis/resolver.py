"""Static jump-target resolution by abstract stack simulation.

The CFG builder needs to know, for every ``JUMP``/``JUMPI``, where control
can go. Solidity's compiler emits the destination as a constant on the stack
just before the branch, but it frequently shuffles that value around
(``DUP``, ``SWAP``) before branching, so "the instruction right before the
branch is a ``PUSH``" is not a complete rule.

This module runs a small abstract interpreter over the block graph:

* the stack depth at every block entry is computed by a forward dataflow
  fixpoint, so loops converge;
* each block is then simulated to track which stack slots hold known
  constants, and a branch whose destination slot holds a constant is
  resolved;
* anything that cannot be resolved stays unresolved -- the resolver never
  guesses.

The fixpoint is deterministic: blocks are always processed in ascending
offset order and conflicts are resolved by marking a block's depth unknown
rather than by picking a winner.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .cfg import ControlFlowGraph, Edge, EdgeType
from .disassembler import Disassembly
from .stack import UNKNOWN_DEPTH, BlockSimulation, Slot, Stack, simulate_block

#: Maximum number of dataflow rounds before the fixpoint gives up. Loops
#: converge quickly in practice; the cap only exists so that a pathological
#: input cannot hang the scanner.
_MAX_ROUNDS = 16


@dataclass(slots=True)
class _EntryState:
    """The abstract stack state at the entry of a block."""

    depth: int = UNKNOWN_DEPTH
    slots: Stack = field(default_factory=list)
    poisoned: bool = False
    """Set when two paths disagree, which makes the depth unknowable."""


def resolve_jump_targets(
    disassembly: Disassembly, cfg: ControlFlowGraph
) -> dict[int, int]:
    """Resolve as many jump targets as the abstract interpreter can.

    Returns a mapping from the offset of the jump instruction to its
    destination offset. Instructions that are not in the mapping are
    genuinely unresolved.
    """
    if not cfg.blocks:
        return {}

    by_offset = {instr.offset: instr for instr in disassembly.instructions}
    if not by_offset:
        return {}

    states: dict[int, _EntryState] = {start: _EntryState() for start in cfg.blocks}

    entry = cfg.entry_offset if cfg.entry_offset in cfg.blocks else min(cfg.blocks)
    states[entry] = _EntryState(depth=0, slots=[])

    resolved: dict[int, int] = {}

    # Adjacency map: scanning every edge for every block would be quadratic.
    out_edges: dict[int, list[Edge]] = {}
    for edge in cfg.edges:
        out_edges.setdefault(edge.source, []).append(edge)

    for _ in range(_MAX_ROUNDS):
        changed = False

        for start in sorted(cfg.blocks):
            state = states[start]
            if state.poisoned and state.depth == UNKNOWN_DEPTH:
                # Nothing can be said about this block's entry stack.
                continue

            simulation = simulate_block(
                cfg.blocks[start].instructions, state.depth, state.slots
            )
            resolved.update(simulation.jump_targets)

            for edge in out_edges.get(start, ()):
                if edge.target is None:
                    # A dynamic transfer. The destination is unknown, so no
                    # stack state can be propagated through it: doing so
                    # would flood every JUMPDEST block with a stack shape
                    # that belongs to a single path, and the resulting
                    # contradictions would poison the whole dataflow.
                    # Blocks that are only reachable dynamically therefore
                    # keep an unknown entry stack, which is the honest
                    # answer.
                    continue

                incoming_depth, incoming_slots = _incoming_stack(edge, simulation)
                target = edge.target
                if target not in states:
                    continue
                if _merge(states[target], incoming_depth, incoming_slots):
                    changed = True

        if not changed:
            break

    # Only keep targets that really are jump destinations.
    jumpdests = set(disassembly.jumpdests)
    return {
        offset: target
        for offset, target in resolved.items()
        if target in jumpdests and target in cfg.blocks
    }


def _incoming_stack(edge: Edge, simulation: BlockSimulation) -> tuple[int, Stack]:
    """The stack state seen by the destination of ``edge``."""
    depth = simulation.exit_depth
    slots = list(simulation.exit_slots)
    if depth == UNKNOWN_DEPTH:
        return UNKNOWN_DEPTH, []
    return depth, slots


def _merge(state: _EntryState, depth: int, slots: Stack) -> bool:
    """Merge an incoming stack state into ``state``.

    Returns ``True`` when the merged state differs from the previous one.
    """
    if depth == UNKNOWN_DEPTH:
        if not state.poisoned:
            state.poisoned = True
            state.depth = UNKNOWN_DEPTH
            state.slots = []
            return True
        return False

    if state.poisoned:
        # The depth was already found to be contradictory; keep it unknown.
        return False

    if state.depth == UNKNOWN_DEPTH:
        state.depth = depth
        state.slots = list(slots)
        return True

    if state.depth != depth:
        # Two paths reach this block with different stack depths: the depth
        # is genuinely unknowable.
        state.poisoned = True
        state.depth = UNKNOWN_DEPTH
        state.slots = []
        return True

    # Same depth: merge the known constants slot by slot.
    changed = False
    merged = list(state.slots)
    for index, value in enumerate(slots):
        if index >= len(merged):
            merged.append(value)
            changed = True
        elif merged[index] is None and value is not None:
            merged[index] = value
            changed = True
    if changed:
        state.slots = merged
    return changed


def resolved_targets_by_offset(
    disassembly: Disassembly, cfg: ControlFlowGraph
) -> dict[int, int]:
    """Public alias kept for readability at the call site."""
    return resolve_jump_targets(disassembly, cfg)


__all__ = [
    "Edge",
    "EdgeType",
    "Slot",
    "Stack",
    "resolved_targets_by_offset",
    "resolve_jump_targets",
]
