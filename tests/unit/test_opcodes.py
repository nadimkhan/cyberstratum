"""Tests for the fork-aware opcode table."""

from __future__ import annotations

import pytest
from evm_analysis.opcodes import (
    FORK_ORDER,
    INVALID_OPCODE,
    load_fork,
    normalize_fork,
    supported_forks,
)


def test_supported_forks_cover_the_documented_range() -> None:
    forks = supported_forks()
    assert forks[0] == "frontier"
    assert "cancun" in forks
    assert "prague" in forks
    assert set(forks) == set(FORK_ORDER)


@pytest.mark.parametrize("fork", FORK_ORDER)
def test_every_fork_has_core_opcodes_with_stack_effects(fork: str) -> None:
    table = load_fork(fork)
    # STOP, ADD, JUMP, JUMPDEST, RETURN, SELFDESTRUCT -- present since Frontier.
    for code in (0x00, 0x01, 0x56, 0x57, 0x5B, 0xF3, 0xFF):
        opcode = table.get(code)
        assert opcode is not None, f"{fork} missing 0x{code:02x}"
        assert opcode.stack_in >= 0
        assert opcode.stack_out >= 0

    # REVERT only exists from Byzantium (EIP-140) onwards.
    if fork in {"frontier", "homestead", "tangerine_whistle", "spurious_dragon"}:
        assert table.get(0xFD) is None
    else:
        assert table.get(0xFD) is not None


@pytest.mark.parametrize("fork", FORK_ORDER)
def test_invalid_opcode_is_never_a_valid_instruction(fork: str) -> None:
    table = load_fork(fork)
    assert table.get(INVALID_OPCODE) is None


def test_push_widths_are_explicit() -> None:
    table = load_fork("cancun")
    assert table.get(0x60).name == "PUSH1"
    assert table.get(0x60).push_bytes == 1
    assert table.get(0x7F).name == "PUSH32"
    assert table.get(0x7F).push_bytes == 32
    assert table.get(0x5F).name == "PUSH0"
    assert table.get(0x5F).push_bytes == 0


def test_fork_specific_opcode_introduction() -> None:
    """Opcodes must exist only in the forks that introduced them."""
    # PUSH0 arrived with Shanghai (EIP-3855).
    assert load_fork("frontier").get(0x5F) is None
    assert load_fork("london").get(0x5F) is None
    assert load_fork("shanghai").get(0x5F) is not None
    assert load_fork("cancun").get(0x5F) is not None

    # MCOPY arrived with Cancun (EIP-5656).
    assert load_fork("shanghai").get(0x5E) is None
    assert load_fork("cancun").get(0x5E) is not None

    # SHL/SHR arrived with Constantinople (EIP-145).
    assert load_fork("byzantium").get(0x1B) is None
    assert load_fork("constantinople").get(0x1B) is not None

    # REVERT arrived with Byzantium (EIP-140).
    assert load_fork("frontier").get(0xFD) is None
    assert load_fork("byzantium").get(0xFD) is not None

    # BASEFEE arrived with London (EIP-3198).
    assert load_fork("berlin").get(0x48) is None
    assert load_fork("london").get(0x48) is not None


def test_opcode_sets_grow_monotonically_across_forks() -> None:
    previous: set[int] = set()
    for fork in FORK_ORDER:
        codes = set(load_fork(fork).opcodes)
        assert previous <= codes, f"{fork} dropped opcodes present in an earlier fork"
        previous = codes


def test_petersburg_matches_constantinople_opcodes() -> None:
    """Petersburg only reverted EIP-1283 (gas metering), not the opcode set."""
    assert set(load_fork("petersburg").opcodes) == set(load_fork("constantinople").opcodes)


def test_known_stack_effects() -> None:
    table = load_fork("cancun")
    assert (table.get(0x01).stack_in, table.get(0x01).stack_out) == (2, 1)  # ADD
    assert (table.get(0x56).stack_in, table.get(0x56).stack_out) == (1, 0)  # JUMP
    assert (table.get(0x57).stack_in, table.get(0x57).stack_out) == (2, 0)  # JUMPI
    assert (table.get(0xF1).stack_in, table.get(0xF1).stack_out) == (7, 1)  # CALL
    assert (table.get(0x55).stack_in, table.get(0x55).stack_out) == (2, 0)  # SSTORE
    assert (table.get(0x5F).stack_in, table.get(0x5F).stack_out) == (0, 1)  # PUSH0
    assert (table.get(0x60).stack_in, table.get(0x60).stack_out) == (0, 1)  # PUSH1


def test_unsupported_fork_raises() -> None:
    with pytest.raises(ValueError, match="unsupported EVM fork"):
        load_fork("atlantis")


def test_normalize_fork_is_tolerant() -> None:
    assert normalize_fork("Cancun") == "cancun"
    assert normalize_fork(" tangerine-whistle ") == "tangerine_whistle"
    with pytest.raises(ValueError):
        normalize_fork("nope")
