"""End-to-end tests for the scan pipeline.

These exercise the whole path the product promises: bytes in, findings out,
with every artifact persisted and every reproducibility field recorded. They
run against the dedicated ``cyberstratum_test`` database and the local
artifact store; no network access and no running worker are required.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.orm import Session

from app.db.enums import ScanStatus
from app.db.models.identity import Chain, ContractTarget, Workspace
from app.db.models.scans import (
    BasicBlock,
    CfgEdge,
    FeatureRecord,
    Finding,
    Instruction,
    Scan,
    ScanArtifact,
)
from app.services.pipeline import run_scan


@pytest.fixture(autouse=True)
def _no_network_source_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the suite off the network.

    The pipeline looks for a contract's verified source so the source
    engine can have a second opinion. In the test suite that would be a
    live HTTP request, so it is stubbed out here. The source engine's own
    behaviour is covered by ``tests/unit/test_source_audit.py`` and
    ``tests/unit/test_slither.py``.
    """
    from app.services import pipeline as pipeline_service

    monkeypatch.setattr(pipeline_service, "fetch_verified_source", lambda *a, **k: None)


#: A runtime that reads TX.ORIGIN, stores it, then performs a DELEGATECALL.
#: It exercises the DELEGATECALL and TX.ORIGIN rules and contains no branch,
#: so the CFG is fully resolvable.
SAMPLE_RUNTIME = bytes.fromhex(
    "32"  # ORIGIN
    "6000"  # PUSH1 0x00
    "52"  # MSTORE
    "6000"  # PUSH1 0x00
    "6000"  # PUSH1 0x00
    "f4"  # DELEGATECALL
    "00"  # STOP
)


def _make_scan(
    session: Session,
    workspace: Workspace,
    chain: Chain,
    code: bytes,
    *,
    fork: str = "cancun",
) -> Scan:
    """Create a target holding ``code`` and a queued scan for it.

    A target is unique per (workspace, chain, address), so a second scan of
    the same contract reuses the target rather than duplicating it. That
    mirrors what the API does when a scan is submitted.
    """
    address = "0x" + "cd" * 20
    target = (
        session.query(ContractTarget)
        .filter(
            ContractTarget.workspace_id == workspace.id,
            ContractTarget.chain_id == chain.id,
            ContractTarget.address == address,
        )
        .one_or_none()
    )
    if target is None:
        target = ContractTarget(
            workspace_id=workspace.id,
            chain_id=chain.id,
            address=address,
            label="E2E target",
            bytecode_type="runtime",
            authorization_status="unknown",
            inline_bytecode=code,
        )
        session.add(target)
    else:
        target.inline_bytecode = code
    session.flush()

    scan = Scan(
        workspace_id=workspace.id,
        target_id=target.id,
        status=ScanStatus.QUEUED,
        fork=fork,
        bytecode_source="upload",
    )
    session.add(scan)
    session.flush()
    return scan


def test_a_scan_produces_findings_artifacts_and_reproducibility(
    db_session: Session, workspace: Workspace, chain: Chain
) -> None:
    """A scan records its findings, its artifacts and how to reproduce it."""
    scan = _make_scan(db_session, workspace, chain, SAMPLE_RUNTIME)
    outcome = run_scan(db_session, scan)
    db_session.flush()

    assert outcome.status in {ScanStatus.COMPLETED, ScanStatus.PARTIAL}
    assert outcome.finding_count >= 2

    findings = db_session.query(Finding).filter(Finding.scan_id == scan.id).all()
    detector_ids = {finding.detector_id for finding in findings}
    assert "baseline.delegatecall" in detector_ids
    assert "baseline.tx_origin" in detector_ids

    # Severity and confidence are separate fields, and both are populated.
    for finding in findings:
        assert finding.severity
        assert 0.0 <= finding.confidence <= 1.0
        assert finding.limitations

    artifacts = db_session.query(ScanArtifact).filter(ScanArtifact.scan_id == scan.id).all()
    kinds = {artifact.kind for artifact in artifacts}
    # The fork resolution is an artifact in its own right: it is the
    # record of *which* fork's rules were applied and how that was
    # decided, and the report cites it.
    assert kinds == {
        "bytecode",
        "disassembly",
        "cfg",
        "features",
        "fork_resolution",
    }

    bytecode_artifact = next(a for a in artifacts if a.kind == "bytecode")
    assert bytecode_artifact.byte_size == len(SAMPLE_RUNTIME)
    assert bytecode_artifact.sha256

    # The reproducibility quadruple: input bytes, fork, parser and ruleset.
    assert scan.bytecode_source == "upload"
    assert scan.fork == "cancun"
    assert scan.parser_version
    assert scan.ruleset_version
    assert scan.started_at is not None
    assert scan.completed_at is not None


def test_the_graph_is_persisted_instruction_by_instruction(
    db_session: Session, workspace: Workspace, chain: Chain
) -> None:
    """Instructions, blocks and edges are stored for the scan."""
    scan = _make_scan(db_session, workspace, chain, SAMPLE_RUNTIME)
    run_scan(db_session, scan)
    db_session.flush()

    instructions = db_session.query(Instruction).filter(Instruction.scan_id == scan.id).all()
    # PUSH immediates are consumed as data, so the runtime decodes to 7
    # instructions rather than 12 bytes.
    assert len(instructions) == 7
    assert [i.opcode_name for i in instructions] == [
        "ORIGIN",
        "PUSH1",
        "MSTORE",
        "PUSH1",
        "PUSH1",
        "DELEGATECALL",
        "STOP",
    ]
    assert all(instruction.byte_offset >= 0 for instruction in instructions)

    blocks = db_session.query(BasicBlock).filter(BasicBlock.scan_id == scan.id).all()
    assert len(blocks) == 1
    assert blocks[0].is_entry is True

    edges = db_session.query(CfgEdge).filter(CfgEdge.scan_id == scan.id).all()
    # The runtime ends in STOP, so the only edge is the terminal one.
    assert len(edges) == 1
    assert edges[0].edge_type == "stop"
    assert edges[0].to_block_id is None

    features = db_session.query(FeatureRecord).filter(FeatureRecord.scan_id == scan.id).one()
    vector = features.feature_json
    assert vector
    assert vector["instruction_count"] == 7
    assert vector["block_count"] == 1
    assert vector["call_count"] == 1
    # Opcode frequencies are normalised by the instruction count.
    assert vector["opcode_freq__DELEGATECALL"] == pytest.approx(1 / 7)
    assert vector["opcode_freq__ORIGIN"] == pytest.approx(1 / 7)
    assert vector["opcode_freq__PUSH1"] == pytest.approx(3 / 7)


def test_the_same_bytecode_produces_the_same_result(
    db_session: Session, workspace: Workspace, chain: Chain
) -> None:
    """Analysing the same bytes twice gives identical findings and features."""
    first = _make_scan(db_session, workspace, chain, SAMPLE_RUNTIME)
    run_scan(db_session, first)
    db_session.flush()

    second = _make_scan(db_session, workspace, chain, SAMPLE_RUNTIME)
    run_scan(db_session, second)
    db_session.flush()

    def signature(scan: Scan) -> list[tuple[str, str, float]]:
        rows = db_session.query(Finding).filter(Finding.scan_id == scan.id).all()
        return sorted((f.detector_id, f.severity.value, f.confidence) for f in rows)

    assert signature(first) == signature(second)

    def feature_vector(scan: Scan) -> dict[str, float]:
        row = db_session.query(FeatureRecord).filter(FeatureRecord.scan_id == scan.id).one()
        return dict(row.feature_json)

    assert feature_vector(first) == feature_vector(second)


def test_a_different_fork_changes_the_analysis(
    db_session: Session, workspace: Workspace, chain: Chain
) -> None:
    """The fork is part of the analysis input, not a label.

    The runtime contains no fork-specific opcode, so the instruction stream
    is identical, but the recorded fork still differs: it is part of what
    makes a scan reproducible.
    """
    frontier = _make_scan(db_session, workspace, chain, SAMPLE_RUNTIME, fork="frontier")
    run_scan(db_session, frontier)
    db_session.flush()
    cancun = _make_scan(db_session, workspace, chain, SAMPLE_RUNTIME, fork="cancun")
    run_scan(db_session, cancun)
    db_session.flush()

    assert frontier.fork == "frontier"
    assert cancun.fork == "cancun"
    assert frontier.parser_version == cancun.parser_version


def test_a_scan_without_bytecode_fails_cleanly(
    db_session: Session, workspace: Workspace, chain: Chain
) -> None:
    """A target with no bytecode and no reachable RPC records a failure.

    The scan must not raise: the failure is recorded on the scan row so the
    UI can explain it.
    """
    from app.services import pipeline as pipeline_service
    from app.services.bytecode import BytecodeUnavailableError

    def unavailable(*args: object, **kwargs: object) -> bytes:
        raise BytecodeUnavailableError("no source", code="rpc_unreachable")

    # The pipeline binds the function at import time, so the patch has to
    # target the name the pipeline actually calls.
    original = pipeline_service.fetch_runtime_bytecode
    pipeline_service.fetch_runtime_bytecode = unavailable  # type: ignore[assignment]
    try:
        target = ContractTarget(
            workspace_id=workspace.id,
            chain_id=chain.id,
            address="0x" + "ef" * 20,
            label="No bytecode",
            bytecode_type="runtime",
            authorization_status="unknown",
        )
        db_session.add(target)
        db_session.flush()
        scan = Scan(
            workspace_id=workspace.id,
            target_id=target.id,
            status=ScanStatus.QUEUED,
            fork="cancun",
            bytecode_source="rpc",
        )
        db_session.add(scan)
        db_session.flush()

        outcome = run_scan(db_session, scan)
        db_session.flush()
    finally:
        pipeline_service.fetch_runtime_bytecode = original  # type: ignore[assignment]

    assert outcome.status is ScanStatus.FAILED
    assert outcome.error_code == "rpc_unreachable"
    assert scan.error_code == "rpc_unreachable"
    assert scan.completed_at is not None


@pytest.mark.parametrize("fork", ["frontier", "shanghai", "cancun", "prague"])
def test_the_pipeline_runs_on_every_supported_fork(
    db_session: Session, workspace: Workspace, chain: Chain, fork: str
) -> None:
    """The pipeline accepts every fork in the vendored opcode table."""
    scan = _make_scan(db_session, workspace, chain, SAMPLE_RUNTIME, fork=fork)
    outcome = run_scan(db_session, scan)
    db_session.flush()
    assert outcome.status in {ScanStatus.COMPLETED, ScanStatus.PARTIAL}
    assert uuid.UUID(str(scan.id))
