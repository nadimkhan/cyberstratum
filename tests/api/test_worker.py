"""Tests for the scan worker and the analysis pipeline."""

from __future__ import annotations

import contextlib
import os
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.db.enums import ScanJobStatus, ScanJobType, ScanStatus
from app.db.models.scans import Scan, ScanJob
from app.services import pipeline as pipeline_service
from app.services.bytecode import BytecodeArtifact, BytecodeUnavailableError
from app.worker import (
    WORKER_NAME,
    WorkerAlreadyRunningError,
    _missing_scan,
    _process_is_alive,
    clear_stale_worker_registrations,
    process_scan_job,
)

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


def test_a_missing_scan_is_information_not_an_error(
    worker_session: Session, capsys: pytest.CaptureFixture[str]
) -> None:
    """A scan that is gone is an expected outcome, not an error.

    It is what a cascade delete leaves behind, and it used to be logged
    as an error, which trained everyone reading the logs to ignore
    errors.
    """
    result = process_scan_job(str(uuid.uuid4()))

    assert result["status"] == "not_found"
    output = capsys.readouterr().out
    assert "scan_not_found" in output
    # The renderer differs between the test session and the running
    # service, so the level is matched as a word rather than as JSON.
    assert "info" in output
    assert "error" not in output


def test_a_missing_scan_marks_a_live_job_failed(
    db_session: Session, workspace: Any, target: Any
) -> None:
    """If a job row is still there, the work did not happen.

    The foreign key cascades, so in practice a job cannot outlive its
    scan; this covers the race, and pins the contract of the helper.
    """
    scan = _make_scan(db_session, workspace.id, target.id)
    job = ScanJob(
        scan_id=scan.id,
        job_type=ScanJobType.SCAN,
        status=ScanJobStatus.QUEUED,
    )
    db_session.add(job)
    db_session.flush()

    result = _missing_scan(db_session, job, str(scan.id), "scan_not_found")
    db_session.flush()

    assert result["status"] == "not_found"
    db_session.expire_all()
    refreshed = db_session.get(ScanJob, job.id)
    assert refreshed is not None
    assert refreshed.status is ScanJobStatus.FAILED
    assert refreshed.resource_usage is not None
    assert "no longer exists" in str(refreshed.resource_usage.get("error"))


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


class FakeRegistration:
    """Stand-in for an RQ worker registration."""

    def __init__(self, name: str, pid: int | None) -> None:
        self.name = name
        self.pid = pid
        self.death_registered = False

    def register_death(self) -> None:
        self.death_registered = True


def test_a_registration_whose_process_is_gone_is_cleared() -> None:
    """A worker killed hard leaves its registration behind; it is cleared."""
    stale = FakeRegistration(WORKER_NAME, 999999)

    cleared = clear_stale_worker_registrations([stale], is_alive=lambda pid: False)

    assert cleared == [WORKER_NAME]
    assert stale.death_registered is True


def test_a_registration_whose_process_is_alive_is_kept_and_reported() -> None:
    """A genuinely running worker is not removed: that would double the queue."""
    live = FakeRegistration(WORKER_NAME, 4242)

    with pytest.raises(WorkerAlreadyRunningError) as excinfo:
        clear_stale_worker_registrations([live], is_alive=lambda pid: True)

    assert "already running" in str(excinfo.value)
    assert live.death_registered is False


def test_registrations_with_another_name_are_left_alone() -> None:
    """Only this deployment's worker name is reconciled."""
    other = FakeRegistration("some-other-worker", 999999)

    cleared = clear_stale_worker_registrations([other], is_alive=lambda pid: False)

    assert cleared == []
    assert other.death_registered is False


def test_a_missing_pid_is_treated_as_a_dead_process() -> None:
    """A registration whose pid cannot be resolved must not block a restart."""
    unknown = FakeRegistration(WORKER_NAME, None)

    cleared = clear_stale_worker_registrations([unknown], is_alive=_process_is_alive)

    assert cleared == [WORKER_NAME]
    assert unknown.death_registered is True


def test_the_current_process_is_reported_as_alive() -> None:
    assert _process_is_alive(os.getpid()) is True


def test_an_impossible_pid_is_reported_as_dead() -> None:
    # 0 is never a valid process id on Windows or POSIX.
    assert _process_is_alive(0) is False
    assert _process_is_alive(-1) is False
    assert _process_is_alive(None) is False
