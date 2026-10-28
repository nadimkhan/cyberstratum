"""Tests for the source engine inside the scan pipeline.

The bytecode engine is the primary path. The source engine is a second
opinion on the same contract, and it must never be able to fail a scan:
an unfetchable source, a missing Slither, a source that does not compile
are all skips.

The suite is offline: the source fetch is stubbed.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.db.enums import ScanStatus
from app.db.models.identity import Chain, ContractTarget, Workspace
from app.db.models.scans import Finding, Scan, ScanArtifact
from app.services import pipeline as pipeline_service
from app.services.pipeline import run_scan
from app.services.source_fetch import SourceArtifact

#: A runtime with a DELEGATECALL, so the bytecode engine reports a finding.
SAMPLE_RUNTIME = bytes.fromhex("325f5260205ff35f5ffd5b600055")


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the suite off the network by default."""
    monkeypatch.setattr(pipeline_service, "fetch_verified_source", lambda *a, **k: None)


def _make_scan(
    session: Session, workspace: Workspace, chain: Chain, address: str
) -> Scan:
    """Create a target and a queued scan for it."""
    target = ContractTarget(
        workspace_id=workspace.id,
        chain_id=chain.id,
        address=address,
        label="Pipeline target",
        bytecode_type="runtime",
        authorization_status="unknown",
        inline_bytecode=SAMPLE_RUNTIME,
    )
    session.add(target)
    session.flush()

    scan = Scan(
        workspace_id=workspace.id,
        target_id=target.id,
        status=ScanStatus.QUEUED,
        fork="cancun",
        bytecode_source="upload",
    )
    session.add(scan)
    session.flush()
    return scan


def _source_artifact(**kwargs: object) -> SourceArtifact:
    """A source artifact with one file."""
    source = "// SPDX-License-Identifier: MIT\npragma solidity ^0.8.0;\ncontract A {}\n"
    defaults: dict[str, object] = {
        "code": source,
        "files": {"A.sol": source},
        "compiler_version": "0.8.26",
        "source_uri": "https://example.test/address/0x1",
        "source_kind": "blockscout_instance",
        "verified": True,
    }
    defaults.update(kwargs)
    return SourceArtifact(**defaults)  # type: ignore[arg-type]


def test_a_scan_without_source_records_the_skip(
    db_session: Session, workspace: Workspace, chain: Chain
) -> None:
    """An unverified contract records why the source engine did not run."""
    scan = _make_scan(db_session, workspace, chain, "0x" + "11" * 20)

    outcome = run_scan(db_session, scan)

    assert outcome.status == ScanStatus.COMPLETED
    assert scan.source_audited is False
    assert scan.source_audit_skipped == "no_source"


def test_the_source_findings_are_stored_with_their_engine(
    db_session: Session, workspace: Workspace, chain: Chain, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Source findings land in the same table, tagged with their engine."""
    from app.db.enums import Severity
    from app.services.rules import RuleFinding

    monkeypatch.setattr(
        pipeline_service,
        "fetch_verified_source",
        lambda *a, **k: _source_artifact(),
    )
    monkeypatch.setattr(
        pipeline_service,
        "audit_source",
        lambda *a, **k: _audit_with(
            RuleFinding(
                detector_id="slither.reentrancy_eth",
                category="reentrancy_candidate",
                title="Reentrancy",
                description="External call before state update.",
                severity=Severity.HIGH,
                confidence=0.8,
                evidence={"detector": "reentrancy_eth"},
            )
        ),
    )

    scan = _make_scan(db_session, workspace, chain, "0x" + "22" * 20)
    outcome = run_scan(db_session, scan)

    assert outcome.status == ScanStatus.COMPLETED
    assert scan.source_audited is True
    assert scan.source_audit_skipped is None

    findings = db_session.query(Finding).filter(Finding.scan_id == scan.id).all()
    sources = {finding.source for finding in findings}
    assert "slither" in sources
    assert "rule" in sources

    slither_findings = [f for f in findings if f.source == "slither"]
    assert len(slither_findings) == 1
    assert slither_findings[0].detector_id == "slither.reentrancy_eth"
    assert slither_findings[0].severity == Severity.HIGH


def test_the_source_is_stored_as_an_artifact(
    db_session: Session, workspace: Workspace, chain: Chain, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The verified source is kept as a scan artifact."""
    from app.db.enums import Severity
    from app.services.rules import RuleFinding

    monkeypatch.setattr(
        pipeline_service,
        "fetch_verified_source",
        lambda *a, **k: _source_artifact(),
    )
    monkeypatch.setattr(
        pipeline_service,
        "audit_source",
        lambda *a, **k: _audit_with(
            RuleFinding(
                detector_id="slither.unprotected_eth",
                category="unprotected_ether_withdrawal",
                title="Unprotected withdrawal",
                description="No access control on the withdrawal function.",
                severity=Severity.HIGH,
                confidence=0.9,
                evidence={"detector": "unprotected_eth"},
            )
        ),
    )

    scan = _make_scan(db_session, workspace, chain, "0x" + "33" * 20)
    run_scan(db_session, scan)

    artifacts = (
        db_session.query(ScanArtifact)
        .filter(ScanArtifact.scan_id == scan.id, ScanArtifact.kind == "source")
        .all()
    )
    assert len(artifacts) == 1
    assert artifacts[0].content_type == "application/json"


def test_a_failing_source_fetch_does_not_fail_the_scan(
    db_session: Session, workspace: Workspace, chain: Chain, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A source fetch that raises is contained."""

    def boom(*_a: object, **_k: object) -> None:
        raise RuntimeError("the explorer is down")

    monkeypatch.setattr(pipeline_service, "fetch_verified_source", boom)

    scan = _make_scan(db_session, workspace, chain, "0x" + "44" * 20)
    outcome = run_scan(db_session, scan)

    assert outcome.status == ScanStatus.COMPLETED
    assert scan.source_audited is False
    assert scan.source_audit_skipped == "source_fetch_failed"
    assert outcome.finding_count >= 0


def test_a_skipped_source_audit_leaves_the_bytecode_results(
    db_session: Session, workspace: Workspace, chain: Chain, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A source audit that cannot run does not undo the bytecode findings."""
    monkeypatch.setattr(
        pipeline_service,
        "fetch_verified_source",
        lambda *a, **k: _source_artifact(),
    )
    monkeypatch.setattr(
        pipeline_service,
        "audit_source",
        lambda *a, **k: _audit_skipped("compilation_failed"),
    )

    scan = _make_scan(db_session, workspace, chain, "0x" + "55" * 20)
    outcome = run_scan(db_session, scan)

    assert outcome.status == ScanStatus.COMPLETED
    assert scan.source_audited is False
    assert scan.source_audit_skipped == "compilation_failed"

    findings = db_session.query(Finding).filter(Finding.scan_id == scan.id).all()
    assert findings
    assert all(finding.source == "rule" for finding in findings)


def test_a_second_scan_does_not_duplicate_the_source_findings(
    db_session: Session, workspace: Workspace, chain: Chain, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Re-running a scan replaces its findings rather than adding to them."""
    from app.db.enums import Severity
    from app.services.rules import RuleFinding

    monkeypatch.setattr(
        pipeline_service,
        "fetch_verified_source",
        lambda *a, **k: _source_artifact(),
    )
    monkeypatch.setattr(
        pipeline_service,
        "audit_source",
        lambda *a, **k: _audit_with(
            RuleFinding(
                detector_id="slither.reentrancy_eth",
                category="reentrancy_candidate",
                title="Reentrancy",
                description="External call before state update.",
                severity=Severity.HIGH,
                confidence=0.8,
                evidence={},
            )
        ),
    )

    scan = _make_scan(db_session, workspace, chain, "0x" + "66" * 20)
    run_scan(db_session, scan)
    first = (
        db_session.query(Finding)
        .filter(Finding.scan_id == scan.id, Finding.source == "slither")
        .count()
    )

    run_scan(db_session, scan)
    second = (
        db_session.query(Finding)
        .filter(Finding.scan_id == scan.id, Finding.source == "slither")
        .count()
    )

    assert first == 1
    assert second == 1


def _audit_with(*findings: object):  # type: ignore[no-untyped-def]
    """Build a SourceAudit with the given findings."""
    from app.services.source_audit import SourceAudit

    return SourceAudit(findings=tuple(findings))


def _audit_skipped(reason: str):  # type: ignore[no-untyped-def]
    """Build a SourceAudit that did not run."""
    from app.services.source_audit import SourceAudit

    return SourceAudit(findings=(), skipped=reason)
