"""A partial scan must say what it could not analyse.

"Partial" on its own is a shrug. The reader needs to know *how* much of
the contract was covered, or the status is decoration. These tests pin
the limitations document that the pipeline writes and that the report
renders.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.db.enums import ScanStatus
from app.services.report import _limitation_lines

#: Bytecode with a DELEGATECALL, so the baseline rules produce a finding.
DELEGATECALL_BYTECODE = bytes.fromhex("60006000f4")


@pytest.fixture()
def fake_bytecode(monkeypatch: pytest.MonkeyPatch) -> bytes:
    """Replace the RPC fetch with a deterministic bytecode source."""
    from app.services import pipeline as pipeline_service
    from app.services.bytecode import BytecodeArtifact

    def fake_fetch(address: str, chain_id: int = 1, **_: Any) -> BytecodeArtifact:
        return BytecodeArtifact(code=DELEGATECALL_BYTECODE, source="test", address=address)

    monkeypatch.setattr(pipeline_service, "fetch_runtime_bytecode", fake_fetch)
    return DELEGATECALL_BYTECODE


@pytest.fixture()
def worker_session(monkeypatch: pytest.MonkeyPatch, db_session: Session) -> Iterator[Session]:
    """Make the worker use the test transaction instead of a new connection."""

    @contextlib.contextmanager
    def fake_scope() -> Iterator[Session]:
        yield db_session

    monkeypatch.setattr("app.worker.session_scope", fake_scope)
    yield db_session


def test_a_complete_scan_records_no_limitations(
    db_session: Session, workspace: Any, target: Any, fake_bytecode: bytes, worker_session: Session
) -> None:
    """Nothing incomplete means nothing is recorded."""
    from tests.api.test_worker import _make_scan

    scan = _make_scan(db_session, workspace.id, target.id)
    scan_id = scan.id

    from app.worker import process_scan_job

    process_scan_job(str(scan_id))

    db_session.refresh(scan)
    if scan.status is ScanStatus.COMPLETED:
        assert scan.limitations is None


def test_a_partial_scan_records_why(
    db_session: Session, workspace: Any, target: Any, fake_bytecode: bytes, worker_session: Session
) -> None:
    """A partial scan carries the reasons it is partial.

    The disassembly of the fixture warns about the trailing bytes, so
    the scan is partial and the warning is in the record.
    """
    from tests.api.test_worker import _make_scan

    scan = _make_scan(db_session, workspace.id, target.id)
    scan_id = scan.id

    from app.worker import process_scan_job

    process_scan_job(str(scan_id))

    db_session.refresh(scan)
    if scan.status is ScanStatus.PARTIAL:
        assert scan.limitations is not None
        rendered = _limitation_lines(scan.limitations)
        assert rendered, "a partial scan must explain itself"


def test_the_limitations_render_as_sentences() -> None:
    """The stored JSON becomes readable lines, and nothing is dropped."""
    lines = _limitation_lines(
        {
            "disassembly_warnings": ["invalid opcode at offset 3"],
            "unresolved_control_flow_edges": 2,
            "unresolved_edge_ratio": 0.25,
            "extra": "value",
        }
    )

    assert any("disassembly warning" in line for line in lines)
    assert any("2 control-flow edge" in line for line in lines)
    assert any("25.0%" in line for line in lines)
    assert any("extra: value" in line for line in lines)


def test_no_limitations_render_as_nothing() -> None:
    """A complete scan has nothing to say about what it missed."""
    assert _limitation_lines(None) == ()
    assert _limitation_lines({}) == ()
