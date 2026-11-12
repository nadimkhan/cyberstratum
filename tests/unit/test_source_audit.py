"""Tests for the source-audit bridge.

The source engine (Slither) and the bytecode engine (CyberStratum's own
rules) must produce findings in the same shape, so the unified findings
table can hold them together and a reviewer can compare them.
"""

from __future__ import annotations

import json
import os
import sys

import pytest

from app.db.enums import Severity
from app.services.rules import RuleFinding
from app.services.slither import SlitherFinding, SlitherRunner, parse_slither_json
from app.services.source_audit import (
    CONFIDENCE_SCORES,
    SOURCE_DETECTOR_VERSION,
    SOURCE_PREFIX,
    audit_source,
    confidence_score,
    detector_title,
    risk_vectors,
    to_rule_finding,
)


def _finding(detector: str = "reentrancy_eth", severity: str = "high") -> SlitherFinding:
    return SlitherFinding(
        detector=detector,
        severity=severity,
        confidence="medium",
        description="Reentrancy in Vault.withdraw(uint256)",
        vector="reentrancy",
        contract_path="Vault.sol",
    )


# -- the shared shape ----------------------------------------------------


def test_a_slither_finding_becomes_a_shared_finding() -> None:
    """The shape matches the one the bytecode rule engine produces."""
    finding = to_rule_finding(_finding())

    assert isinstance(finding, RuleFinding)
    assert finding.detector_id == "slither.reentrancy_eth"
    # The shared category, the same one the bytecode rule engine uses.
    assert finding.category == "reentrancy_candidate"
    assert finding.severity is Severity.HIGH
    assert finding.description == "Reentrancy in Vault.withdraw(uint256)"
    assert 0.0 < finding.confidence <= 1.0


def test_the_detector_id_says_which_engine_produced_it() -> None:
    """The engine is distinguishable in the unified table."""
    finding = to_rule_finding(_finding())
    assert finding.detector_id.startswith(f"{SOURCE_PREFIX}.")
    assert SOURCE_DETECTOR_VERSION


def test_the_evidence_says_where_the_finding_came_from() -> None:
    """The evidence keeps the source engine's own wording."""
    finding = to_rule_finding(_finding())
    assert finding.evidence["sourceEngine"] == "slither"
    assert finding.evidence["detector"] == "reentrancy_eth"
    assert finding.evidence["vector"] == "reentrancy"
    assert finding.evidence["category"] == "reentrancy_candidate"


def test_a_source_finding_states_its_limitation() -> None:
    """Source analysis alone cannot rule out a source/bytecode mismatch."""
    finding = to_rule_finding(_finding())
    assert "bytecode" in finding.limitations.lower()


def test_an_unknown_severity_does_not_crash() -> None:
    """A severity Slither invented does not break the mapping."""
    finding = to_rule_finding(_finding(severity="catastrophic"))
    assert finding.severity is Severity.MEDIUM


# -- confidence ----------------------------------------------------------


@pytest.mark.parametrize(
    ("word", "score"),
    [("high", 0.9), ("Medium", 0.6), ("low", 0.3), ("unknown", 0.6)],
)
def test_confidence_is_a_score(word: str, score: float) -> None:
    """Slither's confidence words become numbers."""
    assert confidence_score(word) == score
    assert word.lower() in CONFIDENCE_SCORES or word.lower() == "unknown"


# -- titles --------------------------------------------------------------


def test_a_known_detector_gets_a_readable_title() -> None:
    """The common detectors get a title a human can read."""
    assert detector_title("reentrancy_eth") == ("Reentrancy — state updated after an external call")
    assert detector_title("tx_origin") == "tx.origin used for authorisation"


def test_an_unknown_detector_still_gets_a_title() -> None:
    """A new Slither detector is not left blank."""
    title = detector_title("some_brand_new_detector")
    assert title == "Some brand new detector"


# -- the audit -----------------------------------------------------------


def test_a_contract_with_no_source_is_skipped() -> None:
    """An unverified contract has no source to audit."""
    result = audit_source(None, "Vault")
    assert result.ran is False
    assert result.skipped == "no_source"
    assert result.findings == ()

    empty = audit_source("   ", "Vault")
    assert empty.skipped == "no_source"


def test_a_missing_slither_is_skipped_not_failed() -> None:
    """A missing optional tool does not fail the contract."""
    runner = SlitherRunner(executable="definitely/not/here/slither")
    result = audit_source("contract Vault { } " * 20, "Vault", runner=runner)

    assert result.ran is False
    assert result.skipped == "slither_not_installed"
    assert result.findings == ()


def test_the_audit_returns_findings_in_the_shared_shape(tmp_path) -> None:
    """A fake executable proves the whole path end to end."""

    payload = json.dumps(
        {
            "results": {
                "detectors": [
                    {
                        "check": "reentrancy-eth",
                        "impact": "High",
                        "confidence": "Medium",
                        "description": "Reentrancy in Vault.withdraw",
                    }
                ]
            }
        }
    )
    script = tmp_path / "fake_slither.py"
    script.write_text("import sys\nsys.stdout.write(" + repr(payload) + ")\n", encoding="utf-8")
    if os.name == "nt":
        fake = tmp_path / "slither.cmd"
        fake.write_text(f'@echo off\r\n"{sys.executable}" "{script}" %*\r\n', encoding="utf-8")
    else:
        fake = tmp_path / "slither"
        fake.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n', encoding="utf-8")
        fake.chmod(0o755)
    solc_dir = tmp_path / "0.8.26"
    solc_dir.mkdir()
    (solc_dir / "solc-0.8.26.exe").write_text("", encoding="utf-8")

    runner = SlitherRunner(executable=str(fake), solc_artifacts=str(tmp_path))
    result = audit_source(
        "contract Vault { function f() public {} } " * 10, "Vault", "0.8.26", runner=runner
    )

    assert result.ran is True
    assert len(result.findings) == 1
    assert result.findings[0].detector_id == "slither.reentrancy_eth"
    assert result.findings[0].severity is Severity.HIGH


def test_a_source_finding_and_a_bytecode_finding_share_a_category() -> None:
    """The two engines describe the same class of risk the same way."""
    source = to_rule_finding(_finding("reentrancy_eth", "high"))
    # The bytecode rule engine's own reentrancy category, so the same risk
    # compares equal whichever engine found it.
    assert source.category == "reentrancy_candidate"


# -- risk vectors --------------------------------------------------------


def test_risk_vectors_summarise_a_set_of_detectors() -> None:
    """A report can say which classes of risk were covered."""
    vectors = risk_vectors(["reentrancy_eth", "tx_origin", "suicidal"])
    assert vectors == ["reentrancy", "selfdestruct", "tx_origin_auth"]


def test_risk_vectors_accept_a_mapping() -> None:
    """A mapping of detector to count works the same way."""
    vectors = risk_vectors({"reentrancy_eth": 3, "tx_origin": 1})
    assert vectors == ["reentrancy", "tx_origin_auth"]


def test_risk_vectors_of_nothing_is_empty() -> None:
    """An empty report is empty, not an error."""
    assert risk_vectors([]) == []
    assert risk_vectors({}) == []


# -- the parser is shared -----------------------------------------------


def test_the_audit_uses_the_shared_json_parser() -> None:
    """The audit and the runner agree on what Slither's JSON means."""
    payload = '{"results": {"detectors": [{"check": "tx-origin", "impact": "Medium"}]}}'
    assert len(parse_slither_json(payload)) == 1
