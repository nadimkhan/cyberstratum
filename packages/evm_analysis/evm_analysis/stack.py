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

This module implements a small abstract interpreter that tracks the known
constants on the stack. The lattice is deliberately crude but sound:

* a stack slot holds either a known constant or ``None`` (unknown);
* any instruction that is not a recognised push/duplicate/swap/pop
  invalidates the slots it consumes and produces unknown slots.

The stack is modelled as a **top-anchored window**: ``stack[-1]`` is the
top of the EVM stack and ``stack[0]`` is the deepest element still tracked.
Only a jump's destination matters, and that is the top of the stack, so the
window is all the analysis needs.

The absolute stack depth is deliberately *not* tracked. ``solc`` joins paths
that reach one block with different stack heights -- the "calldata too
short" path and the "no selector matched" path meet at the same JUMPDEST
with different stacks -- so an absolute depth is unknowable for most blocks,
and gating the analysis on it would throw away jumps that are in fact
statically determinable.

DUPn and SWAPn use their *legacy* EVM semantics: they peek at the stack
instead of consuming it. EIP-5450 (EOF) redefines them to consume their
operands, which is correct for EOF but not for the deployed legacy
bytecode this project analyses.

The result is a resolved target for most statically determinable branches,
and an explicit "unresolved" answer for the rest -- never a guess.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .disassembler import Instruction

#: A stack slot: a known constant, or ``None`` when the value is unknown.
Slot = int | None

#: The abstract stack at a program point, top-anchored (last item = top).
Stack = list[Slot]


@dataclass(slots=True)
class BlockSimulation:
    """The result of simulating one basic block."""

    slots: Stack = field(default_factory=list)
    """Known constants per stack slot on entry (top-anchored)."""

    jump_targets: dict[int, int] = field(default_factory=dict)
    """Resolved jump destinations, keyed by the offset of the jump instruction."""

    exit_slots: Stack = field(default_factory=list)
    """Known constants per stack slot on exit (top-anchored)."""


def _apply(instruction: Instruction, stack: Stack) -> Stack:
    """Apply one instruction to the top-anchored abstract stack."""
    name = instruction.name
    stack_in = instruction.stack_in
    stack_out = instruction.stack_out

    if instruction.is_push:
        stack.append(instruction.immediate_int)
        return stack

    if name.startswith("DUP") and name[3:].isdigit():
        index = int(name[3:])
        # DUPn duplicates the n-th item from the top. It is only known when
        # that item is inside the tracked window.
        stack.append(stack[-index] if len(stack) >= index else None)
        return stack

    if name.startswith("SWAP") and name[4:].isdigit():
        index = int(name[4:])
        # SWAPn exchanges the top item with the (n+1)-th item from the top.
        if len(stack) >= index + 1:
            stack[-1], stack[-(index + 1)] = stack[-(index + 1)], stack[-1]
        else:
            # The partner of the swap is below the tracked window, so the
            # new top is unknown and the old top leaves the window.
            stack = [None] * max(0, len(stack) - 1)
        return stack

    if name == "POP":
        if stack:
            stack.pop()
        return stack

    # Generic handling: consume `stack_in` slots, produce `stack_out` unknown
    # slots. When the window holds fewer items than the instruction consumes,
    # the new top is unknown and the window is cleared.
    if stack_in:
        stack = stack[: len(stack) - stack_in] if len(stack) >= stack_in else []
    if stack_out:
        stack.extend([None] * stack_out)
    return stack


def simulate_block(instructions: list[Instruction], entry_slots: Stack) -> BlockSimulation:
    """Simulate one basic block.

    ``entry_slots`` is the top-anchored window known on entry to the block.
    """
    result = BlockSimulation(slots=list(entry_slots))

    stack: Stack = list(entry_slots)

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
            consumed = 2 if name == "JUMPI" else 1
            stack = stack[:-consumed] if len(stack) >= consumed else []
            continue

        stack = _apply(instruction, stack)

    result.exit_slots = stack
    return result
