"""Tests for the deterministic PDF report renderer.

The report is the product's disclosure surface, so the two properties under
test are the two that a project team would rely on:

* **Reproducibility.** The same evidence must render to byte-identical PDF
  bytes, so that the report's SHA-256 can be recorded and re-checked. This is
  the headline test.
* **Honesty about evidence.** A bytecode-only finding must not claim a source
  line; an engine that produced no verdict must not be described as clean.

The tests assert on the rendered text through ``text_fragments``, which is the
same content model the renderer draws from, so the assertions are about what
the document says rather than about how ReportLab happens to lay it out. The
PDF bytes themselves are additionally checked for the headline strings.
"""

from __future__ import annotations

import os
import sys
from typing import Any

import pytest

from app.services.report import (
    NO_VERDICT,
    NOT_AVAILABLE,
    ReportData,
    ReportLabUnavailableError,
    build_report_data,
    render_report,
    report_sha256,
    text_fragments,
)

CONTRACT = "0x1234567890abcdef1234567890abcdef12345678"

BYTECODE_FINDING: dict[str, Any] = {
    "detector_id": "rule.delegatecall.untrusted",
    "category": "delegatecall",
    "title": "DELEGATECALL to an address that is not a known library",
    "description": "The contract delegates to an address loaded from storage.",
    "severity": "high",
    "confidence": 0.82,
    "source": "rule",
    "evidence": {
        "type": "bytecode_offset",
        "offset": 118,
        "opcode": "DELEGATECALL",
        "instructionSequence": ["PUSH1 0x20", "DELEGATECALL"],
        "cfgPath": [0, 42, 118],
        "reachable": True,
    },
    "limitations": "Reachability is inferred from the CFG, not observed at runtime.",
}

SOURCE_FINDING: dict[str, Any] = {
    "detector_id": "slither.reentrancy",
    "category": "reentrancy",
    "title": "Reentrancy after external call",
    "description": "State is updated after the external call.",
    "severity": "medium",
    "confidence": 0.6,
    "source": "slither",
    "evidence": {
        "type": "source_line",
        "sourceFile": "contracts/Vault.sol",
        "sourceLine": 87,
        "function": "withdraw",
    },
}


def _data(**overrides: Any) -> ReportData:
    """Build a report data object with sensible defaults."""
    kwargs: dict[str, Any] = {
        "scan_id": "scan-0001",
        "contract_address": CONTRACT,
        "chain_id": 1,
        "fork": "cancun",
        "scan_status": "completed",
        "findings": [BYTECODE_FINDING],
        "tool_versions": {"parser": "0.4.1", "ruleset": "0.9.0", "model": "2026.03"},
        "timestamp": "2026-03-01T12:00:00Z",
    }
    kwargs.update(overrides)
    return build_report_data(**kwargs)


def _text(data: ReportData) -> str:
    """The whole document as one searchable string."""
    return "\n".join(text_fragments(data))


# -- determinism -----------------------------------------------------------


def test_rendering_the_same_data_twice_is_byte_identical():
    """The headline property: identical evidence yields identical bytes."""
    data = _data()
    first = render_report(data)
    second = render_report(data)
    assert first == second
    assert report_sha256(first) == report_sha256(second)
    assert first.startswith(b"%PDF-")


def test_different_construction_order_yields_identical_bytes():
    """Two data objects with the same content render the same document.

    The collections are assembled in a different order and the keyword
    arguments are supplied in a different order. The rendered document must
    not depend on either.
    """
    first = build_report_data(
        scan_id="scan-0001",
        contract_address=CONTRACT,
        chain_id=1,
        fork="cancun",
        scan_status="completed",
        findings=[BYTECODE_FINDING, SOURCE_FINDING],
        artifacts=[
            {"kind": "source", "object_key": "b.sol", "byte_size": 12},
            {"kind": "bytecode", "object_key": "a.bin", "byte_size": 34},
        ],
        tool_versions={"parser": "0.4.1", "ruleset": "0.9.0", "model": "2026.03"},
        timestamp="2026-03-01T12:00:00Z",
    )
    second = build_report_data(
        timestamp="2026-03-01T12:00:00Z",
        tool_versions={"model": "2026.03", "ruleset": "0.9.0", "parser": "0.4.1"},
        artifacts=[
            {"kind": "bytecode", "object_key": "a.bin", "byte_size": 34},
            {"kind": "source", "object_key": "b.sol", "byte_size": 12},
        ],
        findings=[SOURCE_FINDING, BYTECODE_FINDING],
        scan_status="completed",
        fork="cancun",
        chain_id=1,
        contract_address=CONTRACT,
        scan_id="scan-0001",
    )
    assert render_report(first) == render_report(second)


def test_supplied_timestamp_is_the_only_source_of_time():
    """The supplied timestamp appears, and it is the only clock in the report."""
    stamped = _data(timestamp="2026-03-01T12:00:00Z")
    other = _data(timestamp="2027-07-07T07:07:07Z")

    assert "2026-03-01T12:00:00Z" in _text(stamped)
    assert "2027-07-07T07:07:07Z" not in _text(stamped)

    assert render_report(stamped) != render_report(other)
    assert render_report(stamped) == render_report(_data(timestamp="2026-03-01T12:00:00Z"))
    assert render_report(other) == render_report(_data(timestamp="2027-07-07T07:07:07Z"))


def test_document_metadata_is_pinned_to_constants():
    """No machine name and no wall-clock date leaks into the document."""
    payload = render_report(_data())
    assert b"/Producer (CyberStratum Report Service)" in payload
    assert b"/Title (CyberStratum Security Analysis Report)" in payload
    assert b"/CreationDate (D:20000101000000+00'00')" in payload


def test_no_timestamp_is_rendered_when_none_is_supplied():
    """With no supplied timestamp the report carries no date at all."""
    data = build_report_data(
        scan_id="scan-0001",
        contract_address=CONTRACT,
        findings=[BYTECODE_FINDING],
    )
    assert "Report timestamp | not available" in _text(data)
    payload = render_report(data)
    assert b"2026-" not in payload
    assert b"2025-" not in payload


def test_an_ambient_source_date_epoch_does_not_change_the_bytes(
    monkeypatch: pytest.MonkeyPatch,
):
    """The bytes must not depend on an environment variable nobody passed in."""
    reference = render_report(_data())
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1700000000")
    assert render_report(_data()) == reference


def test_the_ambient_source_date_epoch_is_restored_after_a_render(
    monkeypatch: pytest.MonkeyPatch,
):
    """The renderer must not leave the environment changed behind it."""
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1700000000")
    render_report(_data())
    assert os.environ["SOURCE_DATE_EPOCH"] == "1700000000"


# -- content ---------------------------------------------------------------


def test_report_contains_the_contract_address_and_finding_titles():
    """The rendered document contains the identity and the findings."""
    data = _data(findings=[BYTECODE_FINDING, SOURCE_FINDING])
    payload = render_report(data)
    assert CONTRACT.encode("ascii") in payload
    assert BYTECODE_FINDING["title"].encode("ascii") in payload
    assert SOURCE_FINDING["title"].encode("ascii") in payload

    text = _text(data)
    assert CONTRACT in text
    assert BYTECODE_FINDING["title"] in text
    assert SOURCE_FINDING["title"] in text


def test_bytecode_evidence_is_rendered():
    """Bytecode evidence is rendered as offset, opcode, sequence, path, reachability."""
    text = _text(_data())
    assert "Evidence type: bytecode" in text
    assert "Byte offset: 0x76 (118)" in text
    assert "Opcode: DELEGATECALL" in text
    assert "Instruction sequence: PUSH1 0x20 -> DELEGATECALL" in text
    assert "CFG path: 0x0 (0) -> 0x2a (42) -> 0x76 (118)" in text
    assert "Reachability: reachable" in text


def test_rule_engine_offsets_are_rendered_as_bytecode_evidence():
    """The rule engine names its offsets after their role; all are bytecode."""
    finding = {
        "detector_id": "rule.call_then_storage_write",
        "category": "reentrancy",
        "title": "External call before a storage write",
        "description": "",
        "severity": "high",
        "confidence": 0.5,
        "source": "rule",
        "evidence": {
            "callOffset": 742,
            "storageWriteOffset": 750,
            "signals": ["external_call_before_state_write"],
        },
    }
    text = _text(_data(findings=[finding]))
    assert "Evidence type: bytecode" in text
    assert "callOffset: 0x2e6 (742)" in text
    assert "storageWriteOffset: 0x2ee (750)" in text


def test_bytecode_only_finding_claims_no_source_line():
    """Without a proven correspondence, no source file or line is claimed."""
    data = _data(findings=[BYTECODE_FINDING], correspondence=None)
    text = _text(data)
    assert "Bytecode-only finding" in text
    assert "Source file:" not in text
    assert "Source line:" not in text
    assert "contracts/Vault.sol" not in text


def test_proven_correspondence_renders_the_source_file_and_line():
    """With a proven correspondence, the source file and line are rendered."""
    data = _data(
        findings=[SOURCE_FINDING],
        correspondence={
            "status": "proven",
            "compiler": "solc 0.8.24",
            "settings": "evmVersion=cancun",
        },
    )
    text = _text(data)
    assert "Source file: contracts/Vault.sol" in text
    assert "Source line: 87" in text
    assert "correspondence proof" in text
    assert "proven" in text


def test_established_correspondence_renders_the_source_file_and_line():
    """The stored enum value for a proven chain is ``established``."""
    data = _data(
        findings=[SOURCE_FINDING],
        correspondence={"status": "established"},
    )
    text = _text(data)
    assert "Source file: contracts/Vault.sol" in text
    assert "Source line: 87" in text


def test_failed_correspondence_does_not_unlock_a_source_line():
    """A correspondence chain that failed is not a proof."""
    data = _data(
        findings=[SOURCE_FINDING],
        correspondence={"status": "failed", "statement": "the metadata hash did not match"},
    )
    text = _text(data)
    assert "Source location withheld" in text
    assert "Source file: contracts/Vault.sol" not in text
    assert "Source line: 87" not in text


@pytest.mark.parametrize("status", ["skipped", "unavailable", "mismatch", ""])
def test_no_other_correspondence_status_unlocks_a_source_line(status: str):
    """Only a proven chain licenses a source location."""
    data = _data(
        findings=[SOURCE_FINDING],
        correspondence={"status": status},
    )
    text = _text(data)
    assert "Source file: contracts/Vault.sol" not in text
    assert "Source line: 87" not in text


def test_per_finding_limitations_are_rendered():
    """A limitation carried by the finding is shown."""
    text = _text(_data())
    assert "Limitations: Reachability is inferred from the CFG" in text


def test_limitations_in_the_evidence_dict_are_rendered():
    """A limitation carried inside the evidence dict is also shown."""
    finding = dict(BYTECODE_FINDING)
    finding.pop("limitations")
    finding["evidence"] = dict(BYTECODE_FINDING["evidence"])
    finding["evidence"]["limitations"] = "Static pattern only."
    text = _text(_data(findings=[finding]))
    assert "Limitations: Static pattern only." in text


def test_the_summary_counts_findings_by_severity():
    """The severity table lists every severity, with the counts."""
    text = _text(_data(findings=[BYTECODE_FINDING, SOURCE_FINDING]))
    assert "Severity | Findings" in text
    assert "high | 1" in text
    assert "medium | 1" in text
    assert "critical | 0" in text


# -- engine coverage -------------------------------------------------------


def test_engine_without_a_verdict_is_reported_as_no_verdict():
    """An engine that did not run is never described as clean."""
    data = _data(source_audited=False, source_audit_skipped="no_verified_source")
    text = _text(data)
    assert NO_VERDICT in text
    assert "clean" not in text.lower()
    assert "passed" not in text.lower()
    # The skip reason is shown verbatim.
    assert "no_verified_source" in text


def test_engines_that_ran_are_labelled_as_having_run():
    """An engine that ran is labelled as having run, not as 'no verdict'."""
    data = _data(source_audited=True)
    text = _text(data)
    assert "ran" in text
    assert "slither" in text


def test_every_known_engine_is_listed_even_when_it_did_not_run():
    """An omitted engine is indistinguishable from one that found nothing."""
    text = _text(_data(source_audited=False, source_audit_skipped="no_source"))
    for engine in ("rule", "slither", "mythril", "ml"):
        assert engine in text


def test_a_mythril_run_with_no_verdict_is_not_treated_as_clean():
    """A Mythril run that produced no verdict stays a no-verdict."""
    data = _data(mythril_ran=False, mythril_skipped="no_verdict")
    text = _text(data)
    assert "no_verdict" in text
    assert "clean" not in text.lower()


# -- provenance ------------------------------------------------------------


def test_missing_provenance_values_render_as_not_available():
    """An absent value is shown as 'not available', never omitted."""
    data = build_report_data(
        scan_id="scan-0002",
        contract_address=CONTRACT,
        findings=[],
        tool_versions={},
    )
    text = _text(data)
    assert NOT_AVAILABLE in text
    assert "parser version" in text
    assert "ruleset version" in text
    assert "model version" in text
    assert "dataset manifest id" in text
    assert "model manifest sha256" in text
    assert "correspondence proof" in text
    for label in (
        "parser version",
        "ruleset version",
        "model version",
        "dataset manifest id",
        "dataset manifest sha256",
        "model manifest id",
        "model manifest sha256",
        "correspondence proof",
    ):
        assert f"{label} | {NOT_AVAILABLE}" in text


def test_present_provenance_values_are_rendered():
    """Present provenance values are shown, with their identifiers and hashes."""
    data = build_report_data(
        scan_id="scan-0003",
        contract_address=CONTRACT,
        findings=[],
        tool_versions={"parser": "0.4.1", "slither": "0.10.4"},
        dataset_manifest={"manifest_id": "ds-1", "sha256": "a" * 64},
        model_manifest={"manifest_id": "ml-1", "sha256": "b" * 64},
        correspondence={"status": "skipped", "statement": "no verified source"},
    )
    text = _text(data)
    assert "parser version | 0.4.1" in text
    assert "slither version | 0.10.4" in text
    assert "dataset manifest id | ds-1" in text
    assert f"dataset manifest sha256 | {'a' * 64}" in text
    assert "model manifest id | ml-1" in text
    assert "correspondence proof | skipped" in text
    assert "no verified source" in text


def test_a_missing_correspondence_says_no_source_location_is_claimed():
    """With no proof at all, the report says so rather than staying silent."""
    text = _text(_data(correspondence=None))
    assert "Correspondence proof: not available" in text
    assert "No source location is claimed" in text


def test_the_correspondence_proof_details_are_rendered():
    """The compiler and the settings are part of the proof."""
    data = _data(
        correspondence={
            "status": "established",
            "compiler": "solc 0.8.24",
            "settings": "evmVersion=cancun",
            "statement": "executable code identical after metadata stripping",
        }
    )
    text = _text(data)
    assert "correspondence compiler | solc 0.8.24" in text
    assert "correspondence settings | evmVersion=cancun" in text
    assert "executable code identical after metadata stripping" in text


def test_the_module_stays_importable_without_reportlab(
    monkeypatch: pytest.MonkeyPatch,
):
    """The import guard defers the failure to call time, not import time.

    ``reportlab`` is imported lazily inside the render call so that the
    module can be imported (and its helpers used) in an environment where
    the dependency is absent. The failure must then be a clear, catchable
    error rather than an ``ImportError`` at import time.
    """
    import app.services.report as report_module

    class _Blocker:
        def find_spec(
            self,
            name: str,
            path: object = None,
            target: object = None,
        ) -> None:
            if name == "reportlab" or name.startswith("reportlab."):
                raise ImportError(f"blocked: {name}")
            return None

    # An earlier test in this session may already have imported ReportLab,
    # and ``importlib.import_module`` returns a cached module without
    # consulting ``find_spec``. Evict the cached entries so the import
    # actually reaches the blocker, and put the blocker first so that the
    # default ``PathFinder`` cannot find the real package on disk.
    for name in list(sys.modules):
        if name == "reportlab" or name.startswith("reportlab."):
            monkeypatch.delitem(sys.modules, name, raising=False)
    monkeypatch.setattr(sys, "meta_path", [_Blocker(), *sys.meta_path])

    with pytest.raises(ReportLabUnavailableError):
        report_module.render_report(_data())


# -- disclaimer ------------------------------------------------------------


def test_the_report_carries_a_limitations_disclaimer():
    """The closing block states what the report does and does not establish."""
    text = _text(_data())
    assert "Limitations and disclaimer" in text
    assert "does not assert that any finding is exploitable" in text
    assert "absence of findings is not proof" in text


def test_the_report_states_what_it_is_and_is_not():
    """The title block carries the one-line statement of purpose."""
    text = _text(_data())
    assert "does not assert that any finding is exploitable" in text
