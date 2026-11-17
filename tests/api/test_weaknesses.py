"""Tests for the weakness taxonomy and the classes it puts on findings.

A finding that names a weakness class must be able to say where the
class came from, and a finding whose detector has no recorded
correspondence must say that plainly rather than be given a class.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.enums import FindingStatus, ScanStatus, Severity
from app.db.models.scans import Finding, Scan
from app.services.knowledge import load_seed
from app.services.weaknesses import (
    load_correspondence,
    load_taxonomy,
    taxonomy_provenance,
    weakness_for,
)


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


def _add_finding(session: Session, scan: Scan, detector_id: str) -> Finding:
    finding = Finding(
        workspace_id=scan.workspace_id,
        scan_id=scan.id,
        detector_id=detector_id,
        detector_version="0.1.0",
        category="reentrancy_candidate",
        title=f"{detector_id} finding",
        description="A deterministic test finding.",
        severity=Severity.HIGH,
        confidence=0.5,
        status=FindingStatus.NEW,
        evidence_json={"offsets": [1, 2]},
        limitations="Test data.",
    )
    session.add(finding)
    session.flush()
    return finding


def test_the_taxonomy_is_served_with_where_it_came_from(
    client: TestClient, api_headers: dict[str, str]
) -> None:
    """The taxonomy says what it is and where it came from."""
    response = client.get("/api/v1/knowledge/weaknesses", headers=api_headers)
    assert response.status_code == 200
    body = response.json()

    assert body["total"] == len(body["items"])
    assert body["total"] >= 30

    provenance = body["provenance"]
    assert provenance["spdx_id"] == "MIT"
    assert provenance["upstream_revision"]
    assert provenance["upstream_url"]
    # The registry says of itself that it is no longer maintained. The
    # product says so too rather than quietly using it as guidance.
    assert provenance["unmaintained"] is True
    assert provenance["note"]


def test_every_correspondence_names_a_detector_that_has_guidance() -> None:
    """A correspondence about a detector nobody has heard of is a mistake."""
    known = set(load_seed())
    for detector_id in load_correspondence():
        assert detector_id in known, f"{detector_id} has no guidance"


def test_every_correspondence_names_a_class_the_registry_holds() -> None:
    """A correspondence to a class that does not exist is a mistake."""
    known = set(load_taxonomy())
    for correspondence in load_correspondence().values():
        for swc_id in correspondence.swc_ids:
            assert swc_id in known, f"{swc_id} is not in the registry"


def test_a_correspondence_says_who_is_making_the_claim() -> None:
    """Every correspondence says who is making the claim, and why."""
    for correspondence in load_correspondence().values():
        assert correspondence.source
        assert correspondence.basis


def test_a_finding_carries_the_class_of_its_detector(
    client: TestClient, api_headers: dict[str, str], db_session: Session, scan: Scan
) -> None:
    """The finding says which weakness class it belongs to."""
    _add_finding(db_session, scan, "slither.tx_origin")
    db_session.flush()

    response = client.get("/api/v1/findings", headers=api_headers)
    assert response.status_code == 200
    items = [
        item for item in response.json()["items"] if item["detector_id"] == "slither.tx_origin"
    ]
    assert items, "the finding was not listed"

    weakness = items[0]["weakness"]
    assert weakness is not None
    assert weakness["swc_id"] == "SWC-115"
    assert weakness["title"] == "Authorization through tx.origin"
    assert "CWE-477" in weakness["cwe_ids"]
    assert weakness["basis"]
    assert weakness["source"]


def test_a_finding_with_no_correspondence_has_no_class(
    client: TestClient, api_headers: dict[str, str], db_session: Session, scan: Scan
) -> None:
    """A detector with no recorded correspondence gets no invented class."""
    _add_finding(db_session, scan, "baseline.unmapped_detector")
    db_session.flush()

    response = client.get("/api/v1/findings", headers=api_headers)
    assert response.status_code == 200
    items = [
        item
        for item in response.json()["items"]
        if item["detector_id"] == "baseline.unmapped_detector"
    ]
    assert items, "the finding was not listed"
    assert items[0]["weakness"] is None


def test_the_summary_counts_the_classes(
    client: TestClient, api_headers: dict[str, str], db_session: Session, scan: Scan
) -> None:
    """The breakdown says how many findings belong to each class."""
    _add_finding(db_session, scan, "slither.tx_origin")
    db_session.flush()

    response = client.get("/api/v1/findings/summary", headers=api_headers)
    assert response.status_code == 200
    body = response.json()

    entries = {entry["swc_id"]: entry for entry in body["by_weakness"]}
    assert "SWC-115" in entries
    assert entries["SWC-115"]["count"] >= 1
    assert entries["SWC-115"]["title"] == "Authorization through tx.origin"


def test_the_provenance_of_the_taxonomy_is_readable() -> None:
    """The provenance is available without a request."""
    provenance = taxonomy_provenance()
    assert provenance["dataset"] == "swc_registry"
    assert provenance["entry_count"] == len(load_taxonomy())
    assert provenance["unmaintained"] is True


def test_a_detector_with_a_correspondence_resolves() -> None:
    """The service resolves a correspondence to the class it names."""
    weakness = weakness_for("baseline.delegatecall")
    assert weakness is not None
    assert weakness["swc_id"] == "SWC-112"
    assert weakness["title"] == "Delegatecall to Untrusted Callee"


def test_the_list_can_be_narrowed_to_a_class(
    client: TestClient, api_headers: dict[str, str], db_session: Session, scan: Scan
) -> None:
    """A class narrows the list the same way a detector does."""
    _add_finding(db_session, scan, "slither.tx_origin")
    _add_finding(db_session, scan, "baseline.unmapped_detector")
    db_session.flush()

    response = client.get("/api/v1/findings?weakness=SWC-115", headers=api_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["items"], "the narrowed list was empty"
    narrowed = {item["detector_id"] for item in body["items"]}
    assert "slither.tx_origin" in narrowed
    assert "baseline.unmapped_detector" not in narrowed, (
        "a finding with no correspondence must not appear under a class"
    )


def test_a_class_nobody_corresponds_to_matches_nothing(
    client: TestClient, api_headers: dict[str, str]
) -> None:
    """A class that does not exist cannot match a finding."""
    response = client.get("/api/v1/findings?weakness=SWC-999", headers=api_headers)
    assert response.status_code == 200
    assert response.json()["items"] == []
