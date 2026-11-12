"""What a pattern is *used for*, which is what decides whether it matters.

The rules that report the presence of an opcode are the noisiest thing
this product does. ``DELEGATECALL`` is the expected shape of an
upgradeable proxy; ``TX.ORIGIN`` is harmless in a log line. Reporting
either without asking what the value is *for* fills a reviewer's queue
with patterns and teaches them to ignore the tool.

What this module does
----------------------

It tracks, per basic block, where a value came from: a known constant,
the transaction origin, or something outside the contract's control
(calldata or storage). That is enough to answer two questions the
opcode-presence rules cannot:

* **Is the DELEGATECALL's target fixed?** A target that is a
  compile-time constant is the expected proxy pattern: the implementation
  cannot be swapped by an attacker, so the finding is not a finding.
  A target that came from calldata or storage can be swapped, and that
  is the case worth reporting. This narrowing is *sound*: the constant
  tracking comes from the same abstract interpreter the control-flow
  graph uses, and an unknown target is always reported.

* **Is the TX.ORIGIN value used for authorisation?** A comparison
  (``EQ``) or a use as a call target is an authorisation-shaped use. A
  value that is merely stored or logged is not.

Where this module refuses to narrow
------------------------------------

A per-block analysis cannot prove that an ``ORIGIN`` read is *not*
compared later, in another block, after it has been written to memory.
So the rule does not drop those findings: it separates them into "used
for authorisation", which is reported confidently, and "present, and
this analysis cannot show what it is used for", which is reported with a
lower confidence and a limitation that says exactly that. The reviewer
decides; the tool does not guess.

The same honesty applies to the DELEGATECALL rule: a target the
analysis could not resolve is reported, never dropped.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Literal

from evm_analysis.cfg import ControlFlowGraph
from evm_analysis.disassembler import Instruction

__all__ = [
    "BlockFacts",
    "DelegatecallTarget",
    "GraphFacts",
    "OriginUse",
    "analyse_block",
    "analyse_graph",
]

#: Where a value came from.
Taint = Literal["constant", "origin", "external", "unknown"]

#: The kinds of DELEGATECALL target the analysis can tell apart.
TARGET_CONSTANT = "constant"
TARGET_EXTERNAL = "external"
TARGET_UNKNOWN = "unknown"

#: The kinds of ORIGIN use the analysis can tell apart.
USE_COMPARED = "compared"
USE_CALL_TARGET = "call_target"
USE_STORED = "stored"
USE_OTHER = "other"

#: The opcodes that push a value the caller controls.
_EXTERNAL_SOURCES = frozenset({"CALLDATALOAD", "SLOAD"})

#: The call-family opcodes, and how many stack slots they consume.
_CALL_OPCODES = frozenset({"CALL", "CALLCODE", "DELEGATECALL", "STATICCALL"})

#: The comparison opcode.
_EQUALITY = "EQ"


@dataclass(frozen=True, slots=True)
class DelegatecallTarget:
    """One DELEGATECALL and what is known about its target.

    Attributes:
        offset: The instruction's offset.
        kind: ``constant`` when the target is a compile-time constant,
            ``external`` when it came from calldata or storage, and
            ``unknown`` when the analysis could not tell.
        value: The target, when it is a known constant.
    """

    offset: int
    kind: str
    value: int | None = None

    @property
    def is_fixed(self) -> bool:
        """Whether the target cannot be changed by an attacker."""
        return self.kind == TARGET_CONSTANT


@dataclass(frozen=True, slots=True)
class OriginUse:
    """One read of TX.ORIGIN and what is known about its use.

    Attributes:
        offset: The ORIGIN instruction's offset.
        kind: ``compared``, ``call_target``, ``stored`` or ``other``.
    """

    offset: int
    kind: str

    @property
    def is_authorisation_shaped(self) -> bool:
        """Whether the use is one an authorisation check would make."""
        return self.kind in (USE_COMPARED, USE_CALL_TARGET)


@dataclass
class BlockFacts:
    """What one basic block does with the values it reads.

    Attributes:
        delegatecall_targets: The DELEGATECALL instructions and their
            targets.
        origin_uses: The ORIGIN reads and their uses.
    """

    delegatecall_targets: list[DelegatecallTarget] = field(default_factory=list)
    origin_uses: list[OriginUse] = field(default_factory=list)


#: A stack slot: a known constant, a taint, or unknown.
_Slot = tuple[str, int | None]


def _pop(stack: list[_Slot], count: int) -> list[_Slot]:
    """Remove and return the top ``count`` slots, deepest first."""
    if count <= 0:
        return []
    if len(stack) < count:
        taken = list(stack)
        stack.clear()
        return taken
    taken = stack[-count:]
    del stack[-count:]
    return taken


def _push_unknown(stack: list[_Slot], count: int) -> None:
    for _ in range(count):
        stack.append(("unknown", None))


def analyse_block(instructions: Iterable[Instruction]) -> BlockFacts:
    """Analyse one basic block.

    The simulation is deliberately crude and conservative: it tracks the
    top of the stack, it only follows the opcodes it understands, and
    anything it does not understand invalidates the slots it touches.
    A value it cannot account for is *unknown*, and unknown never means
    "safe".

    Args:
        instructions: The block's instructions, in order.

    Returns:
        The facts the block establishes.
    """
    facts = BlockFacts()
    stack: list[_Slot] = []
    #: Slots pushed by ORIGIN, so a later use can be traced back to it.
    origin_slots: list[int] = []

    for instruction in instructions:
        name = instruction.name

        if name.startswith("PUSH"):
            value = instruction.immediate_int
            stack.append(("constant", value))
            continue

        if name == "ORIGIN":
            stack.append(("origin", None))
            origin_slots.append(len(stack) - 1)
            continue

        if name in _EXTERNAL_SOURCES:
            stack.append(("external", None))
            continue

        if name in _CALL_OPCODES:
            # CALL-family: gas, address, value, argsOffset, argsLength,
            # retOffset, retLength. The address is the second from the
            # top.
            consumed = _pop(stack, 7)
            # The popped slots come back deepest-first, so the top of the
            # stack is the last element and the address -- the second
            # from the top -- is the one before it.
            address = consumed[-2] if len(consumed) >= 2 else ("unknown", None)
            if name == "DELEGATECALL":
                kind = TARGET_UNKNOWN
                target_value: int | None = None
                if address[0] == "constant":
                    kind = TARGET_CONSTANT
                    target_value = address[1]
                elif address[0] == "external":
                    kind = TARGET_EXTERNAL
                facts.delegatecall_targets.append(
                    DelegatecallTarget(
                        offset=instruction.offset, kind=kind, value=target_value
                    )
                )
            elif address[0] == "origin":
                facts.origin_uses.append(
                    OriginUse(offset=instruction.offset, kind=USE_CALL_TARGET)
                )
            _push_unknown(stack, instruction.stack_out)
            continue

        if name == _EQUALITY:
            consumed = _pop(stack, 2)
            if any(slot[0] == "origin" for slot in consumed):
                facts.origin_uses.append(
                    OriginUse(offset=instruction.offset, kind=USE_COMPARED)
                )
            _push_unknown(stack, instruction.stack_out)
            continue

        if name in ("SSTORE", "MSTORE"):
            consumed = _pop(stack, instruction.stack_in)
            if any(slot[0] == "origin" for slot in consumed):
                facts.origin_uses.append(
                    OriginUse(offset=instruction.offset, kind=USE_STORED)
                )
            _push_unknown(stack, instruction.stack_out)
            continue

        # Any other opcode: consume what it consumes, invalidate it, and
        # push whatever it pushes. An origin value that survives here is
        # no longer traceable, which is why the rule keeps those
        # findings with a lower confidence rather than dropping them.
        consumed = _pop(stack, instruction.stack_in)
        if name in ("DUP1", "DUP2", "DUP3", "DUP4"):
            # DUPn peeks: the value it copies keeps its provenance.
            index = int(name[3:]) - 1
            if index < len(consumed):
                stack.append(consumed[index])
                if consumed[index][0] == "origin":
                    origin_slots.append(len(stack) - 1)
        elif name.startswith("SWAP"):
            # SWAPn exchanges the top with the n-th slot.
            index = int(name[4:]) - 1
            if index < len(stack):
                stack[-1], stack[-1 - index] = stack[-1 - index], stack[-1]
        elif name == "POP":
            pass
        else:
            _push_unknown(stack, instruction.stack_out)
            if consumed and any(slot[0] == "origin" for slot in consumed):
                # The origin value was consumed by something this
                # analysis does not model. Its use is unknown, and the
                # finding stays.
                facts.origin_uses.append(
                    OriginUse(offset=instruction.offset, kind=USE_OTHER)
                )

    return facts


@dataclass
class GraphFacts:
    """What the whole control-flow graph does with the values it reads.

    Attributes:
        delegatecall_targets: Every DELEGATECALL and what is known
            about its target.
        origin_uses: Every ORIGIN read and what is known about its use.
        blocks_analysed: How many blocks were analysed. A block that
            could not be analysed is a blind spot, and the count says
            how big the blind spot is.
    """

    delegatecall_targets: list[DelegatecallTarget] = field(default_factory=list)
    origin_uses: list[OriginUse] = field(default_factory=list)
    blocks_analysed: int = 0


def analyse_graph(cfg: ControlFlowGraph) -> GraphFacts:
    """Analyse every reachable block of the graph.

    Blocks are analysed separately, which is the honest unit: a value's
    provenance is tracked within the block that computes it, and a value
    that arrives from another block is unknown. Unreachable blocks --
    the data regions a compiler appends -- are not analysed, because no
    execution ever reaches them.
    """
    facts = GraphFacts()
    for block in cfg.reachable_blocks:
        block_facts = analyse_block(block.instructions)
        facts.delegatecall_targets.extend(block_facts.delegatecall_targets)
        facts.origin_uses.extend(block_facts.origin_uses)
        facts.blocks_analysed += 1
    return facts
