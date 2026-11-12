"""Tests for the guidance a finding carries.

The guidance is what turns a pattern into an action: what it is, why it
matters, what to change, and -- the part that saves a reviewer their
afternoon -- when it is not a problem at all.

These tests also pin two properties that matter more than the wording:
guidance is never half-written, and a detector with no guidance gets
none rather than a generic paragraph that says nothing.
"""

from __future__ import annotations

from app.services.knowledge import guidance_for, load_seed
from app.services.report import ReportFinding, build_report_data, text_fragments

#: The detectors the bytecode rules produce.
BASELINE_DETECTORS = (
    "baseline.delegatecall",
    "baseline.tx_origin",
    "baseline.selfdestruct",
    "baseline.call_before_state_write",
    "baseline.stack_underflow",
    "baseline.unresolved_jumps",
)

REQUIRED_FIELDS = (
    "title",
    "what_it_means",
    "why_it_matters",
    "how_to_fix",
    "false_positive_patterns",
    "references",
)


def test_every_baseline_detector_has_guidance() -> None:
    for detector_id in BASELINE_DETECTORS:
        guidance = guidance_for(detector_id)
        assert guidance is not None, f"{detector_id} has no guidance"


def test_no_guidance_is_half_written() -> None:
    """Advice with a missing half is worse than no advice."""
    for detector_id, guidance in load_seed().items():
        for field in REQUIRED_FIELDS:
            value = getattr(guidance, field)
            assert value and value.strip(), f"{detector_id}.{field} is empty"


def test_an_unknown_detector_has_no_guidance() -> None:
    assert guidance_for("baseline.not_a_detector") is None
    assert guidance_for("") is None


def test_the_false_positive_half_is_present_for_every_detector() -> None:
    """Every detector needs to say when it is *not* a problem."""
    for detector_id, guidance in load_seed().items():
        assert len(guidance.false_positive_patterns) > 40, detector_id


def test_the_guidance_carries_its_own_version() -> None:
    guidance = guidance_for("baseline.delegatecall")
    assert guidance is not None
    assert guidance.version


def _report_for(detector_id: str) -> str:
    """The report text for one finding from ``detector_id``."""
    data = build_report_data(
        scan_id="scan-1",
        contract_address="0x" + "ab" * 20,
        chain_id=1,
        fork="cancun",
        findings=[
            {
                "detector_id": detector_id,
                "category": "test",
                "title": "a finding",
                "description": "a finding",
                "severity": "high",
                "confidence": 0.8,
                "source": "rule",
                "evidence": {},
            }
        ],
    )
    return "\n".join(text_fragments(data))


def test_the_report_explains_what_to_do() -> None:
    text = _report_for("baseline.delegatecall")
    assert "What this means" in text
    assert "Why it matters" in text
    assert "What to change" in text
    assert "When it is not a problem" in text


def test_the_report_says_nothing_about_a_fix_it_does_not_have() -> None:
    """No guidance means no advice, not generic advice."""
    text = _report_for("baseline.not_a_detector")
    assert "What this means" not in text
    assert "What to change" not in text


def test_the_guidance_is_carried_on_the_finding() -> None:
    guidance = guidance_for("baseline.tx_origin")
    assert guidance is not None
    finding = ReportFinding(
        detector_id="baseline.tx_origin",
        category="access_control",
        title="tx.origin",
        description="",
        severity="low",
        confidence=0.5,
        source="rule",
        guidance=guidance.as_dict(),
    )
    assert finding.guidance is not None
    assert finding.guidance["how_to_fix"]
#: The detectors the Slither and Mythril integrations emit, as they
#: appear in the live corpus.
ENGINE_DETECTORS = (
    "slither.assembly",
    "slither.solc_version",
    "slither.immutable_states",
    "slither.locked_ether",
    "slither.too_many_digits",
    "slither.naming_convention",
    "slither.dead_code",
    "slither.low_level_calls",
    "slither.incorrect_return",
    "slither.unindexed_event_address",
    "slither.unused_return",
    "slither.divide_before_multiply",
    "slither.calls_loop",
    "slither.arbitrary_send_eth",
    "slither.arbitrary_send_erc20",
    "slither.incorrect_modifier",
    "slither.missing_inheritance",
    "slither.timestamp",
    "slither.events_access",
    "slither.missing_zero_check",
    "slither.incorrect_exp",
    "slither.cyclomatic_complexity",
    "slither.pragma",
    "slither.reentrancy_unlimited_gas",
    "mythril.swc_114",
    "mythril.swc_105",
)

#: The severities the product uses.
KNOWN_SEVERITIES = ("critical", "high", "medium", "low", "info")


def test_every_engine_detector_has_guidance() -> None:
    """A detector the product emits must be explainable."""
    for detector_id in ENGINE_DETECTORS:
        guidance = guidance_for(detector_id)
        assert guidance is not None, f"{detector_id} has no guidance"


def test_the_severity_of_every_entry_is_one_the_product_uses() -> None:
    for detector_id, guidance in load_seed().items():
        assert guidance.default_severity in KNOWN_SEVERITIES, detector_id


def test_every_detector_appears_once() -> None:
    """Two entries for one detector would make the answer ambiguous."""
    seed = load_seed()
    assert len(seed) == len(set(seed))
