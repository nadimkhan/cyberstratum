"""End-to-end tests for fork resolution in the scan pipeline.

The question these answer is the one a reviewer asks about any scan
result: *which* fork's rules were applied, and how do we know? A scan
analysed under the wrong fork does not fail -- it quietly reports real
opcodes as invalid -- so the answer has to be in the record.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.db.enums import ScanStatus
from app.db.models.identity import Chain, ContractTarget, Workspace
from app.db.models.scans import Scan, ScanArtifact
from app.services.pipeline import run_scan


@pytest.fixture(autouse=True)
def _no_network_source_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the suite off the network."""
    from app.services import pipeline as pipeline_service

    monkeypatch.setattr(
        pipeline_service, "fetch_verified_source", lambda *a, **k: None
    )


#: Uses PUSH0 (0x5f), which arrived in Shanghai.
PUSH0_RUNTIME = bytes.fromhex("5f60005260016000f3")

#: Uses nothing newer than the earliest forks.
PLAIN_RUNTIME = bytes.fromhex("6001600055")


def _make_scan(
    session: Session,
    workspace: Workspace,
    chain: Chain,
    code: bytes,
    *,
    fork: str = "",
    suffix: str = "01",
) -> Scan:
    """Create a target holding ``code`` and a queued scan for it."""
    address = "0x" + suffix * 20
    target = ContractTarget(
        workspace_id=workspace.id,
        chain_id=chain.id,
        address=address,
        label="fork target",
        bytecode_type="runtime",
        authorization_status="unknown",
        inline_bytecode=code,
    )
    session.add(target)
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


def test_a_scan_without_a_fork_infers_it_from_the_bytecode(
    db_session: Session, workspace: Workspace, chain: Chain
) -> None:
    scan = _make_scan(db_session, workspace, chain, PUSH0_RUNTIME)
    run_scan(db_session, scan)
    db_session.flush()

    assert scan.fork == "shanghai"
    assert scan.fork_source == "inferred"
    assert not scan.fork_conflict


def test_a_requested_fork_newer_than_the_code_needs_is_kept(
    db_session: Session, workspace: Workspace, chain: Chain
) -> None:
    scan = _make_scan(db_session, workspace, chain, PLAIN_RUNTIME, fork="cancun")
    run_scan(db_session, scan)
    db_session.flush()

    assert scan.fork == "cancun"
    assert scan.fork_source == "requested"
    assert not scan.fork_conflict


def test_a_requested_fork_older_than_the_code_needs_is_honoured_and_flagged(
    db_session: Session, workspace: Workspace, chain: Chain
) -> None:
    scan = _make_scan(db_session, workspace, chain, PUSH0_RUNTIME, fork="london")
    run_scan(db_session, scan)
    db_session.flush()

    # The request is honoured: analysing under an older fork is a
    # legitimate question, and the older table reporting PUSH0 as
    # invalid is the answer. The disagreement is recorded rather than
    # hidden, so the report can say the contract cannot execute under
    # the analysed fork.
    assert scan.fork == "london"
    assert scan.fork_source == "requested"
    assert scan.fork_conflict


def test_the_resolution_is_stored_as_an_artifact(
    db_session: Session, workspace: Workspace, chain: Chain
) -> None:
    scan = _make_scan(db_session, workspace, chain, PUSH0_RUNTIME)
    run_scan(db_session, scan)
    db_session.flush()

    artifact = (
        db_session.query(ScanArtifact)
        .filter(ScanArtifact.scan_id == scan.id)
        .filter(ScanArtifact.kind == "fork_resolution")
        .one()
    )
    assert artifact.object_key.endswith("fork_resolution.json")
