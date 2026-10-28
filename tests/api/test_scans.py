"""Tests for the scan endpoints."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api import scans as scans_api
from app.db.enums import ScanJobStatus, ScanStatus
from app.db.models.scans import Scan

#: A minimal runtime bytecode blob: PUSH1 0x00, SSTORE, STOP.
SAMPLE_BYTECODE = bytes.fromhex("6000556000")


@pytest.fixture()
def captured_enqueue(monkeypatch: pytest.MonkeyPatch) -> list[tuple[uuid.UUID, uuid.UUID]]:
    """Replace the RQ enqueue call with a recording stub."""
    calls: list[tuple[uuid.UUID, uuid.UUID]] = []

    def fake_enqueue(scan_id: uuid.UUID, job_id: uuid.UUID | None = None) -> str:
        assert job_id is not None
        calls.append((scan_id, job_id))
        return "rq-job-id"

    monkeypatch.setattr(scans_api, "enqueue_scan", fake_enqueue)
    return calls


def test_submit_scan_requires_authentication(client: TestClient) -> None:
    """Scan submission is rejected without an API key."""
    response = client.post("/api/v1/scans", json={"contract_address": "0x" + "22" * 20})
    assert response.status_code == 401


def test_submit_scan_rejects_invalid_address(
    client: TestClient, api_headers: dict[str, str]
) -> None:
    """An invalid contract address fails validation."""
    response = client.post(
        "/api/v1/scans", json={"contract_address": "not-an-address"}, headers=api_headers
    )
    assert response.status_code == 422


def test_submit_scan_enqueues_job(
    client: TestClient, api_headers: dict[str, str], captured_enqueue: list[Any]
) -> None:
    """Submitting a scan creates the scan row and enqueues an RQ job."""
    response = client.post(
        "/api/v1/scans",
        json={"contract_address": "0x" + "33" * 20, "chain_id": 1, "fork": "cancun"},
        headers=api_headers,
    )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["status"] == ScanStatus.QUEUED.value
    assert body["status_url"] == f"/api/v1/scans/{body['id']}"
    assert len(captured_enqueue) == 1

    scan_id = uuid.UUID(body["id"])
    detail = client.get(f"/api/v1/scans/{scan_id}", headers=api_headers)
    assert detail.status_code == 200
    detail_body = detail.json()
    assert detail_body["status"] == ScanStatus.QUEUED.value
    assert detail_body["fork"] == "cancun"
    assert len(detail_body["jobs"]) == 1
    assert detail_body["jobs"][0]["status"] == ScanJobStatus.QUEUED.value
    assert detail_body["jobs"][0]["rq_job_id"] == "rq-job-id"


def test_submit_scan_persists_rows(
    client: TestClient,
    api_headers: dict[str, str],
    captured_enqueue: list[Any],
    db_session: Session,
) -> None:
    """The scan and its job are persisted in the database."""
    response = client.post(
        "/api/v1/scans",
        json={"contract_address": "0x" + "44" * 20, "chain_id": 1},
        headers=api_headers,
    )
    assert response.status_code == 202
    scan_id = uuid.UUID(response.json()["id"])

    scan = db_session.get(Scan, scan_id)
    assert scan is not None
    assert scan.status is ScanStatus.QUEUED
    assert scan.target.address == "0x" + "44" * 20
    assert scan.target.chain.chain_id == 1
    assert len(scan.jobs) == 1


def test_list_scans(
    client: TestClient, api_headers: dict[str, str], captured_enqueue: list[Any]
) -> None:
    """Submitted scans appear in the scan list."""
    client.post(
        "/api/v1/scans",
        json={"contract_address": "0x" + "55" * 20, "chain_id": 1},
        headers=api_headers,
    )
    response = client.get("/api/v1/scans", headers=api_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["total"] >= 1
    assert body["items"][0]["status"] in {status.value for status in ScanStatus}


def test_list_scans_filters_by_status(
    client: TestClient, api_headers: dict[str, str], captured_enqueue: list[Any]
) -> None:
    """The scan list can be filtered by status."""
    client.post(
        "/api/v1/scans",
        json={"contract_address": "0x" + "66" * 20, "chain_id": 1},
        headers=api_headers,
    )
    response = client.get("/api/v1/scans?status=queued", headers=api_headers)
    assert response.status_code == 200
    assert all(item["status"] == "queued" for item in response.json()["items"])


def test_submit_scan_accepts_inline_bytecode(
    client: TestClient, api_headers: dict[str, str], captured_enqueue: list[Any]
) -> None:
    """User-supplied bytecode is stored on the target and marks the source as upload."""
    response = client.post(
        "/api/v1/scans",
        json={
            "contract_address": "0x" + "77" * 20,
            "chain_id": 1,
            "bytecode_hex": SAMPLE_BYTECODE.hex(),
        },
        headers=api_headers,
    )
    assert response.status_code == 202, response.text
    scan_id = uuid.UUID(response.json()["id"])

    detail = client.get(f"/api/v1/scans/{scan_id}", headers=api_headers).json()
    assert detail["bytecode_source"] == "upload"


def test_submit_scan_stores_inline_bytecode_on_target(
    client: TestClient,
    api_headers: dict[str, str],
    captured_enqueue: list[Any],
    db_session: Session,
) -> None:
    """The uploaded bytes are persisted on the contract target."""
    response = client.post(
        "/api/v1/scans",
        json={
            "contract_address": "0x" + "88" * 20,
            "chain_id": 1,
            "bytecode_hex": "0x" + SAMPLE_BYTECODE.hex(),
        },
        headers=api_headers,
    )
    assert response.status_code == 202, response.text
    scan = db_session.get(Scan, uuid.UUID(response.json()["id"]))
    assert scan is not None
    assert scan.target.inline_bytecode == SAMPLE_BYTECODE


def test_submit_scan_rejects_invalid_bytecode(
    client: TestClient, api_headers: dict[str, str]
) -> None:
    """Non-hex bytecode is rejected by validation."""
    response = client.post(
        "/api/v1/scans",
        json={"contract_address": "0x" + "99" * 20, "bytecode_hex": "nothex"},
        headers=api_headers,
    )
    assert response.status_code == 422


def test_submit_scan_rejects_odd_length_bytecode(
    client: TestClient, api_headers: dict[str, str]
) -> None:
    """Bytecode with an odd number of hex characters is rejected."""
    response = client.post(
        "/api/v1/scans",
        json={"contract_address": "0x" + "aa" * 20, "bytecode_hex": "600055600"},
        headers=api_headers,
    )
    assert response.status_code == 422


def test_get_unknown_scan_returns_404(client: TestClient, api_headers: dict[str, str]) -> None:
    """An unknown scan id returns 404."""
    response = client.get(f"/api/v1/scans/{uuid.uuid4()}", headers=api_headers)
    assert response.status_code == 404
    assert "error" in response.json()
