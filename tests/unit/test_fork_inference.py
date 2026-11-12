"""Tests for fork inference.

The point of the module under test is that it never guesses: it either
places the bytecode in a fork from the vendored tables or it says it
cannot.
"""

from __future__ import annotations

import pytest

from evm_analysis.fork_inference import (
    first_appearance,
    fork_index,
    infer_required_fork,
)
from evm_analysis.opcodes import load_fork, supported_forks

#: A contract body that uses nothing newer than the earliest forks.
PLAIN = bytes.fromhex("60016000556002600155")  # PUSH1 01 PUSH1 00 SSTORE PUSH1 02 PUSH1 01 SSTORE

#: PUSH0 (0x5f) arrived in Shanghai.
PUSH0 = bytes.fromhex("5f60005260016000f3")  # PUSH0 PUSH1 00 MSTORE PUSH1 01 PUSH1 00 RETURN

#: TSTORE (0x5d) arrived in Cancun. TLOAD is 0x5c; they are neighbours.
TSTORE = bytes.fromhex("600160005d60006000f3")  # PUSH1 01 PUSH1 00 TSTORE PUSH1 00 PUSH1 00 RETURN

#: MCOPY (0x5e) also arrived in Cancun.
MCOPY = bytes.fromhex("6000600060005e60006000f3")

#: A byte no fork defines (0x0c is not an EVM opcode).
UNKNOWN_BYTE = bytes.fromhex("60000c")


def test_a_plain_contract_is_placed_in_the_earliest_fork():
    requirement = infer_required_fork(PLAIN)
    assert requirement.required_fork == "frontier"
    assert requirement.is_analysable
    assert requirement.unknown_opcodes == ()


def test_push0_raises_the_floor_to_shanghai():
    requirement = infer_required_fork(PUSH0)
    assert requirement.required_fork == "shanghai"
    assert requirement.newest_opcode == "PUSH0"
    assert requirement.newest_opcode_byte == 0x5F
    assert not requirement.conflict


def test_tstore_raises_the_floor_to_cancun():
    requirement = infer_required_fork(TSTORE)
    assert requirement.required_fork == "cancun"
    assert requirement.newest_opcode == "TSTORE"


def test_mcopy_raises_the_floor_to_cancun():
    requirement = infer_required_fork(MCOPY)
    assert requirement.required_fork == "cancun"
    assert requirement.newest_opcode == "MCOPY"


def test_push_immediates_are_not_mistaken_for_opcodes():
    """``PUSH1 0x5f`` is data, not the PUSH0 opcode."""
    push_one_5f = bytes.fromhex("605f600052")
    requirement = infer_required_fork(push_one_5f)
    assert requirement.required_fork == "frontier"
    assert 0x5F not in requirement.opcodes_used


def test_a_byte_no_fork_defines_is_reported_not_hidden():
    requirement = infer_required_fork(UNKNOWN_BYTE)
    assert requirement.unknown_opcodes == (0x0C,)
    assert not requirement.is_analysable
    # The floor is still computed from the opcodes that *are* known, but
    # the code cannot be placed because one byte belongs to no fork.
    assert requirement.required_fork == "frontier"
    assert 0x0C not in requirement.opcodes_used


def test_a_cap_older_than_the_floor_is_a_conflict():
    requirement = infer_required_fork(TSTORE, cap="london")
    assert requirement.conflict
    assert requirement.required_fork == "cancun"


def test_a_cap_newer_than_the_floor_is_not_a_conflict():
    requirement = infer_required_fork(PUSH0, cap="cancun")
    assert not requirement.conflict


def test_the_first_appearance_map_agrees_with_the_tables():
    first = first_appearance()
    for fork in supported_forks():
        table = load_fork(fork)
        for code in range(256):
            if code in table:
                assert fork_index(first[code]) <= fork_index(fork)
                break


def test_the_requirement_serialises_for_the_scan_record():
    requirement = infer_required_fork(PUSH0)
    payload = requirement.as_dict()
    assert payload["required_fork"] == "shanghai"
    assert payload["opcode_count"] > 0
    assert payload["unknown_opcodes"] == []
    assert payload["conflict"] is False


@pytest.mark.parametrize("code", [PLAIN, PUSH0, TSTORE, MCOPY, UNKNOWN_BYTE])
def test_inference_is_deterministic(code: bytes):
    first = infer_required_fork(code)
    second = infer_required_fork(code)
    assert first == second
