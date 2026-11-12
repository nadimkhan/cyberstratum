"""Tests for the context analysis that gates the noisy rules.

The point of these tests is what the analysis *refuses* to conclude.
An analysis that cannot tell a fixed target from an attacker-controlled
one must report the finding; an analysis that cannot show what an
ORIGIN read is used for must not drop the finding either. Both mistakes
are silent, and one of them is a false negative in a security product,
which is the worse of the two.
"""

from __future__ import annotations

from app.services.context import (
    TARGET_CONSTANT,
    TARGET_EXTERNAL,
    TARGET_UNKNOWN,
    USE_CALL_TARGET,
    USE_COMPARED,
    USE_STORED,
    analyse_graph,
)
from evm_analysis.cfg import build_cfg
from evm_analysis.disassembler import disassemble
from evm_analysis.opcodes import load_fork


def _facts(code: bytes):
    """The facts for a piece of runtime code."""
    table = load_fork("cancun")
    disassembly = disassemble(code, table)
    cfg = build_cfg(disassembly)
    return analyse_graph(cfg)


#: A delegatecall whose target is a compile-time constant: the expected
#: shape of an upgradeable proxy whose implementation is immutable.
#:
#: DELEGATECALL takes seven values from the top of the stack: gas,
#: address, value, argsOffset, argsLength, retOffset, retLength. So the
#: address is the second from the top, and the frame has to be complete
#: for the analysis to know what the address is.
DELEGATECALL_CONSTANT_TARGET = bytes.fromhex(
    "6000"  # PUSH1 00   (retLength)
    "6000"  # PUSH1 00   (retOffset)
    "6000"  # PUSH1 00   (argsLength)
    "6000"  # PUSH1 00   (argsOffset)
    "6000"  # PUSH1 00   (value)
    "73"  # PUSH20       (address)
    "0123456789abcdef0123456789abcdef01234567"
    "5a"  # GAS          (gas)
    "f4"  # DELEGATECALL
    "00"  # STOP
)

#: A delegatecall whose target comes from calldata: the attacker can
#: choose the implementation.
DELEGATECALL_CALLDATA_TARGET = bytes.fromhex(
    "6000"  # PUSH1 00   (retLength)
    "6000"  # PUSH1 00   (retOffset)
    "6000"  # PUSH1 00   (argsLength)
    "6000"  # PUSH1 00   (argsOffset)
    "6000"  # PUSH1 00   (value)
    "6000"  # PUSH1 00   (the offset calldata is read from)
    "35"  # CALLDATALOAD (address)
    "5a"  # GAS          (gas)
    "f4"  # DELEGATECALL
    "00"  # STOP
)

#: A delegatecall whose target comes from storage: the administrator,
#: or an attacker who compromised it, can choose the implementation.
DELEGATECALL_STORAGE_TARGET = bytes.fromhex(
    "6000"  # PUSH1 00   (retLength)
    "6000"  # PUSH1 00   (retOffset)
    "6000"  # PUSH1 00   (argsLength)
    "6000"  # PUSH1 00   (argsOffset)
    "6000"  # PUSH1 00   (value)
    "6000"  # PUSH1 00   (the slot storage is read from)
    "54"  # SLOAD        (address)
    "5a"  # GAS          (gas)
    "f4"  # DELEGATECALL
    "00"  # STOP
)

#: ORIGIN compared with an address: an authorisation check.
ORIGIN_COMPARED = bytes.fromhex(
    "32"  # ORIGIN
    "73"  # PUSH20
    "0123456789abcdef0123456789abcdef01234567"
    "14"  # EQ
    "00"  # STOP
)

#: ORIGIN used as the target of a call.
#:
#: CALL takes its arguments from the top of the stack: gas, address,
#: value, argsOffset, argsLength, retOffset, retLength. So the address is
#: the *second* from the top, which means ORIGIN is pushed after the
#: five values below it and before the gas.
ORIGIN_CALL_TARGET = bytes.fromhex(
    "6000"  # PUSH1 00   (retLength)
    "6000"  # PUSH1 00   (retOffset)
    "6000"  # PUSH1 00   (argsLength)
    "6000"  # PUSH1 00   (argsOffset)
    "6000"  # PUSH1 00   (value)
    "32"  # ORIGIN      (address)
    "5a"  # GAS         (gas)
    "f1"  # CALL
    "00"  # STOP
)

#: ORIGIN stored to memory and never used for anything.
ORIGIN_STORED = bytes.fromhex(
    "32"  # ORIGIN
    "6000"  # PUSH1 00
    "52"  # MSTORE
    "00"  # STOP
)


def test_a_constant_delegatecall_target_is_recognised():
    facts = _facts(DELEGATECALL_CONSTANT_TARGET)
    assert len(facts.delegatecall_targets) == 1
    target = facts.delegatecall_targets[0]
    assert target.kind == TARGET_CONSTANT
    assert target.is_fixed


def test_a_calldata_delegatecall_target_is_external():
    facts = _facts(DELEGATECALL_CALLDATA_TARGET)
    assert len(facts.delegatecall_targets) == 1
    target = facts.delegatecall_targets[0]
    assert target.kind == TARGET_EXTERNAL
    assert not target.is_fixed


def test_a_storage_delegatecall_target_is_external():
    facts = _facts(DELEGATECALL_STORAGE_TARGET)
    assert len(facts.delegatecall_targets) == 1
    assert facts.delegatecall_targets[0].kind == TARGET_EXTERNAL


def test_an_origin_that_is_compared_is_authorisation_shaped():
    facts = _facts(ORIGIN_COMPARED)
    assert len(facts.origin_uses) == 1
    use = facts.origin_uses[0]
    assert use.kind == USE_COMPARED
    assert use.is_authorisation_shaped


def test_an_origin_used_as_a_call_target_is_authorisation_shaped():
    facts = _facts(ORIGIN_CALL_TARGET)
    assert len(facts.origin_uses) == 1
    assert facts.origin_uses[0].kind == USE_CALL_TARGET


def test_an_origin_that_is_stored_is_not_authorisation_shaped():
    facts = _facts(ORIGIN_STORED)
    assert len(facts.origin_uses) == 1
    assert facts.origin_uses[0].kind == USE_STORED
    assert not facts.origin_uses[0].is_authorisation_shaped


def test_a_delegatecall_with_an_unreadable_target_is_unknown():
    """An unresolved target is reported, never dropped."""
    # The target comes from a call's return value: the analysis cannot
    # follow it, so it must not claim the target is fixed.
    code = bytes.fromhex(
        "6000"  # PUSH1 00
        "6000"  # PUSH1 00
        "6000"  # PUSH1 00
        "6000"  # PUSH1 00
        "6000"  # PUSH1 00
        "5a"  # GAS
        "f1"  # CALL -> leaves an unknown value
        "5a"  # GAS
        "f4"  # DELEGATECALL
        "00"  # STOP
    )
    facts = _facts(code)
    assert len(facts.delegatecall_targets) == 1
    assert facts.delegatecall_targets[0].kind == TARGET_UNKNOWN
    assert not facts.delegatecall_targets[0].is_fixed


def test_a_delegatecall_with_an_underflowed_stack_is_unknown() -> None:
    """An underflow is not a constant target.

    The call's argument frame was never pushed, so the slots that happen
    to be on the stack are not its arguments. Reading an address out of
    them would turn a stack underflow into a false all-clear, and a
    false all-clear is the worst thing this analysis can do.
    """
    code = bytes.fromhex(
        "6000"  # PUSH1 00
        "6000"  # PUSH1 00
        "f4"  # DELEGATECALL -- the frame is not there
        "00"  # STOP
    )
    facts = _facts(code)
    assert len(facts.delegatecall_targets) == 1
    assert facts.delegatecall_targets[0].kind == TARGET_UNKNOWN
    assert not facts.delegatecall_targets[0].is_fixed


def test_nothing_is_claimed_about_code_without_the_opcodes():
    facts = _facts(bytes.fromhex("600160005500"))
    assert facts.delegatecall_targets == []
    assert facts.origin_uses == []
