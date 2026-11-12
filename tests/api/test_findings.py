"""Tests for the findings endpoints."""

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
    session: Session, scan: Scan, severity: Severity, category: str = "reentrancy_candidate"
) -> Finding:
    finding = Finding(
        workspace_id=scan.workspace_id,
        scan_id=scan.id,
        detector_id="baseline.test",
        detector_version="0.1.0",
        category=category,
        title=f"{category} finding",
        description="A deterministic test finding.",
        severity=severity,
        confidence=0.5,
        status=FindingStatus.NEW,
        evidence_json={"offsets": [1, 2]},
        limitations="Test data.",
    )
    session.add(finding)
    session.flush()
    return finding


def test_list_findings(
    client: TestClient, api_headers: dict[str, str], db_session: Session, scan: Scan
) -> None:
    """Findings are listed with their evidence."""
    _add_finding(db_session, scan, Severity.HIGH)
    db_session.flush()

    response = client.get("/api/v1/findings", headers=api_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["total"] >= 1
    first = body["items"][0]
    assert first["severity"] == "high"
    assert first["evidence"] == {"offsets": [1, 2]}


def test_list_findings_filters_by_severity(
    client: TestClient, api_headers: dict[str, str], db_session: Session, scan: Scan
) -> None:
    """The findings list can be filtered by severity."""
    _add_finding(db_session, scan, Severity.HIGH)
    _add_finding(db_session, scan, Severity.LOW, category="tx_origin_dependency")
    db_session.flush()

    response = client.get("/api/v1/findings?severity=low", headers=api_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["total"] >= 1
    assert all(item["severity"] == "low" for item in body["items"])


def test_list_findings_filters_by_scan(
    client: TestClient, api_headers: dict[str, str], db_session: Session, scan: Scan
) -> None:
    """The findings list can be filtered by scan id."""
    _add_finding(db_session, scan, Severity.MEDIUM)
    db_session.flush()

    response = client.get(f"/api/v1/findings?scan_id={scan.id}", headers=api_headers)
    assert response.status_code == 200
    assert response.json()["total"] >= 1


def test_severity_breakdown(
    client: TestClient, api_headers: dict[str, str], db_session: Session, scan: Scan
) -> None:
    """The summary endpoint aggregates findings by severity and status."""
    _add_finding(db_session, scan, Severity.HIGH)
    _add_finding(db_session, scan, Severity.HIGH, category="delegatecall_usage")
    _add_finding(db_session, scan, Severity.LOW, category="tx_origin_dependency")
    db_session.flush()

    response = client.get("/api/v1/findings/summary", headers=api_headers)
    assert response.status_code == 200
    body = response.json()
    severities = {item["severity"]: item["count"] for item in body["by_severity"]}
    assert severities.get("high", 0) >= 2
    assert severities.get("low", 0) >= 1
    assert body["total"] >= 3
    assert body["by_status"]
    assert 0.0 <= body["average_confidence"] <= 1.0


def test_findings_require_authentication(
    client: TestClient, db_session: Session, scan: Scan
) -> None:
    """Listing findings without an API key is rejected."""
    _add_finding(db_session, scan, Severity.INFO)
    db_session.flush()

    response = client.get("/api/v1/findings")
    assert response.status_code == 401


def test_severity_breakdown_names_the_detectors(
    client: TestClient, api_headers: dict[str, str], db_session: Session, scan: Scan
) -> None:
    """The summary names which detectors fire, not only how bad the findings are."""
    delegatecall = _add_finding(db_session, scan, Severity.HIGH)
    tx_origin = _add_finding(db_session, scan, Severity.LOW, category="tx_origin_dependency")
    delegatecall.detector_id = "baseline.delegatecall"
    tx_origin.detector_id = "baseline.tx_origin"
    db_session.flush()

    response = client.get("/api/v1/findings/summary", headers=api_headers)
    assert response.status_code == 200
    detectors = {item["detector_id"]: item["count"] for item in response.json()["by_detector"]}
    assert detectors.get("baseline.delegatecall", 0) >= 1
    assert detectors.get("baseline.tx_origin", 0) >= 1


def test_severity_breakdown_names_the_chains(
    client: TestClient, api_headers: dict[str, str], db_session: Session, scan: Scan
) -> None:
    """The summary says which chain the findings came from."""
    _add_finding(db_session, scan, Severity.HIGH)
    db_session.flush()

    response = client.get("/api/v1/findings/summary", headers=api_headers)
    assert response.status_code == 200
    chains = response.json()["by_chain"]
    assert chains
    assert all("chain_id" in item and "chain_name" in item for item in chains)
    assert all(item["count"] >= 1 for item in chains)


def test_list_findings_filters_by_detector(
    client: TestClient, api_headers: dict[str, str], db_session: Session, scan: Scan
) -> None:
    """The findings list can be filtered by the detector that raised them."""
    finding = _add_finding(db_session, scan, Severity.HIGH)
    finding.detector_id = "baseline.delegatecall"
    db_session.flush()

    response = client.get("/api/v1/findings?detector_id=baseline.delegatecall", headers=api_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["total"] >= 1
    assert all(item["detector_id"] == "baseline.delegatecall" for item in body["items"])


def test_list_findings_filters_by_chain(
    client: TestClient, api_headers: dict[str, str], db_session: Session, scan: Scan
) -> None:
    """The findings list can be filtered by the chain they came from."""
    _add_finding(db_session, scan, Severity.HIGH)
    db_session.flush()

    response = client.get("/api/v1/findings?chain_id=1", headers=api_headers)
    assert response.status_code == 200
    assert response.json()["total"] >= 1

    empty = client.get("/api/v1/findings?chain_id=999999", headers=api_headers)
    assert empty.status_code == 200
    assert empty.json()["total"] == 0
