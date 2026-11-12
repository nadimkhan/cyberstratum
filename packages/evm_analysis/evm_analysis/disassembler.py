"""EVM bytecode tokenizer / disassembler.

Design rules (from the technical design doc, §6.2 and §6.3):

* Tokenize *decoded instructions*, not raw hex bytes.
* Preserve each instruction's byte offset, opcode name and immediate bytes.
* Byte offsets are absolute within the contract runtime code.
* The disassembly is deterministic and fork-aware: an opcode that does not
  exist in the target fork is reported as ``invalid`` rather than silently
  decoded.
* Truncated ``PUSH`` immediates at the end of the code are reported rather
  than dropped, because a truncated push changes the meaning of everything
  after it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from .metadata import MetadataRegion, detect_solidity_metadata
from .opcodes import INVALID_OPCODE, ForkTable, Opcode


class InstructionStatus(StrEnum):
    """Why an instruction could not be fully decoded."""

    OK = "ok"
    #: The opcode byte does not exist in the target fork.
    UNKNOWN_OPCODE = "unknown_opcode"
    #: A ``PUSH`` immediate ran past the end of the code.
    TRUNCATED_IMMEDIATE = "truncated_immediate"
    #: The designated invalid opcode (0xFE) was reached.
    INVALID_OPCODE = "invalid_opcode"


@dataclass(frozen=True, slots=True)
class Instruction:
    """A single decoded EVM instruction."""

    offset: int
    """Absolute byte offset of the opcode within the runtime code."""

    opcode: int
    """The opcode byte."""

    name: str
    """Canonical opcode name for the target fork (``PUSH1``, ``JUMP``, ...)."""

    immediate: bytes
    """Immediate data for ``PUSHn``; empty for every other opcode."""

    size: int
    """Total size in bytes: the opcode byte plus any immediate."""

    stack_in: int
    stack_out: int
    terminating: bool
    status: InstructionStatus

    @property
    def end_offset(self) -> int:
        """Offset one past the last byte of this instruction."""
        return self.offset + self.size

    @property
    def is_push(self) -> bool:
        return self.name.startswith("PUSH")

    @property
    def is_jumpdest(self) -> bool:
        return self.name == "JUMPDEST"

    @property
    def is_jump(self) -> bool:
        return self.name in {"JUMP", "JUMPI"}

    @property
    def stack_delta(self) -> int:
        return self.stack_out - self.stack_in

    @property
    def immediate_int(self) -> int | None:
        """The immediate as an integer, or ``None`` for non-push instructions."""
        if not self.immediate:
            return None
        return int.from_bytes(self.immediate, "big")


@dataclass(slots=True)
class Disassembly:
    """The result of disassembling a blob of runtime code."""

    instructions: list[Instruction] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    """Observations that are not defects.

    A note says what was found without implying that something went
    wrong: the metadata trailer of a compiler-produced contract, for
    instance, is data that is correctly left undecoded. Only a *warning*
    means that part of the code could not be analysed.
    """
    fork: str = ""
    code_size: int = 0
    metadata: MetadataRegion | None = None
    """The detected Solidity metadata trailer, if the code carried one."""

    @property
    def executable_size(self) -> int:
        """Size of the executable code, excluding any metadata trailer."""
        if self.metadata is None:
            return self.code_size
        return self.metadata.start_offset

    @property
    def jumpdests(self) -> list[int]:
        """Offsets of valid ``JUMPDEST`` instructions."""
        return [i.offset for i in self.instructions if i.is_jumpdest]

    @property
    def is_truncated(self) -> bool:
        return any(i.status is InstructionStatus.TRUNCATED_IMMEDIATE for i in self.instructions)

    @property
    def has_unknown_opcodes(self) -> bool:
        return any(i.status is InstructionStatus.UNKNOWN_OPCODE for i in self.instructions)

    def instruction_at(self, offset: int) -> Instruction | None:
        """Return the instruction starting at ``offset``, if any."""
        for instr in self.instructions:
            if instr.offset == offset:
                return instr
        return None

    def opcode_histogram(self) -> dict[str, int]:
        """Counts per opcode name."""
        counts: dict[str, int] = {}
        for instr in self.instructions:
            counts[instr.name] = counts.get(instr.name, 0) + 1
        return counts

    def ngrams(self, n: int = 3) -> list[tuple[str, ...]]:
        """Contiguous opcode-name n-grams over the instruction stream."""
        if n < 1:
            raise ValueError("n must be >= 1")
        names = [i.name for i in self.instructions]
        if len(names) < n:
            return []
        return [tuple(names[i : i + n]) for i in range(len(names) - n + 1)]


def disassemble(code: bytes, table: ForkTable, *, detect_metadata: bool = True) -> Disassembly:
    """Disassemble ``code`` using the opcode set of ``table``.

    The disassembly always runs to the end of the *executable* code. When a
    Solidity metadata trailer is detected, decoding stops at the start of that
    trailer: the trailer is data, not code, and decoding it would invent
    instructions that the EVM would never execute. The trailer is still
    reported through :attr:`Disassembly.metadata` and the original bytes are
    never modified.

    Malformed regions are represented by instructions with a non-``OK`` status
    so the caller can see exactly where the bytecode became invalid.
    """
    if not isinstance(code, (bytes, bytearray, memoryview)):
        raise TypeError(f"expected bytes-like code, got {type(code).__name__}")
    code = bytes(code)

    result = Disassembly(fork=table.fork, code_size=len(code))
    offset = 0
    length = len(code)

    if detect_metadata:
        region = detect_solidity_metadata(code)
        if region is not None:
            result.metadata = region
            length = region.start_offset
            result.notes.append(
                f"solidity metadata detected at offset {region.start_offset} "
                f"({region.length} bytes); not decoded as instructions"
            )

    pending_invalid: list[int] = []
    while offset < length:
        opcode_byte = code[offset]
        opcode: Opcode | None = table.get(opcode_byte)

        if opcode_byte == INVALID_OPCODE:
            # The designated invalid opcode: a valid encoding that is invalid
            # by definition. It is deliberately absent from every fork's
            # opcode table, so this check must come before the "unknown in
            # this fork" check below.
            result.instructions.append(
                Instruction(
                    offset=offset,
                    opcode=opcode_byte,
                    name="INVALID",
                    immediate=b"",
                    size=1,
                    stack_in=0,
                    stack_out=0,
                    terminating=True,
                    status=InstructionStatus.INVALID_OPCODE,
                )
            )
            pending_invalid.append(offset)
            offset += 1
            continue

        if opcode is None:
            # Unknown in this fork. Record it as an invalid one-byte
            # instruction and keep going so the rest of the code is still
            # visible in the disassembly view.
            result.instructions.append(
                Instruction(
                    offset=offset,
                    opcode=opcode_byte,
                    name="INVALID",
                    immediate=b"",
                    size=1,
                    stack_in=0,
                    stack_out=0,
                    terminating=True,
                    status=InstructionStatus.UNKNOWN_OPCODE,
                )
            )
            result.warnings.append(
                f"opcode 0x{opcode_byte:02x} at offset {offset} does not exist in fork "
                f"{table.fork!r}"
            )
            offset += 1
            continue

        if opcode.push_bytes:
            available = length - (offset + 1)
            take = min(opcode.push_bytes, available)
            immediate = code[offset + 1 : offset + 1 + take]
            truncated = take < opcode.push_bytes
            result.instructions.append(
                Instruction(
                    offset=offset,
                    opcode=opcode_byte,
                    name=opcode.name,
                    immediate=immediate,
                    size=1 + take,
                    stack_in=opcode.stack_in,
                    stack_out=opcode.stack_out,
                    terminating=opcode.terminating,
                    status=(
                        InstructionStatus.TRUNCATED_IMMEDIATE if truncated else InstructionStatus.OK
                    ),
                )
            )
            if truncated:
                result.warnings.append(
                    f"truncated {opcode.name} immediate at offset {offset}: "
                    f"expected {opcode.push_bytes} bytes, found {take}"
                )
            offset += 1 + take
            continue

        result.instructions.append(
            Instruction(
                offset=offset,
                opcode=opcode_byte,
                name=opcode.name,
                immediate=b"",
                size=1,
                stack_in=opcode.stack_in,
                stack_out=opcode.stack_out,
                terminating=opcode.terminating,
                status=InstructionStatus.OK,
            )
        )
        offset += 1

    # The designated invalid opcode is a defect in the code -- except when
    # the compiler put it there on purpose. Solidity ends a contract's
    # runtime with a guard byte immediately before the metadata trailer,
    # so an invalid opcode exactly there is the guard, not a mistake.
    for invalid_offset in pending_invalid:
        if result.metadata is not None and invalid_offset == result.metadata.start_offset - 1:
            result.notes.append(
                f"solidity guard byte (INVALID) at offset {invalid_offset}, "
                "immediately before the metadata trailer"
            )
        else:
            result.warnings.append(f"invalid opcode at offset {invalid_offset}")

    return result
