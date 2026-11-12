"""Basic block and control-flow graph construction.

Implements the requirements from the technical design doc, §6.3:

* Block boundaries occur at control-flow terminators (``JUMP``, ``JUMPI``,
  ``STOP``, ``RETURN``, ``REVERT``, ``INVALID``, ``SELFDESTRUCT``), at the
  instruction following a branch, and at valid ``JUMPDEST`` locations.
* A CFG is **not** assumed to be a DAG: loops and cyclic edges are normal in
  Solidity and are preserved.
* Edge confidence is tracked: ``resolved`` (a statically known target),
  ``inferred`` (a target derived from a constant ``PUSH`` immediately before a
  jump), and ``unresolved`` (a dynamic stack value).

The graph is a directed graph ``G=(V,E)``. Blocks are identified by their
starting offset so that they are stable across re-runs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from .disassembler import Disassembly, Instruction


class EdgeType(StrEnum):
    """The kind of control-flow transfer an edge represents."""

    FALLTHROUGH = "fallthrough"
    UNCONDITIONAL_JUMP = "unconditional_jump"
    CONDITIONAL_JUMP = "conditional_jump"
    CONDITIONAL_FALLTHROUGH = "conditional_fallthrough"
    RETURN = "return"
    REVERT = "revert"
    STOP = "stop"
    INVALID = "invalid"
    SELFDESTRUCT = "selfdestruct"
    UNRESOLVED = "unresolved"


class Resolution(StrEnum):
    """Confidence in an edge's destination."""

    RESOLVED = "resolved"
    """The destination is statically known exactly."""

    INFERRED = "inferred"
    """The destination was derived from a constant push adjacent to the jump."""

    UNRESOLVED = "unresolved"
    """The destination depends on a runtime stack value and is not known."""


#: How many times the resolver's findings are fed back into its own
#: dataflow before the CFG is considered final.
_MAX_RESOLUTION_ROUNDS = 8

#: Instructions that end a basic block because control does not fall through.
_TERMINATORS = {
    "STOP",
    "RETURN",
    "REVERT",
    "INVALID",
    "SELFDESTRUCT",
}

#: Instructions that end a block but may transfer control elsewhere.
_BRANCHES = {"JUMP", "JUMPI"}


@dataclass(frozen=True, slots=True)
class Edge:
    """A directed control-flow edge between two blocks."""

    source: int
    """Start offset of the source block."""

    target: int | None
    """Start offset of the destination block, or ``None`` when unresolved."""

    edge_type: EdgeType
    resolution: Resolution
    instruction_offset: int
    """Offset of the instruction that produced this edge."""

    @property
    def is_unresolved(self) -> bool:
        return self.resolution is Resolution.UNRESOLVED


@dataclass(slots=True)
class Block:
    """A basic block: a maximal run of instructions with a single entry."""

    start: int
    """Start offset of the block."""

    end: int
    """Offset one past the last instruction byte of the block."""

    instructions: list[Instruction] = field(default_factory=list)
    terminator: str | None = None
    """Name of the terminating instruction, if the block ends on one."""

    reachable: bool = True
    """Whether the block is reachable from the entry point.

    Solidity appends *data* regions to the runtime code -- most visibly the
    revert-reason strings -- guarded by an ``INVALID`` opcode so that
    execution can never fall into them. Those bytes decode into instructions
    that are never executed, so they form blocks that are unreachable from
    the entry point. They stay in the graph (they are part of the artifact
    and a reviewer wants to see them) but they are flagged and excluded from
    the reachable-graph metrics.
    """

    @property
    def size(self) -> int:
        return len(self.instructions)

    @property
    def byte_size(self) -> int:
        return self.end - self.start

    @property
    def is_empty(self) -> bool:
        return not self.instructions


@dataclass(slots=True)
class ControlFlowGraph:
    """The CFG for one disassembly."""

    blocks: dict[int, Block] = field(default_factory=dict)
    edges: list[Edge] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    """Observations about the graph that are not defects.

    A dynamic jump is a property of the bytecode, not a failure of
    the analysis: the destination is computed at run time and no
    static analysis can follow it. It is counted and reported, but
    it does not mean the contract was left unanalysed.
    """
    entry_offset: int = 0

    @property
    def unresolved_edges(self) -> list[Edge]:
        return [e for e in self.edges if e.is_unresolved]

    @property
    def edge_count(self) -> int:
        return len(self.edges)

    @property
    def reachable_blocks(self) -> list[Block]:
        """Blocks reachable from the entry point, in offset order."""
        return [b for b in self.blocks.values() if b.reachable]

    @property
    def unreachable_blocks(self) -> list[Block]:
        """Blocks that cannot be reached from the entry point."""
        return [b for b in self.blocks.values() if not b.reachable]

    @property
    def reachable_block_count(self) -> int:
        return sum(1 for b in self.blocks.values() if b.reachable)

    @property
    def unreachable_regions(self) -> list[tuple[int, int]]:
        """Byte ranges of the unreachable regions, in offset order.

        Each range is ``(start, end)`` with ``end`` exclusive. These are
        typically the Solidity data segments (revert strings, and the
        constant blobs solc keeps behind an ``INVALID`` guard).
        """
        regions: list[tuple[int, int]] = []
        for block in sorted(self.unreachable_blocks, key=lambda b: b.start):
            if regions and regions[-1][1] == block.start:
                regions[-1] = (regions[-1][0], block.end)
            else:
                regions.append((block.start, block.end))
        return regions

    @property
    def unreachable_byte_size(self) -> int:
        """Total number of bytes that are not reachable from the entry."""
        return sum(end - start for start, end in self.unreachable_regions)

    def block_at(self, offset: int) -> Block | None:
        """Return the block containing ``offset``, if any."""
        for block in self.blocks.values():
            if block.start <= offset < block.end:
                return block
        return None

    def successors(self, block_start: int) -> list[Edge]:
        """Outgoing edges of the block starting at ``block_start``."""
        return [e for e in self.edges if e.source == block_start]

    def predecessors(self, block_start: int) -> list[Edge]:
        """Incoming edges of the block starting at ``block_start``."""
        return [e for e in self.edges if e.target == block_start]

    def find_cycles(self) -> list[list[int]]:
        """Return elementary cycles found in the graph.

        Used by the feature extractor to report "graph cycles" without
        assuming the graph is acyclic. Implemented as an iterative DFS with a
        colour marking so it terminates on cyclic graphs.
        """
        cycles: list[list[int]] = []
        seen_cycles: set[tuple[int, ...]] = set()

        # Only the reachable subgraph is searched: unreachable data regions
        # contain fall-through chains that are not real control flow.
        reachable = {b.start for b in self.blocks.values() if b.reachable}

        white, grey, black = 0, 1, 2
        colour: dict[int, int] = dict.fromkeys(reachable, white)

        def visit(node: int, path: list[int]) -> None:
            colour[node] = grey
            path.append(node)
            for edge in self.successors(node):
                target = edge.target
                if target is None or target not in reachable:
                    continue
                state = colour.get(target, white)
                if state == grey and target in path:
                    # Found a cycle: slice the path from the target onwards.
                    cycle = path[path.index(target) :]
                    key = tuple(sorted(cycle))
                    if key not in seen_cycles:
                        seen_cycles.add(key)
                        cycles.append(list(cycle))
                elif state == white:
                    visit(target, path)
            path.pop()
            colour[node] = black

        for start in reachable:
            if colour.get(start, white) == white:
                visit(start, [])

        return cycles


def _constant_push_before(
    instruction: Instruction, disassembly: Disassembly, index_by_offset: dict[int, int]
) -> int | None:
    """Return the constant target of a jump, when it is statically derivable.

    The destination of a branch is the top of the stack (Yellow Paper:
    ``JUMPI`` jumps to ``mu_s[0]`` when ``mu_s[1]`` is non-zero), and a
    ``PUSHn`` immediately before the branch puts its value on top. The
    condition of a ``JUMPI`` is therefore pushed *before* the destination,
    so the rule holds for both branch kinds.

    This is the *fallback* rule. :mod:`evm_analysis.resolver` runs a full
    abstract stack simulation, which resolves strictly more targets; this
    rule is kept as a bootstrap so the dataflow has a graph to walk on the
    first round.
    """
    idx = index_by_offset.get(instruction.offset)
    if idx is None or idx == 0:
        return None

    previous = disassembly.instructions[idx - 1]
    if not previous.is_push:
        return None
    value = previous.immediate_int
    if value is None:
        return None
    return value


def build_cfg(disassembly: Disassembly) -> ControlFlowGraph:
    """Build the control-flow graph for a disassembly."""
    instructions = disassembly.instructions
    cfg = ControlFlowGraph(entry_offset=disassembly.instructions[0].offset if instructions else 0)

    if not instructions:
        cfg.warnings.append("no instructions to build a control-flow graph from")
        return cfg

    jumpdest_offsets = set(disassembly.jumpdests)

    # --- Determine block boundaries ---------------------------------------
    leaders: set[int] = {instructions[0].offset}

    for i, instr in enumerate(instructions):
        if instr.is_jumpdest:
            leaders.add(instr.offset)

        # The instruction after a terminator/branch starts a new block.
        if (
            instr.name in _TERMINATORS or instr.name in _BRANCHES
        ) and i + 1 < len(instructions):
            leaders.add(instructions[i + 1].offset)

    # A block that ends in a terminator must not also contain the instructions
    # after it, so split at every leader.

    # --- Create the blocks -----------------------------------------------
    ordered = sorted(leaders)
    for idx, start in enumerate(ordered):
        end = ordered[idx + 1] if idx + 1 < len(ordered) else instructions[-1].end_offset
        block_instructions = [i for i in instructions if start <= i.offset < end]
        if not block_instructions:
            continue
        terminator = block_instructions[-1].name
        block = Block(
            start=start,
            end=block_instructions[-1].end_offset,
            instructions=block_instructions,
            terminator=terminator,
        )
        cfg.blocks[start] = block

    # --- Resolve jump targets ---------------------------------------------
    index_by_offset = {instr.offset: i for i, instr in enumerate(instructions)}

    # Pass 1 uses the narrow "the push right before the jump" rule, so the
    # dataflow fixpoint has a graph to walk. Pass 2 refines the targets with
    # the full abstract stack simulation.
    heuristic: dict[int, int] = {}
    for instr in instructions:
        if instr.name in ("JUMP", "JUMPI"):
            value = _constant_push_before(instr, disassembly, index_by_offset)
            if value is not None:
                heuristic[instr.offset] = value

    # Imported here because the resolver depends on this module.
    from .resolver import resolve_jump_targets

    # The resolver's dataflow walks the CFG edges, and the CFG edges are
    # built from the resolver's own findings. That circularity has to be
    # broken by iterating: each round the resolver sees the edges the
    # previous round discovered, so a block that is only reachable through
    # a resolver-discovered jump finally receives a stack state.
    #
    # The target map only ever grows, so the loop converges; the round
    # cap is a safety net for pathological inputs.
    combined = dict(heuristic)
    for _ in range(_MAX_RESOLUTION_ROUNDS):
        cfg.edges = _build_edges(cfg, combined, jumpdest_offsets)
        resolved = resolve_jump_targets(disassembly, cfg)
        updated = dict(combined)
        updated.update(resolved)
        if updated == combined:
            break
        combined = updated
    cfg.edges = _build_edges(cfg, combined, jumpdest_offsets)

    for edge in cfg.edges:
        if edge.resolution is Resolution.UNRESOLVED:
            kind = "conditional" if edge.edge_type is EdgeType.CONDITIONAL_JUMP else "unconditional"
            cfg.notes.append(
                f"unresolved {kind} jump at offset {edge.instruction_offset}"
            )

    _mark_reachable(cfg)
    return cfg


def _build_edges(
    cfg: ControlFlowGraph, target_lookup: dict[int, int], jumpdest_offsets: set[int]
) -> list[Edge]:
    """Build the control-flow edges for ``cfg`` from a jump-target lookup."""
    edges: list[Edge] = []

    for block_start in sorted(cfg.blocks):
        block = cfg.blocks[block_start]
        last = block.instructions[-1]
        name = last.name

        if name == "JUMP":
            target = target_lookup.get(last.offset)
            if target is not None and target in jumpdest_offsets and target in cfg.blocks:
                edges.append(
                    Edge(
                        source=block_start,
                        target=target,
                        edge_type=EdgeType.UNCONDITIONAL_JUMP,
                        resolution=Resolution.INFERRED,
                        instruction_offset=last.offset,
                    )
                )
            else:
                edges.append(
                    Edge(
                        source=block_start,
                        target=None,
                        edge_type=EdgeType.UNRESOLVED,
                        resolution=Resolution.UNRESOLVED,
                        instruction_offset=last.offset,
                    )
                )

        elif name == "JUMPI":
            # The conditional branch: a taken edge to the constant target and
            # a fall-through edge to the next block.
            target = target_lookup.get(last.offset)
            if target is not None and target in jumpdest_offsets and target in cfg.blocks:
                edges.append(
                    Edge(
                        source=block_start,
                        target=target,
                        edge_type=EdgeType.CONDITIONAL_JUMP,
                        resolution=Resolution.INFERRED,
                        instruction_offset=last.offset,
                    )
                )
            else:
                edges.append(
                    Edge(
                        source=block_start,
                        target=None,
                        edge_type=EdgeType.UNRESOLVED,
                        resolution=Resolution.UNRESOLVED,
                        instruction_offset=last.offset,
                    )
                )

            fallthrough = _next_block_start(cfg, block_start)
            if fallthrough is not None:
                edges.append(
                    Edge(
                        source=block_start,
                        target=fallthrough,
                        edge_type=EdgeType.CONDITIONAL_FALLTHROUGH,
                        resolution=Resolution.RESOLVED,
                        instruction_offset=last.offset,
                    )
                )

        elif name in _TERMINATORS:
            edge_type = {
                "STOP": EdgeType.STOP,
                "RETURN": EdgeType.RETURN,
                "REVERT": EdgeType.REVERT,
                "INVALID": EdgeType.INVALID,
                "SELFDESTRUCT": EdgeType.SELFDESTRUCT,
            }[name]
            edges.append(
                Edge(
                    source=block_start,
                    target=None,
                    edge_type=edge_type,
                    resolution=Resolution.RESOLVED,
                    instruction_offset=last.offset,
                )
            )

        else:
            # Ordinary fall-through to the next block.
            fallthrough = _next_block_start(cfg, block_start)
            if fallthrough is not None:
                edges.append(
                    Edge(
                        source=block_start,
                        target=fallthrough,
                        edge_type=EdgeType.FALLTHROUGH,
                        resolution=Resolution.RESOLVED,
                        instruction_offset=last.offset,
                    )
                )

    return edges


def _mark_reachable(cfg: ControlFlowGraph) -> None:
    """Flag the blocks that are reachable from the entry point.

    Reachability follows every edge whose destination is known: resolved and
    inferred jumps, and the fall-through edges.

    An unresolved jump is a genuine dynamic transfer, so every ``JUMPDEST``
    block is treated as a potential target. That is the strongest statement
    the EVM allows: ``JUMP``/``JUMPI`` to a non-``JUMPDEST`` offset is an
    exceptional halt, so the target set of a dynamic jump is exactly the set
    of ``JUMPDEST`` blocks. Blocks that are *not* ``JUMPDEST``-headed are
    therefore unreachable, which is what lets the Solidity data segments
    (revert strings, guarded by ``INVALID``) be told apart from code.
    """
    if not cfg.blocks:
        return

    entry = cfg.entry_offset
    if entry not in cfg.blocks:
        # The entry offset is not a block leader (malformed input); fall back
        # to the lowest block.
        entry = min(cfg.blocks)

    jumpdest_blocks = {
        start
        for start, block in cfg.blocks.items()
        if block.instructions and block.instructions[0].is_jumpdest
    }

    reachable: set[int] = {entry}
    frontier: list[int] = [entry]

    while frontier:
        start = frontier.pop()
        for edge in cfg.edges:
            if edge.source != start:
                continue
            if edge.target is None:
                # A dynamic transfer: every JUMPDEST block is a candidate.
                for other in jumpdest_blocks:
                    if other not in reachable:
                        reachable.add(other)
                        frontier.append(other)
                continue
            if edge.target in cfg.blocks and edge.target not in reachable:
                reachable.add(edge.target)
                frontier.append(edge.target)

    for start, block in cfg.blocks.items():
        block.reachable = start in reachable

    unreachable = [b for b in cfg.blocks.values() if not b.reachable]
    if unreachable:
        total = sum(b.byte_size for b in unreachable)
        cfg.notes.append(
            f"{len(unreachable)} unreachable block(s) covering {total} byte(s); "
            "these are typically Solidity data segments (revert strings) rather "
            "than executable code"
        )


def _next_block_start(cfg: ControlFlowGraph, start: int) -> int | None:
    """Return the start offset of the block that follows ``start``."""
    later = [s for s in cfg.blocks if s > start]
    return min(later) if later else None
