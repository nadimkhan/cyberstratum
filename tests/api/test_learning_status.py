"""Tests for the learning status endpoint."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.enums import FindingStatus, ScanStatus, Severity
from app.db.models.scans import Finding, Scan


@pytest.fixture()
def scan(db_session: Session, workspace: Any, target: Any) -> Scan:
    """Create a completed scan to attach findings to."""
    row = Scan(
        workspace_id=workspace.id,
        target_id=target.id,
        status=ScanStatus.COMPLETED,
        fork="cancun",
        bytecode_source="test",
    )
    db_session.add(row)
    db_session.flush()
    return row


def _add_finding(
    session: Session,
    scan: Scan,
    status: FindingStatus,
    category: str = "reentrancy_candidate",
) -> Finding:
    finding = Finding(
        workspace_id=scan.workspace_id,
        scan_id=scan.id,
        detector_id="baseline.test",
        detector_version="0.1.0",
        category=category,
        title=f"{category} finding",
        description="A deterministic test finding.",
        severity=Severity.HIGH,
        confidence=0.5,
        status=status,
        evidence_json={"offsets": [1, 2]},
        limitations="Test data.",
    )
    session.add(finding)
    session.flush()
    return finding


def test_the_status_reports_the_reviewed_corpus(
    client: TestClient, api_headers: dict[str, str], db_session: Session, scan: Scan
) -> None:
    """Only settled findings count as reviewed evidence."""
    before = client.get("/api/v1/learning/status", headers=api_headers).json()["reviewed"]

    _add_finding(db_session, scan, FindingStatus.CONFIRMED)
    _add_finding(db_session, scan, FindingStatus.FALSE_POSITIVE, "tx_origin_dependency")
    _add_finding(db_session, scan, FindingStatus.NEW)
    db_session.flush()

    response = client.get("/api/v1/learning/status", headers=api_headers)
    assert response.status_code == 200
    body = response.json()
    reviewed = body["reviewed"]

    # The settled findings are counted; the unsettled one is not.
    assert reviewed["total"] == before["total"] + 2
    assert reviewed["confirmed"] == before["confirmed"] + 1
    assert reviewed["false_positive"] == before["false_positive"] + 1
    assert reviewed["contracts"] == before["contracts"] + 1
    assert reviewed["categories"] >= before["categories"]


def test_the_status_does_not_invent_a_model(
    client: TestClient, api_headers: dict[str, str]
) -> None:
    """No model means no model, not a broken one."""
    response = client.get("/api/v1/learning/status", headers=api_headers)
    assert response.status_code == 200
    body = response.json()

    assert body["model"] is None
    assert isinstance(body["reviewed"]["total"], int)

    # A cycle that has run is reported as it happened; one that has not
    # is absent rather than invented.
    cycle = body["last_cycle"]
    assert cycle is None or "promotable" in cycle


def test_the_status_needs_a_credential(
    client: TestClient,
) -> None:
    """The state of the model is not public."""
    response = client.get("/api/v1/learning/status")
    assert response.status_code in (401, 403)
