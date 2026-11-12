"""Tests for the fork-aware SELFDESTRUCT rule.

SELFDESTRUCT changed what it does in Cancun: the contract's code
survives and only the balance moves. A rule that keeps saying the
contract can destroy itself is stating something the chain no longer
does, so the finding has to narrow with the fork. These tests pin that
narrowing -- and pin that it does not narrow the wrong way.
"""

from __future__ import annotations

from app.services.rules import run_rules
from evm_analysis.cfg import build_cfg
from evm_analysis.disassembler import disassemble
from evm_analysis.features import extract_features
from evm_analysis.opcodes import load_fork

#: PUSH20 of a beneficiary address, then SELFDESTRUCT.
SELFDESTRUCT_CODE = bytes.fromhex(
    "73"
    "0123456789abcdef0123456789abcdef01234567"
    "ff"
)


def _finding(code: bytes, fork: str):
    table = load_fork(fork)
    disassembly = disassemble(code, table)
    cfg = build_cfg(disassembly)
    features = extract_features(disassembly, cfg)
    findings = {
        finding.detector_id: finding
        for finding in run_rules(disassembly, cfg, features)
    }
    return findings.get("baseline.selfdestruct")


def test_before_cancun_the_contract_can_still_be_destroyed():
    finding = _finding(SELFDESTRUCT_CODE, "shanghai")
    assert finding is not None
    assert finding.severity.value == "medium"
    assert "destroy itself" in finding.description
    assert finding.evidence["offsets"] == [21]


def test_from_cancun_the_code_survives_and_only_the_balance_moves():
    finding = _finding(SELFDESTRUCT_CODE, "cancun")
    assert finding is not None
    assert finding.severity.value == "low"
    assert "code is not destroyed" in finding.description
    assert finding.evidence["fork"] == "cancun"
    assert "balance_forwarding_only" in finding.evidence["signals"]
    assert "same transaction" in finding.limitations


def test_a_later_fork_still_narrows():
    finding = _finding(SELFDESTRUCT_CODE, "prague")
    assert finding is not None
    assert finding.severity.value == "low"


def test_the_narrowing_keeps_the_offset_of_the_opcode():
    finding = _finding(SELFDESTRUCT_CODE, "cancun")
    assert finding is not None
    assert finding.evidence["offsets"] == [21]
