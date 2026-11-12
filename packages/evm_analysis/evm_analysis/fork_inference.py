"""Infer the earliest fork that can execute a given runtime bytecode.

Why this exists
---------------

A chain is not a fork, and the two are easy to confuse. ``cancun`` is a
reasonable guess for Ethereum mainnet and a wrong one for a chain that
predates Shanghai, for zkSync, which is not an EVM at all, and for the
majority of the chains a discovery feed now finds.

Two facts make the problem tractable:

* A contract that is verified as deployed on a chain must be executable
  on that chain. So the opcodes its runtime bytecode uses are a lower
  bound on the chain's fork: if the code contains ``PUSH0`` (Shanghai),
  the chain is at least Shanghai.
* The opcode tables in :mod:`evm_analysis.opcodes` are ordered from
  ``frontier`` to ``prague``, and every opcode's first appearance is
  known. The lowest fork whose table contains every opcode the code uses
  is therefore the minimum fork that could execute it.

That minimum is a *floor*, not an answer. It says nothing about
opcodes the chain has but the contract does not use, and it says nothing
about semantics that changed without changing the opcode set. So the
inference is used for two things, and only two:

* as a **cross-check** on a chain's declared fork -- a contract whose
  floor is above the chain's declared fork is a contradiction, and a
  contradiction is worth reporting rather than analysing quietly;
* as the **analysis fork** for chains whose declared fork is unknown,
  marked as inferred so that it can be excluded from anything that
  depends on exact chain semantics.

Both uses are deterministic and need no network access.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from .disassembler import InstructionStatus, disassemble
from .opcodes import ForkTable, load_fork, supported_forks

__all__ = [
    "ForkRequirement",
    "first_appearance",
    "fork_index",
    "infer_required_fork",
]


def fork_index(fork: str) -> int:
    """Position of ``fork`` in the supported order, or -1 when unknown."""
    try:
        return supported_forks().index(fork)
    except ValueError:
        return -1


@lru_cache(maxsize=1)
def first_appearance() -> dict[int, str]:
    """Map every known opcode byte to the earliest fork that defines it.

    The map is built once from the vendored fork tables, so it cannot
    drift from the tables the disassembler uses.
    """
    first: dict[int, str] = {}
    for fork in supported_forks():
        table = load_fork(fork)
        for code in range(256):
            if code in table and code not in first:
                first[code] = fork
    return first


@dataclass(frozen=True, slots=True)
class ForkRequirement:
    """What the bytecode says about the fork it needs.

    Attributes:
        required_fork: The lowest supported fork whose opcode table
            contains every opcode the code uses *that any fork defines*.
            When the code contains a byte no fork defines, the floor is
            computed from the rest and ``is_analysable`` is False: the
            code cannot be placed in the table at all.
        opcodes_used: The opcode bytes the code uses.
        newest_opcode: Canonical name of the most recent opcode used.
        newest_opcode_byte: Its opcode byte, if any.
        unknown_opcodes: Bytes that no supported fork defines. Their
            presence means the code cannot be analysed against the
            vendored tables at all.
        conflict: True when the required fork is newer than a declared
            cap passed by the caller, which means the contract cannot
            execute on the chain the cap describes.
    """

    required_fork: str
    opcodes_used: frozenset[int]
    newest_opcode: str
    newest_opcode_byte: int | None
    unknown_opcodes: tuple[int, ...]
    conflict: bool = False

    @property
    def is_analysable(self) -> bool:
        """Whether the code can be decoded against the vendored tables."""
        return not self.unknown_opcodes

    def as_dict(self) -> dict[str, object]:
        """A JSON-friendly view, for the scan record and the report."""
        return {
            "required_fork": self.required_fork,
            "newest_opcode": self.newest_opcode,
            "newest_opcode_byte": self.newest_opcode_byte,
            "opcode_count": len(self.opcodes_used),
            "unknown_opcodes": [f"0x{code:02x}" for code in self.unknown_opcodes],
            "conflict": self.conflict,
        }


def _opcodes(code: bytes) -> tuple[frozenset[int], tuple[int, ...]]:
    """Return the opcodes the code uses and the bytes no fork defines.

    The walk is done with the newest fork's table so that a byte which
    exists nowhere is not mistaken for an opcode. Immediate data of
    ``PUSHn`` is skipped by the disassembler, which is what keeps a
    ``PUSH1 0x5f`` from being read as the ``PUSH0`` opcode.
    """
    newest = supported_forks()[-1]
    disassembly = disassemble(code, load_fork(newest))
    used: set[int] = set()
    unknown: set[int] = set()
    for instruction in disassembly.instructions:
        if instruction.status is InstructionStatus.OK:
            used.add(instruction.opcode)
        elif instruction.status is InstructionStatus.UNKNOWN_OPCODE:
            unknown.add(instruction.opcode)
    return frozenset(used), tuple(sorted(unknown))


def infer_required_fork(code: bytes, *, cap: str | None = None) -> ForkRequirement:
    """Infer the earliest fork that could execute ``code``.

    Args:
        code: The runtime bytecode, metadata trailer included. The
            trailer is CBOR, not code, so it is ignored by the
            disassembler's instruction walk only to the extent that the
            walk stops at invalid bytes; callers that care should split
            the metadata first.
        cap: The fork a chain is declared to support. When the
            inferred floor is newer than the cap, ``conflict`` is set.

    Returns:
        A :class:`ForkRequirement`. When the code contains bytes no fork
        defines, the floor is still reported for the opcodes that are
        known, and ``is_analysable`` is False so that no caller treats
        the floor as a placement.
    """
    forks = supported_forks()
    used, unknown = _opcodes(code)

    required = forks[-1]
    for fork in forks:
        table: ForkTable = load_fork(fork)
        if all(opcode in table for opcode in used):
            required = fork
            break

    first = first_appearance()
    newest_byte: int | None = None
    newest_name = ""
    for opcode in used:
        appearance = first.get(opcode)
        if appearance is None:
            continue
        if newest_byte is None or fork_index(appearance) > fork_index(first[newest_byte]):
            newest_byte = opcode
            newest_name = _name_for(appearance, opcode)

    conflict = False
    if cap is not None:
        cap_position = fork_index(cap)
        if cap_position >= 0 and fork_index(required) > cap_position:
            conflict = True

    return ForkRequirement(
        required_fork=required,
        opcodes_used=used,
        newest_opcode=newest_name,
        newest_opcode_byte=newest_byte,
        unknown_opcodes=unknown,
        conflict=conflict,
    )


def _name_for(fork: str, opcode: int) -> str:
    """The canonical name of ``opcode`` in ``fork``."""
    table = load_fork(fork)
    entry = table.get(opcode)
    if entry is None:
        return f"0x{opcode:02x}"
    return entry.name
