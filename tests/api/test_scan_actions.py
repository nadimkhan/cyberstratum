"""Tests for the on-demand scan actions: Mythril, correspondence and the PDF report.

These three endpoints share one property that matters more than their
individual behaviour: none of them may claim more than they know. A queued
Mythril run is not a verdict, a missing correspondence proof is not a
mismatch, and a report that lists an engine says whether that engine
produced a verdict or not.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api import scans as scans_api
from app.db.enums import CorrespondenceStatus, ScanStatus
from app.db.models.scans import CorrespondenceProof, Scan

#: A minimal runtime bytecode blob: PUSH1 0x00, SSTORE, STOP.
SAMPLE_BYTECODE = bytes.fromhex("6000556000")


@pytest.fixture()
def captured_mythril(monkeypatch: pytest.MonkeyPatch) -> list[tuple[uuid.UUID, uuid.UUID]]:
    """Replace the Mythril enqueue call with a recording stub."""
    calls: list[tuple[uuid.UUID, uuid.UUID]] = []

    def fake_enqueue(scan_id: uuid.UUID, job_id: uuid.UUID | None = None) -> str:
        assert job_id is not None
        calls.append((scan_id, job_id))
        return "rq-mythril-job-id"

    monkeypatch.setattr(scans_api, "enqueue_mythril", fake_enqueue)
    return calls


@pytest.fixture()
def captured_scan(monkeypatch: pytest.MonkeyPatch) -> list[tuple[uuid.UUID, uuid.UUID]]:
    """Replace the scan enqueue call with a recording stub."""
    calls: list[tuple[uuid.UUID, uuid.UUID]] = []

    def fake_enqueue(scan_id: uuid.UUID, job_id: uuid.UUID | None = None) -> str:
        assert job_id is not None
        calls.append((scan_id, job_id))
        return "rq-job-id"

    monkeypatch.setattr(scans_api, "enqueue_scan", fake_enqueue)
    return calls


def _create_scan(client: TestClient, headers: dict[str, str], address: str) -> uuid.UUID:
    response = client.post(
        "/api/v1/scans",
        json={
            "contract_address": address,
            "chain_id": 1,
            "fork": "cancun",
            "bytecode_hex": SAMPLE_BYTECODE.hex(),
        },
        headers=headers,
    )
    assert response.status_code == 202, response.text
    return uuid.UUID(response.json()["id"])


# --------------------------------------------------------------------- Mythril


def test_mythril_requires_authentication(client: TestClient) -> None:
    """The manual Mythril action is behind the API key."""
    response = client.post(f"/api/v1/scans/{uuid.uuid4()}/mythril")
    assert response.status_code == 401


def test_mythril_trigger_returns_202_and_queues_the_work(
    client: TestClient,
    api_headers: dict[str, str],
    captured_scan: list[Any],
    captured_mythril: list[Any],
) -> None:
    """Triggering Mythril queues the work and says only that it was queued."""
    scan_id = _create_scan(client, api_headers, "0x" + "a1" * 20)

    response = client.post(f"/api/v1/scans/{scan_id}/mythril", headers=api_headers)

    assert response.status_code == 202, response.text
    body = response.json()
    assert body["status"] == "queued"
    assert body["scan_id"] == str(scan_id)
    assert body["queue_name"] == "cyberstratum:mythril"
    assert len(captured_mythril) == 1

    # The response must not imply that Mythril has already looked at the
    # contract. It says the work was queued, and nothing more.
    assert "clean" not in body["message"].lower()
    assert "verdict" not in body["message"].lower()


def test_mythril_trigger_records_a_job_row(
    client: TestClient,
    api_headers: dict[str, str],
    captured_scan: list[Any],
    captured_mythril: list[Any],
    db_session: Session,
) -> None:
    """The Mythril request is persisted as a job of its own type."""
    from app.db.enums import ScanJobType
    from app.db.models.scans import ScanJob

    scan_id = _create_scan(client, api_headers, "0x" + "a2" * 20)
    client.post(f"/api/v1/scans/{scan_id}/mythril", headers=api_headers)

    jobs = db_session.query(ScanJob).filter(ScanJob.scan_id == scan_id).all()
    mythril_jobs = [job for job in jobs if job.job_type is ScanJobType.MYTHRIL]
    assert len(mythril_jobs) == 1
    assert mythril_jobs[0].rq_job_id == "rq-mythril-job-id"
    assert mythril_jobs[0].queue_name == "cyberstratum:mythril"


def test_mythril_trigger_404s_for_an_unknown_scan(
    client: TestClient, api_headers: dict[str, str], captured_mythril: list[Any]
) -> None:
    """An unknown scan id returns 404 rather than queueing work."""
    response = client.post(f"/api/v1/scans/{uuid.uuid4()}/mythril", headers=api_headers)
    assert response.status_code == 404
    assert captured_mythril == []


def test_mythril_trigger_reports_an_unavailable_queue(
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
    api_headers: dict[str, str],
    captured_scan: list[Any],
) -> None:
    """A queue outage is reported as 503, not as a queued run."""

    def boom(scan_id: uuid.UUID, job_id: uuid.UUID | None = None) -> str:
        raise RuntimeError("redis is down")

    monkeypatch.setattr(scans_api, "enqueue_mythril", boom)
    scan_id = _create_scan(client, api_headers, "0x" + "a3" * 20)

    response = client.post(f"/api/v1/scans/{scan_id}/mythril", headers=api_headers)

    assert response.status_code == 503


# --------------------------------------------------------------- Correspondence


@pytest.fixture()
def captured_correspondence(monkeypatch: pytest.MonkeyPatch) -> list[tuple[uuid.UUID, uuid.UUID]]:
    """Replace the correspondence enqueue call with a recording stub."""
    calls: list[tuple[uuid.UUID, uuid.UUID]] = []

    def fake_enqueue(scan_id: uuid.UUID, job_id: uuid.UUID | None = None) -> str:
        assert job_id is not None
        calls.append((scan_id, job_id))
        return "rq-correspondence-job-id"

    monkeypatch.setattr(scans_api, "enqueue_correspondence", fake_enqueue)
    return calls


def test_correspondence_trigger_returns_202_and_queues_the_work(
    client: TestClient,
    api_headers: dict[str, str],
    captured_scan: list[Any],
    captured_correspondence: list[Any],
) -> None:
    """Triggering the proof queues the work and claims nothing."""
    scan_id = _create_scan(client, api_headers, "0x" + "b0" * 20)

    response = client.post(f"/api/v1/scans/{scan_id}/correspondence", headers=api_headers)

    assert response.status_code == 202, response.text
    body = response.json()
    assert body["status"] == "queued"
    assert body["scan_id"] == str(scan_id)
    assert body["queue_name"] == "cyberstratum:correspondence"
    assert len(captured_correspondence) == 1

    # The response must not imply a source line may already be claimed.
    assert body["status"] == "queued"
    assert "no source line may be claimed" in body["message"].lower()
    assert "proof established" not in body["message"].lower()


def test_correspondence_trigger_records_a_job_row(
    client: TestClient,
    api_headers: dict[str, str],
    captured_scan: list[Any],
    captured_correspondence: list[Any],
    db_session: Session,
) -> None:
    """The proof request is persisted as a job of its own type."""
    from app.db.enums import ScanJobType
    from app.db.models.scans import ScanJob

    scan_id = _create_scan(client, api_headers, "0x" + "b5" * 20)
    client.post(f"/api/v1/scans/{scan_id}/correspondence", headers=api_headers)

    jobs = db_session.query(ScanJob).filter(ScanJob.scan_id == scan_id).all()
    proof_jobs = [job for job in jobs if job.job_type is ScanJobType.CORRESPONDENCE]
    assert len(proof_jobs) == 1
    assert proof_jobs[0].rq_job_id == "rq-correspondence-job-id"
    assert proof_jobs[0].queue_name == "cyberstratum:correspondence"


def test_correspondence_trigger_requires_authentication(client: TestClient) -> None:
    """The manual proof action is behind the API key."""
    response = client.post(f"/api/v1/scans/{uuid.uuid4()}/correspondence")
    assert response.status_code == 401


def test_correspondence_trigger_404s_for_an_unknown_scan(
    client: TestClient, api_headers: dict[str, str], captured_correspondence: list[Any]
) -> None:
    """An unknown scan id returns 404 rather than queueing work."""
    response = client.post(f"/api/v1/scans/{uuid.uuid4()}/correspondence", headers=api_headers)
    assert response.status_code == 404
    assert captured_correspondence == []


def test_correspondence_trigger_reports_an_unavailable_queue(
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
    api_headers: dict[str, str],
    captured_scan: list[Any],
) -> None:
    """A queue outage is reported as 503, not as a queued proof."""

    def boom(scan_id: uuid.UUID, job_id: uuid.UUID | None = None) -> str:
        raise RuntimeError("redis is down")

    monkeypatch.setattr(scans_api, "enqueue_correspondence", boom)
    scan_id = _create_scan(client, api_headers, "0x" + "b6" * 20)

    response = client.post(f"/api/v1/scans/{scan_id}/correspondence", headers=api_headers)

    assert response.status_code == 503


def test_correspondence_404s_when_no_proof_exists(
    client: TestClient, api_headers: dict[str, str], captured_scan: list[Any]
) -> None:
    """No proof is a 404, and the message says it is not a mismatch."""
    scan_id = _create_scan(client, api_headers, "0x" + "b1" * 20)

    response = client.get(f"/api/v1/scans/{scan_id}/correspondence", headers=api_headers)

    assert response.status_code == 404
    detail = response.json()["error"]["message"].lower()
    assert "not evidence of a mismatch" in detail


def test_correspondence_returns_the_stored_proof(
    client: TestClient,
    api_headers: dict[str, str],
    captured_scan: list[Any],
    db_session: Session,
) -> None:
    """A stored proof is returned with its status and its compiler."""
    scan_id = _create_scan(client, api_headers, "0x" + "b2" * 20)
    scan = db_session.get(Scan, scan_id)
    assert scan is not None

    db_session.add(
        CorrespondenceProof(
            scan_id=scan.id,
            status=CorrespondenceStatus.ESTABLISHED,
            compiler_version="0.4.24+commit.e67f0147",
            source_path="FiatTokenProxy.sol",
            runtime_sha256="a" * 64,
            executable_sha256="b" * 64,
            executable_byte_size=2143,
            instruction_count=807,
            mapped_instruction_count=807,
        )
    )
    db_session.flush()

    response = client.get(f"/api/v1/scans/{scan_id}/correspondence", headers=api_headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "established"
    assert body["compiler_version"] == "0.4.24+commit.e67f0147"
    assert body["source_path"] == "FiatTokenProxy.sol"
    assert body["executable_byte_size"] == 2143


def test_scan_detail_exposes_the_correspondence_proof(
    client: TestClient,
    api_headers: dict[str, str],
    captured_scan: list[Any],
    db_session: Session,
) -> None:
    """The scan detail carries the proof, so the UI need not call twice."""
    scan_id = _create_scan(client, api_headers, "0x" + "b3" * 20)
    scan = db_session.get(Scan, scan_id)
    assert scan is not None
    db_session.add(
        CorrespondenceProof(
            scan_id=scan.id,
            status=CorrespondenceStatus.MISMATCH,
            skipped="",
        )
    )
    db_session.flush()

    response = client.get(f"/api/v1/scans/{scan_id}", headers=api_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["correspondence"] is not None
    assert body["correspondence"]["status"] == "mismatch"


def test_scan_detail_reports_no_proof_as_null(
    client: TestClient, api_headers: dict[str, str], captured_scan: list[Any]
) -> None:
    """A scan with no proof reports it as null, not as a mismatch."""
    scan_id = _create_scan(client, api_headers, "0x" + "b4" * 20)

    response = client.get(f"/api/v1/scans/{scan_id}", headers=api_headers)

    assert response.status_code == 200
    assert response.json()["correspondence"] is None


# ------------------------------------------------------------------ PDF report


def test_report_downloads_a_pdf(
    client: TestClient, api_headers: dict[str, str], captured_scan: list[Any]
) -> None:
    """The report endpoint returns a real PDF."""
    scan_id = _create_scan(client, api_headers, "0x" + "c1" * 20)

    response = client.get(f"/api/v1/scans/{scan_id}/report.pdf", headers=api_headers)

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/pdf")
    assert response.content.startswith(b"%PDF")
    assert len(response.headers["x-report-sha256"]) == 64


def test_report_is_byte_identical_across_requests(
    client: TestClient, api_headers: dict[str, str], captured_scan: list[Any]
) -> None:
    """The same evidence renders the same document, byte for byte."""
    scan_id = _create_scan(client, api_headers, "0x" + "c2" * 20)

    first = client.get(f"/api/v1/scans/{scan_id}/report.pdf", headers=api_headers)
    second = client.get(f"/api/v1/scans/{scan_id}/report.pdf", headers=api_headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.content == second.content
    assert first.headers["x-report-sha256"] == second.headers["x-report-sha256"]


def test_report_404s_for_an_unknown_scan(client: TestClient, api_headers: dict[str, str]) -> None:
    """An unknown scan id returns 404."""
    response = client.get(f"/api/v1/scans/{uuid.uuid4()}/report.pdf", headers=api_headers)
    assert response.status_code == 404


def test_report_requires_authentication(client: TestClient) -> None:
    """The report is behind the API key."""
    response = client.get(f"/api/v1/scans/{uuid.uuid4()}/report.pdf")
    assert response.status_code == 401


def test_scan_status_reaches_the_report(
    client: TestClient,
    api_headers: dict[str, str],
    captured_scan: list[Any],
    db_session: Session,
) -> None:
    """The report is rendered for a scan that has not finished, and says so."""
    scan_id = _create_scan(client, api_headers, "0x" + "c3" * 20)
    scan = db_session.get(Scan, scan_id)
    assert scan is not None
    assert scan.status is ScanStatus.QUEUED

    response = client.get(f"/api/v1/scans/{scan_id}/report.pdf", headers=api_headers)

    assert response.status_code == 200
    assert response.content.startswith(b"%PDF")
