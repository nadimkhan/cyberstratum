"""Abstract stack simulation for static jump-target resolution.

The first cut of the CFG builder resolved a jump target by looking at the
instruction immediately before the jump: if it was a ``PUSHn``, the pushed
value was taken as the destination. That rule matches the compiler output of
``solc`` for the simple cases, but it misses the equally common patterns
where the destination is shuffled around the stack before the branch:

    PUSH2 <target>   ; the destination
    DUP2             ; duplicate it
    JUMPI

Here the destination is on top of the stack at the branch, but it is not the
instruction immediately before the branch.

This module implements a small abstract interpreter that tracks the stack
*shape* and the *known constants* on it. The lattice is deliberately crude
but sound:

* the stack depth is tracked exactly where it can be derived, and is
  ``unknown`` where two paths disagree;
* a stack slot holds either a known constant or ``None`` (unknown);
* any instruction that is not a recognised push/duplicate/swap/pop
  invalidates the slots it consumes and produces unknown slots.

The result is a resolved target for most statically determinable branches,
and an explicit "unresolved" answer for the rest -- never a guess.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .disassembler import Instruction

#: A stack slot: a known constant, or ``None`` when the value is unknown.
Slot = int | None

#: The abstract stack at a program point, bottom slot first.
Stack = list[Slot]

#: Sentinel for an unknown stack depth.
UNKNOWN_DEPTH = -1


@dataclass(slots=True)
class BlockSimulation:
    """The result of simulating one basic block."""

    entry_depth: int = UNKNOWN_DEPTH
    """Modelled stack depth on entry to the block."""

    slots: Stack = field(default_factory=list)
    """Known constants per stack slot on entry (bottom slot first)."""

    jump_targets: dict[int, int] = field(default_factory=dict)
    """Resolved jump destinations, keyed by the offset of the jump instruction."""

    exit_depth: int = UNKNOWN_DEPTH
    """Modelled stack depth on exit from the block."""

    exit_slots: Stack = field(default_factory=list)
    """Known constants per stack slot on exit."""


def _apply(instruction: Instruction, stack: Stack) -> Stack:
    """Apply one instruction to the abstract stack.

    The stack is a list of slots, bottom first. ``None`` marks an unknown
    value.
    """
    name = instruction.name
    stack_in = instruction.stack_in
    stack_out = instruction.stack_out

    if instruction.is_push:
        stack.append(instruction.immediate_int)
        return stack

    if name.startswith("DUP") and name[3:].isdigit():
        index = int(name[3:])
        if len(stack) >= index:
            stack.append(stack[-index])
        else:
            stack.append(None)
        return stack

    if name.startswith("SWAP") and name[4:].isdigit():
        index = int(name[4:])
        if len(stack) >= index:
            stack[-1], stack[-index] = stack[-index], stack[-1]
        return stack

    if name == "POP":
        if stack:
            stack.pop()
        return stack

    # Generic handling: consume `stack_in` slots, produce `stack_out` unknown
    # slots. If the modelled depth is too shallow the whole stack becomes
    # untrustworthy, so it is cleared rather than silently mis-modelled.
    if len(stack) < stack_in:
        return []

    if stack_in:
        del stack[len(stack) - stack_in :]
    if stack_out:
        stack.extend([None] * stack_out)
    return stack


def simulate_block(
    instructions: list[Instruction], entry_depth: int, entry_slots: Stack
) -> BlockSimulation:
    """Simulate one basic block.

    ``entry_depth`` is the modelled stack depth on entry; ``UNKNOWN_DEPTH``
    means the depth is not known, in which case only the instructions that
    push their own values can be tracked reliably.
    """
    result = BlockSimulation(entry_depth=entry_depth, slots=list(entry_slots))

    stack: Stack = list(entry_slots) if entry_depth != UNKNOWN_DEPTH else []

    for instruction in instructions:
        name = instruction.name

        if name in ("JUMP", "JUMPI"):
            # The destination is the top of the stack (Yellow Paper: for
            # JUMPI, ``mu_s[0]`` is the destination and ``mu_s[1]`` is the
            # condition).
            if stack:
                destination = stack[-1]
                if destination is not None:
                    result.jump_targets[instruction.offset] = destination
            # The branch consumes the destination (and, for JUMPI, the
            # condition) from the stack.
            stack = stack[:-2] if name == "JUMPI" else stack[:-1]
            continue

        stack = _apply(instruction, stack)

    result.exit_depth = len(stack)
    result.exit_slots = stack
    return result
