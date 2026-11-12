"""Tests for the label export.

These tests are about one thing: the export must not put a label on a
contract that nobody reviewed. "Not looked at yet" is not "not
vulnerable", and a training set that makes that assumption teaches the
model the mistake this product exists to avoid.
"""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy.orm import Session

from app.db.enums import FindingStatus, ScanStatus, Severity
from app.db.models.identity import Chain, ContractTarget, Workspace
from app.db.models.scans import Finding, Scan, ScanArtifact
from app.services.label_export import (
    DETECTOR_CATEGORIES,
    LABEL_CATEGORIES,
    build_records,
    write_dataset,
)

#: A runtime with a DELEGATECALL, which the baseline rules report.
SAMPLE_BYTECODE = bytes.fromhex("3260005260006000f400")


def _scan_with_bytecode(
    session: Session,
    workspace: Workspace,
    chain: Chain,
    storage_root: Path,
    *,
    address: str = "0x" + "aa" * 20,
    code: bytes = SAMPLE_BYTECODE,
) -> Scan:
    """Create a scan with its bytecode stored the way the pipeline stores it."""
    target = ContractTarget(
        workspace_id=workspace.id,
        chain_id=chain.id,
        address=address,
        label="export target",
        bytecode_type="runtime",
        authorization_status="unknown",
    )
    session.add(target)
    session.flush()

    scan = Scan(
        workspace_id=workspace.id,
        target_id=target.id,
        status=ScanStatus.COMPLETED,
        fork="cancun",
        bytecode_source="test",
    )
    session.add(scan)
    session.flush()

    key = f"scans/{scan.id}/bytecode.bin"
    (storage_root / key).parent.mkdir(parents=True, exist_ok=True)
    (storage_root / key).write_bytes(code)
    session.add(
        ScanArtifact(
            scan_id=scan.id,
            kind="bytecode",
            content_type="application/octet-stream",
            object_key=key,
            byte_size=len(code),
        )
    )
    session.flush()
    return scan


def _finding(
    session: Session,
    scan: Scan,
    detector_id: str,
    status: FindingStatus,
    *,
    note: str | None = None,
) -> Finding:
    finding = Finding(
        workspace_id=scan.workspace_id,
        scan_id=scan.id,
        detector_id=detector_id,
        detector_version="0.1.0",
        category="test",
        title="a finding",
        description="a finding",
        severity=Severity.MEDIUM,
        confidence=0.5,
        status=status,
        review_note=note,
    )
    session.add(finding)
    session.flush()
    return finding


def test_a_confirmed_finding_makes_its_category_true(
    db_session: Session, workspace: Workspace, chain: Chain, tmp_path: Path
) -> None:
    scan = _scan_with_bytecode(db_session, workspace, chain, tmp_path)
    _finding(
        db_session,
        scan,
        "baseline.delegatecall",
        FindingStatus.CONFIRMED,
        note="the target is attacker controlled",
    )

    export = build_records(db_session, storage_root=tmp_path)

    assert len(export.records) == 1
    labels = export.records[0]["labels"]
    assert labels["unchecked_call"] is True
    assert labels["reentrancy"] is False
    assert export.records[0]["label_source"] == "human-review"


def test_a_false_positive_makes_its_category_false(
    db_session: Session, workspace: Workspace, chain: Chain, tmp_path: Path
) -> None:
    scan = _scan_with_bytecode(db_session, workspace, chain, tmp_path)
    _finding(
        db_session,
        scan,
        "baseline.tx_origin",
        FindingStatus.FALSE_POSITIVE,
        note="the state is written before the call",
    )

    export = build_records(db_session, storage_root=tmp_path)

    assert len(export.records) == 1
    assert export.records[0]["labels"]["tx_origin"] is False


def test_an_unreviewed_finding_keeps_the_contract_out(
    db_session: Session, workspace: Workspace, chain: Chain, tmp_path: Path
) -> None:
    """A category nobody looked at is not a negative label."""
    scan = _scan_with_bytecode(db_session, workspace, chain, tmp_path)
    _finding(
        db_session,
        scan,
        "baseline.delegatecall",
        FindingStatus.CONFIRMED,
        note="real",
    )
    _finding(db_session, scan, "baseline.selfdestruct", FindingStatus.NEW)

    export = build_records(db_session, storage_root=tmp_path)

    assert export.records == []
    assert export.skipped_unsettled == 1


def test_a_detector_outside_the_vocabulary_is_ignored(
    db_session: Session, workspace: Workspace, chain: Chain, tmp_path: Path
) -> None:
    """A finding with no category says nothing about the labels.

    Some detectors report things that are not vulnerability classes at
    all -- a stack-depth anomaly, an unresolved jump. They cannot carry a
    label, and they must not disqualify a contract that was reviewed
    properly, or the dataset stays empty for no gain.
    """
    scan = _scan_with_bytecode(db_session, workspace, chain, tmp_path)
    _finding(db_session, scan, "baseline.delegatecall", FindingStatus.CONFIRMED)
    _finding(db_session, scan, "baseline.stack_underflow", FindingStatus.NEW)

    export = build_records(db_session, storage_root=tmp_path)

    assert len(export.records) == 1
    assert export.records[0]["labels"]["unchecked_call"] is True
    assert export.ignored_unmapped == 1


def test_exact_clones_share_a_family(
    db_session: Session, workspace: Workspace, chain: Chain, tmp_path: Path
) -> None:
    first = _scan_with_bytecode(db_session, workspace, chain, tmp_path, address="0x" + "aa" * 20)
    second = _scan_with_bytecode(db_session, workspace, chain, tmp_path, address="0x" + "bb" * 20)
    _finding(db_session, first, "baseline.delegatecall", FindingStatus.CONFIRMED)
    _finding(db_session, second, "baseline.delegatecall", FindingStatus.CONFIRMED)

    export = build_records(db_session, storage_root=tmp_path)

    assert len(export.records) == 2
    assert export.records[0]["family"] == export.records[1]["family"]


def test_different_bytecode_is_a_different_family(
    db_session: Session, workspace: Workspace, chain: Chain, tmp_path: Path
) -> None:
    first = _scan_with_bytecode(db_session, workspace, chain, tmp_path, address="0x" + "aa" * 20)
    second = _scan_with_bytecode(
        db_session,
        workspace,
        chain,
        tmp_path,
        address="0x" + "bb" * 20,
        code=bytes.fromhex("6000556000"),
    )
    _finding(db_session, first, "baseline.delegatecall", FindingStatus.CONFIRMED)
    _finding(db_session, second, "baseline.delegatecall", FindingStatus.CONFIRMED)

    export = build_records(db_session, storage_root=tmp_path)

    assert export.records[0]["family"] != export.records[1]["family"]


def test_the_dataset_file_carries_its_provenance(
    db_session: Session, workspace: Workspace, chain: Chain, tmp_path: Path
) -> None:
    scan = _scan_with_bytecode(db_session, workspace, chain, tmp_path)
    _finding(db_session, scan, "baseline.delegatecall", FindingStatus.CONFIRMED)

    export = build_records(db_session, storage_root=tmp_path)
    path = write_dataset(export, tmp_path / "dataset.jsonl")

    lines = path.read_text(encoding="utf-8").strip().splitlines()
    header = json.loads(lines[0])
    assert "__dataset__" in header
    assert header["__dataset__"]["provenance"]["label_source"] == "human-review"
    assert "not the presence or absence" in header["__dataset__"]["description"]

    record = json.loads(lines[1])
    assert set(record["labels"]) == set(LABEL_CATEGORIES)
    assert record["bytecode"] == SAMPLE_BYTECODE.hex()


def test_every_detector_mapping_names_a_real_category() -> None:
    for detector, category in DETECTOR_CATEGORIES.items():
        assert category in LABEL_CATEGORIES
        assert detector
