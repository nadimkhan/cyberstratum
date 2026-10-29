"""Tests for the on-demand correspondence worker job.

This is where the distinction that matters most is enforced in the database:
a compiler that failed is *unavailable*, and a real difference in executable
code is a *mismatch*. Collapsing the two would accuse a contract on the
strength of a broken toolchain.
"""

from __future__ import annotations

import contextlib
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.db.enums import CorrespondenceStatus, ScanJobStatus, ScanStatus
from app.db.models.scans import CorrespondenceProof, Scan, ScanArtifact, ScanJob
from app.services import storage
from app.services.correspondence import CorrespondenceOutcome, SourceLocation
from app.worker import CORRESPONDENCE_WORKER_NAME, process_correspondence_job

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


def _proofs(session: Session, scan_id: uuid.UUID) -> list[CorrespondenceProof]:
    return session.query(CorrespondenceProof).filter(CorrespondenceProof.scan_id == scan_id).all()


def test_a_scan_without_a_bytecode_artifact_records_a_skip(
    db_session: Session, workspace: Any, target: Any, worker_session: Session
) -> None:
    """Without stored bytecode the proof cannot run, and that is recorded."""
    scan = _make_scan(db_session, workspace.id, target.id)
    scan_id = scan.id

    result = process_correspondence_job(str(scan_id))

    assert result["status"] == CorrespondenceStatus.SKIPPED.value
    assert result["skipped"] == "bytecode_artifact_missing"

    proofs = _proofs(db_session, scan_id)
    assert len(proofs) == 1
    assert proofs[0].status is CorrespondenceStatus.SKIPPED
    assert proofs[0].skipped == "bytecode_artifact_missing"


def test_a_missing_scan_is_reported_rather_than_raised(worker_session: Session) -> None:
    """An unknown scan id is reported, not raised."""
    result = process_correspondence_job(str(uuid.uuid4()))
    assert result["status"] == "not_found"


def test_an_established_proof_is_stored_with_its_hashes(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    workspace: Any,
    target: Any,
    worker_session: Session,
) -> None:
    """The stored proof carries the hashes, the compiler and the line map."""
    import app.worker as worker_module

    outcome = CorrespondenceOutcome(
        status=CorrespondenceStatus.ESTABLISHED,
        detail="executable code identical",
        compiler_version="0.8.26+commit.8a97fa7a",
        source_path="A.sol",
        contract_name="A",
        runtime_sha256="a" * 64,
        executable_sha256="b" * 64,
        metadata_sha256="c" * 64,
        runtime_byte_size=5,
        executable_byte_size=5,
        instruction_count=3,
        mapped_instruction_count=1,
        locations=(
            SourceLocation(offset=4, opcode="SSTORE", file="A.sol", line=12, snippet="sstore"),
        ),
    )

    class FakeProver:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        def prove(self, address: str, chain_id: str, bytecode: bytes) -> CorrespondenceOutcome:
            assert bytecode == RUNTIME_BYTECODE
            return outcome

    monkeypatch.setattr(worker_module, "CorrespondenceProver", FakeProver)

    scan = _make_scan(db_session, workspace.id, target.id)
    _store_bytecode(db_session, scan)
    scan_id = scan.id

    result = process_correspondence_job(str(scan_id))

    assert result["status"] == CorrespondenceStatus.ESTABLISHED.value

    proofs = _proofs(db_session, scan_id)
    assert len(proofs) == 1
    proof = proofs[0]
    assert proof.status is CorrespondenceStatus.ESTABLISHED
    assert proof.source_path == "A.sol"
    assert proof.compiler_version == "0.8.26+commit.8a97fa7a"
    assert proof.runtime_sha256 == "a" * 64
    assert proof.executable_sha256 == "b" * 64
    assert proof.mapped_instruction_count == 1
    assert proof.proof_json is not None
    assert proof.proof_json["locations"][0]["line"] == 12


def test_a_mismatch_is_stored_as_a_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    workspace: Any,
    target: Any,
    worker_session: Session,
) -> None:
    """A real difference in executable code is a mismatch."""
    import app.worker as worker_module

    outcome = CorrespondenceOutcome(
        status=CorrespondenceStatus.MISMATCH,
        detail="executable code differs -> first differing byte at offset 0x1",
    )

    class FakeProver:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        def prove(self, address: str, chain_id: str, bytecode: bytes) -> CorrespondenceOutcome:
            return outcome

    monkeypatch.setattr(worker_module, "CorrespondenceProver", FakeProver)

    scan = _make_scan(db_session, workspace.id, target.id)
    _store_bytecode(db_session, scan)
    scan_id = scan.id

    result = process_correspondence_job(str(scan_id))

    assert result["status"] == CorrespondenceStatus.MISMATCH.value
    proofs = _proofs(db_session, scan_id)
    assert len(proofs) == 1
    assert proofs[0].status is CorrespondenceStatus.MISMATCH


def test_a_crashed_prover_is_recorded_as_unavailable_not_mismatched(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    workspace: Any,
    target: Any,
    worker_session: Session,
) -> None:
    """A tooling failure must never become an accusation against a contract."""
    import app.worker as worker_module

    class ExplodingProver:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        def prove(self, address: str, chain_id: str, bytecode: bytes) -> CorrespondenceOutcome:
            raise RuntimeError("the prover died")

    monkeypatch.setattr(worker_module, "CorrespondenceProver", ExplodingProver)

    scan = _make_scan(db_session, workspace.id, target.id)
    _store_bytecode(db_session, scan)
    scan_id = scan.id

    result = process_correspondence_job(str(scan_id))

    assert result["status"] == CorrespondenceStatus.UNAVAILABLE.value
    proofs = _proofs(db_session, scan_id)
    assert len(proofs) == 1
    assert proofs[0].status is CorrespondenceStatus.UNAVAILABLE
    assert proofs[0].skipped == "prover_error"


def test_the_job_row_records_the_attempt(
    db_session: Session, workspace: Any, target: Any, worker_session: Session
) -> None:
    """The correspondence job row is marked finished with its attempt count."""
    scan = _make_scan(db_session, workspace.id, target.id)
    job = ScanJob(
        scan_id=scan.id,
        queue_name="cyberstratum:correspondence",
        status=ScanJobStatus.QUEUED,
    )
    db_session.add(job)
    db_session.flush()
    job_id = job.id

    process_correspondence_job(str(scan.id), str(job_id))

    db_session.refresh(job)
    assert job.status is ScanJobStatus.FINISHED
    assert job.attempt == 1
    assert job.finished_at is not None


def test_the_correspondence_worker_has_its_own_name() -> None:
    """The correspondence worker must not register under the scan worker's name."""
    assert CORRESPONDENCE_WORKER_NAME != "cyberstratum-worker"
    assert CORRESPONDENCE_WORKER_NAME.startswith("cyberstratum-worker")
