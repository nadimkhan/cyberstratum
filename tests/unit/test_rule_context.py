"""Tests for the context-gated rules.

The rules that used to report the presence of an opcode were the
noisiest thing this product did. These tests pin the narrowing, and --
just as importantly -- they pin that the narrowing never goes the wrong
way: a target the analysis cannot resolve is still reported, and a
TX.ORIGIN read whose use cannot be established is still reported, with
a lower confidence.
"""

from __future__ import annotations

from app.db.enums import Severity
from app.services.rules import run_rules
from evm_analysis.cfg import build_cfg
from evm_analysis.disassembler import disassemble
from evm_analysis.features import extract_features
from evm_analysis.opcodes import load_fork


def _findings(code: bytes):
    table = load_fork("cancun")
    disassembly = disassemble(code, table)
    cfg = build_cfg(disassembly)
    features = extract_features(disassembly, cfg)
    return {finding.detector_id: finding for finding in run_rules(disassembly, cfg, features)}


#: DELEGATECALL to a compile-time constant: the expected proxy pattern.
DELEGATECALL_CONSTANT = bytes.fromhex(
    "73"  # PUSH20
    "0123456789abcdef0123456789abcdef01234567"
    "5a"  # GAS
    "f4"  # DELEGATECALL
    "00"  # STOP
)

#: DELEGATECALL to a calldata-supplied address: an attacker chooses.
DELEGATECALL_CALLDATA = bytes.fromhex(
    "6000"  # PUSH1 00
    "35"  # CALLDATALOAD
    "5a"  # GAS
    "f4"  # DELEGATECALL
    "00"  # STOP
)

#: TX.ORIGIN compared with an address.
ORIGIN_COMPARED = bytes.fromhex(
    "32"  # ORIGIN
    "73"  # PUSH20
    "0123456789abcdef0123456789abcdef01234567"
    "14"  # EQ
    "00"  # STOP
)

#: TX.ORIGIN written to memory and never used for anything.
ORIGIN_STORED = bytes.fromhex(
    "32"  # ORIGIN
    "6000"  # PUSH1 00
    "52"  # MSTORE
    "00"  # STOP
)


def test_a_constant_delegatecall_is_not_reported() -> None:
    """The expected proxy pattern is not a finding."""
    findings = _findings(DELEGATECALL_CONSTANT)
    assert "baseline.delegatecall" not in findings


def test_an_attacker_chosen_delegatecall_is_reported() -> None:
    findings = _findings(DELEGATECALL_CALLDATA)
    finding = findings["baseline.delegatecall"]
    assert finding.severity is Severity.HIGH
    assert finding.evidence["offsets"]


def test_an_authorisation_shaped_origin_is_reported_confidently() -> None:
    findings = _findings(ORIGIN_COMPARED)
    finding = findings["baseline.tx_origin"]
    assert finding.confidence >= 0.7
    assert finding.evidence["authorisationOffsets"]
    assert "authorisation" in finding.title.lower()


def test_an_origin_whose_use_is_unknown_is_still_reported() -> None:
    """The analysis cannot rule out an authorisation use, so it says so."""
    findings = _findings(ORIGIN_STORED)
    finding = findings["baseline.tx_origin"]
    assert finding is not None
    assert finding.confidence < 0.5
    assert "rule one out" in finding.limitations
    assert finding.severity is Severity.LOW


def test_a_contract_with_neither_opcode_has_neither_finding() -> None:
    findings = _findings(bytes.fromhex("600160005500"))
    assert "baseline.delegatecall" not in findings
    assert "baseline.tx_origin" not in findings
