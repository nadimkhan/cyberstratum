"""Tests for the scan worker and the analysis pipeline."""

from __future__ import annotations

import contextlib
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.db.enums import ScanJobStatus, ScanStatus
from app.db.models.scans import Scan
from app.services import pipeline as pipeline_service
from app.services.bytecode import BytecodeArtifact, BytecodeUnavailableError
from app.worker import process_scan_job

#: Runtime bytecode with a DELEGATECALL so the baseline rules produce a finding.
DELEGATECALL_BYTECODE = bytes.fromhex("60006000f4")


@pytest.fixture()
def fake_bytecode(monkeypatch: pytest.MonkeyPatch) -> bytes:
    """Replace the RPC fetch with a deterministic bytecode source."""
    code = DELEGATECALL_BYTECODE

    def fake_fetch(address: str, chain_id: int = 1, **_: Any) -> BytecodeArtifact:
        return BytecodeArtifact(code=code, source="test", address=address)

    monkeypatch.setattr(pipeline_service, "fetch_runtime_bytecode", fake_fetch)
    return code


@pytest.fixture()
def worker_session(monkeypatch: pytest.MonkeyPatch, db_session: Session) -> Iterator[Session]:
    """Make the worker use the test transaction instead of a new connection."""

    @contextlib.contextmanager
    def fake_scope() -> Iterator[Session]:
        yield db_session

    monkeypatch.setattr("app.worker.session_scope", fake_scope)
    yield db_session


def _make_scan(session: Session, workspace_id: uuid.UUID, target_id: uuid.UUID) -> Scan:
    scan = Scan(
        workspace_id=workspace_id,
        target_id=target_id,
        status=ScanStatus.QUEUED,
        fork="cancun",
        bytecode_source="rpc",
    )
    session.add(scan)
    session.flush()
    return scan


def test_worker_runs_pipeline_and_records_findings(
    db_session: Session, workspace: Any, target: Any, fake_bytecode: bytes, worker_session: Session
) -> None:
    """A successful scan stores findings and artifacts."""
    scan = _make_scan(db_session, workspace.id, target.id)
    scan_id = scan.id

    result = process_scan_job(str(scan_id))

    assert result["status"] in {ScanStatus.COMPLETED.value, ScanStatus.PARTIAL.value}
    assert result["finding_count"] >= 1

    db_session.refresh(scan)
    assert scan.status in {ScanStatus.COMPLETED, ScanStatus.PARTIAL}
    assert scan.parser_version is not None
    assert scan.ruleset_version is not None
    assert len(scan.findings) >= 1
    assert len(scan.artifacts) >= 3


def test_worker_records_failure_when_bytecode_unavailable(
    monkeypatch: pytest.MonkeyPatch, db_session: Session, workspace: Any, target: Any,
    worker_session: Session,
) -> None:
    """A missing bytecode source is recorded as a failed scan, not a crash."""

    def fake_fetch(address: str, chain_id: int = 1, **_: Any) -> BytecodeArtifact:
        raise BytecodeUnavailableError("no rpc reachable", code="rpc_unreachable")

    monkeypatch.setattr(pipeline_service, "fetch_runtime_bytecode", fake_fetch)

    scan = _make_scan(db_session, workspace.id, target.id)
    scan_id = scan.id

    result = process_scan_job(str(scan_id))

    assert result["status"] == ScanStatus.FAILED.value
    assert result["error_code"] == "rpc_unreachable"

    db_session.refresh(scan)
    assert scan.status is ScanStatus.FAILED
    assert scan.error_code == "rpc_unreachable"
    assert scan.error_message_redacted is not None


def test_worker_marks_job_finished(
    db_session: Session, workspace: Any, target: Any, fake_bytecode: bytes, worker_session: Session
) -> None:
    """The scan job row records the attempt and terminal status."""
    from app.db.models.scans import ScanJob

    scan = _make_scan(db_session, workspace.id, target.id)
    job = ScanJob(scan_id=scan.id, queue_name="cyberstratum", status=ScanJobStatus.QUEUED)
    db_session.add(job)
    db_session.flush()
    job_id = job.id

    process_scan_job(str(scan.id), str(job_id))

    db_session.refresh(job)
    assert job.status is ScanJobStatus.FINISHED
    assert job.attempt == 1
    assert job.finished_at is not None


def test_worker_handles_missing_scan(worker_session: Session) -> None:
    """An unknown scan id is reported rather than raising."""
    result = process_scan_job(str(uuid.uuid4()))
    assert result["status"] == "not_found"
