"""Tests for the on-demand Mythril worker job.

The job is where the "no verdict is never clean" rule is actually enforced
in the database. The API says a run was queued; this is the code that decides
what the scan records afterwards.
"""

from __future__ import annotations

import contextlib
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.db.enums import ScanJobStatus, ScanStatus
from app.db.models.scans import Finding, Scan, ScanArtifact, ScanJob
from app.services import storage
from app.services.mythril import MythrilFinding, MythrilResult
from app.worker import MYTHRIL_WORKER_NAME, process_mythril_job

#: Runtime bytecode with a DELEGATECALL, so the bytecode rules also fire.
RUNTIME_BYTECODE = bytes.fromhex("60006000f4")


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
        status=ScanStatus.COMPLETED,
        fork="cancun",
        bytecode_source="rpc",
    )
    session.add(scan)
    session.flush()
    return scan


def _store_bytecode(session: Session, scan: Scan) -> None:
    """Store the runtime bytecode exactly as the pipeline would."""
    key = storage.put_bytes(f"scans/{scan.id}/bytecode.bin", RUNTIME_BYTECODE)
    session.add(
        ScanArtifact(
            scan_id=scan.id,
            kind="bytecode",
            content_type="application/octet-stream",
            object_key=key,
            byte_size=len(RUNTIME_BYTECODE),
        )
    )
    session.flush()


def test_a_scan_without_a_bytecode_artifact_records_no_verdict(
    db_session: Session, workspace: Any, target: Any, worker_session: Session
) -> None:
    """Without stored bytecode Mythril cannot run, and that is recorded."""
    scan = _make_scan(db_session, workspace.id, target.id)
    scan_id = scan.id

    result = process_mythril_job(str(scan_id))

    assert result["status"] == "no_verdict"
    assert result["skipped"] == "bytecode_artifact_missing"

    db_session.refresh(scan)
    assert scan.mythril_ran is False
    assert scan.mythril_skipped == "bytecode_artifact_missing"


def test_a_missing_scan_is_reported_rather_than_raised(worker_session: Session) -> None:
    """An unknown scan id is reported, not raised."""
    result = process_mythril_job(str(uuid.uuid4()))
    assert result["status"] == "not_found"


def test_findings_from_mythril_are_stored_with_their_own_provenance(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    workspace: Any,
    target: Any,
    worker_session: Session,
) -> None:
    """A Mythril finding is stored with source='mythril', not as a rule finding."""
    import app.worker as worker_module

    result = MythrilResult(
        findings=(
            MythrilFinding(
                swc_id="105",
                title="Reentrancy",
                severity="high",
                description="State variable changes after a call.",
            ),
        ),
        ran=True,
        skipped=None,
        success=True,
        error=None,
        exit_code=1,
    )

    class FakeRunner:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        def run(
            self, runtime_bytecode: bytes, contract_name: str = "", **_kw: Any
        ) -> MythrilResult:
            assert runtime_bytecode == RUNTIME_BYTECODE
            return result

    monkeypatch.setattr(worker_module, "MythrilRunner", FakeRunner)

    scan = _make_scan(db_session, workspace.id, target.id)
    _store_bytecode(db_session, scan)
    scan_id = scan.id

    outcome = process_mythril_job(str(scan_id))

    assert outcome["status"] == "completed"
    assert outcome["finding_count"] == 1

    db_session.refresh(scan)
    assert scan.mythril_ran is True
    assert scan.mythril_skipped is None

    findings = db_session.query(Finding).filter(Finding.scan_id == scan_id).all()
    assert len(findings) == 1
    assert findings[0].source == "mythril"
    assert findings[0].detector_id.startswith("mythril.")


def test_a_mythril_run_without_a_verdict_is_not_recorded_as_clean(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    workspace: Any,
    target: Any,
    worker_session: Session,
) -> None:
    """A run that produced no verdict leaves the reason, not a clean bill."""
    import app.worker as worker_module

    result = MythrilResult(
        findings=(),
        ran=True,
        skipped="no_output",
        success=None,
        error=None,
        exit_code=0,
    )

    class FakeRunner:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        def run(
            self, runtime_bytecode: bytes, contract_name: str = "", **_kw: Any
        ) -> MythrilResult:
            return result

    monkeypatch.setattr(worker_module, "MythrilRunner", FakeRunner)

    scan = _make_scan(db_session, workspace.id, target.id)
    _store_bytecode(db_session, scan)
    scan_id = scan.id

    outcome = process_mythril_job(str(scan_id))

    assert outcome["status"] == "no_verdict"
    assert outcome["skipped"] == "no_output"

    db_session.refresh(scan)
    assert scan.mythril_ran is False
    assert scan.mythril_skipped == "no_output"
    assert db_session.query(Finding).filter(Finding.scan_id == scan_id).count() == 0


def test_an_engine_crash_is_recorded_as_an_error_not_a_clean_result(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    workspace: Any,
    target: Any,
    worker_session: Session,
) -> None:
    """An exception inside the engine is a failure, never a clean result."""
    import app.worker as worker_module

    class ExplodingRunner:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        def run(
            self, runtime_bytecode: bytes, contract_name: str = "", **_kw: Any
        ) -> MythrilResult:
            raise RuntimeError("the engine died")

    monkeypatch.setattr(worker_module, "MythrilRunner", ExplodingRunner)

    scan = _make_scan(db_session, workspace.id, target.id)
    _store_bytecode(db_session, scan)
    scan_id = scan.id

    outcome = process_mythril_job(str(scan_id))

    assert outcome["status"] == "failed"

    db_session.refresh(scan)
    assert scan.mythril_ran is False
    assert scan.mythril_skipped == "engine_error"


def test_the_job_row_records_the_attempt(
    db_session: Session, workspace: Any, target: Any, worker_session: Session
) -> None:
    """The Mythril job row is marked finished with its attempt count."""
    scan = _make_scan(db_session, workspace.id, target.id)
    job = ScanJob(
        scan_id=scan.id,
        queue_name="cyberstratum:mythril",
        status=ScanJobStatus.QUEUED,
    )
    db_session.add(job)
    db_session.flush()
    job_id = job.id

    process_mythril_job(str(scan.id), str(job_id))

    db_session.refresh(job)
    assert job.status is ScanJobStatus.FINISHED
    assert job.attempt == 1
    assert job.finished_at is not None


def test_the_mythril_worker_has_its_own_name() -> None:
    """The Mythril worker must not register under the scan worker's name."""
    assert MYTHRIL_WORKER_NAME != "cyberstratum-worker"
    assert MYTHRIL_WORKER_NAME.startswith("cyberstratum-worker")
