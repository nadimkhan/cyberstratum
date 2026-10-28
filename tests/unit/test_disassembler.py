"""Tests for the disassembler."""

from __future__ import annotations

import pytest
from evm_analysis.disassembler import InstructionStatus, disassemble
from evm_analysis.opcodes import load_fork


@pytest.fixture(scope="module")
def cancun():
    return load_fork("cancun")


def test_empty_code(cancun) -> None:
    result = disassemble(b"", cancun)
    assert result.instructions == []
    assert result.code_size == 0


def test_single_stop(cancun) -> None:
    result = disassemble(bytes.fromhex("00"), cancun)
    assert len(result.instructions) == 1
    instr = result.instructions[0]
    assert instr.offset == 0
    assert instr.name == "STOP"
    assert instr.size == 1
    assert instr.status is InstructionStatus.OK


def test_push_immediate_is_preserved(cancun) -> None:
    # PUSH1 0x2a
    result = disassemble(bytes.fromhex("602a"), cancun)
    assert len(result.instructions) == 1
    instr = result.instructions[0]
    assert instr.name == "PUSH1"
    assert instr.immediate == b"\x2a"
    assert instr.immediate_int == 42
    assert instr.size == 2
    assert instr.end_offset == 2


def test_push32_immediate_is_preserved(cancun) -> None:
    code = bytes.fromhex("7f" + "ff" * 32)
    result = disassemble(code, cancun)
    instr = result.instructions[0]
    assert instr.name == "PUSH32"
    assert len(instr.immediate) == 32
    assert instr.size == 33


def test_push0_has_no_immediate(cancun) -> None:
    result = disassemble(bytes.fromhex("5f"), cancun)
    instr = result.instructions[0]
    assert instr.name == "PUSH0"
    assert instr.immediate == b""
    assert instr.size == 1


def test_offsets_are_absolute(cancun) -> None:
    # PUSH1 0x01, PUSH1 0x02, ADD
    result = disassemble(bytes.fromhex("6001600201"), cancun)
    assert [i.offset for i in result.instructions] == [0, 2, 4]
    assert [i.name for i in result.instructions] == ["PUSH1", "PUSH1", "ADD"]


def test_truncated_push_is_reported(cancun) -> None:
    # PUSH32 with only 2 immediate bytes available.
    result = disassemble(bytes.fromhex("7fdead"), cancun)
    instr = result.instructions[0]
    assert instr.status is InstructionStatus.TRUNCATED_IMMEDIATE
    assert instr.immediate == b"\xde\xad"
    assert instr.size == 3
    assert result.is_truncated
    assert any("truncated" in w for w in result.warnings)


def test_unknown_opcode_for_old_fork() -> None:
    """PUSH0 is invalid on London, so it must be flagged, not decoded."""
    london = load_fork("london")
    result = disassemble(bytes.fromhex("5f"), london)
    instr = result.instructions[0]
    assert instr.status is InstructionStatus.UNKNOWN_OPCODE
    assert instr.name == "INVALID"
    assert result.has_unknown_opcodes


def test_invalid_opcode_is_flagged(cancun) -> None:
    result = disassemble(bytes.fromhex("fe"), cancun)
    instr = result.instructions[0]
    assert instr.status is InstructionStatus.INVALID_OPCODE
    assert instr.name == "INVALID"
    assert instr.terminating


def test_disassembly_continues_after_invalid_byte(cancun) -> None:
    result = disassemble(bytes.fromhex("fe6001"), cancun)
    assert [i.name for i in result.instructions] == ["INVALID", "PUSH1"]


def test_histogram_and_ngrams(cancun) -> None:
    result = disassemble(bytes.fromhex("600160020100"), cancun)
    histogram = result.opcode_histogram()
    assert histogram["PUSH1"] == 2
    assert histogram["ADD"] == 1
    assert histogram["STOP"] == 1

    trigrams = result.ngrams(3)
    assert len(trigrams) == len(result.instructions) - 2
    assert trigrams[0] == ("PUSH1", "PUSH1", "ADD")


def test_ngrams_of_size_one(cancun) -> None:
    result = disassemble(bytes.fromhex("6001"), cancun)
    assert result.ngrams(1) == [("PUSH1",)]


def test_ngrams_rejects_zero(cancun) -> None:
    result = disassemble(bytes.fromhex("6001"), cancun)
    with pytest.raises(ValueError):
        result.ngrams(0)


def test_rejects_non_bytes() -> None:
    with pytest.raises(TypeError):
        disassemble("6001", load_fork("cancun"))  # type: ignore[arg-type]


def test_jumpdest_listing(cancun) -> None:
    # JUMPDEST, STOP, JUMPDEST
    result = disassemble(bytes.fromhex("5b005b"), cancun)
    assert result.jumpdests == [0, 2]
