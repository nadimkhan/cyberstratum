"""The report and the model manifest must be provable, retrievable objects.

Two properties are tested here:

1. **The rendered PDF is a first-class artefact of the scan.** It has a
   location, a size and a digest in the artefact registry, and the
   digest in the response header is the digest of the bytes that were
   stored. A report that cannot be pointed at is not evidence.

2. **The model manifest is retrievable, and its absence is stated
   honestly.** "No model is installed" (404) and "a model is installed
   but its manifest cannot be read" (503) are different facts and are
   never collapsed into one.

The report's provenance table deliberately excludes the report's own
artefact row: a document that contained its own digest could not render
twice to the same bytes, and reproducibility is the whole point.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api import scans as scans_api
from app.db.models.scans import ScanArtifact
from app.services.model_manifest import ModelManifestError, read_model_manifest

#: A minimal runtime bytecode blob: PUSH1 0x00, SSTORE, STOP.
SAMPLE_BYTECODE = bytes.fromhex("6000556000")


@pytest.fixture()
def captured_scan(monkeypatch: pytest.MonkeyPatch) -> list[uuid.UUID]:
    """Replace the scan enqueue call with a recording stub.

    The suite never depends on a running worker; the queue is not part of
    what these tests are about.
    """
    calls: list[uuid.UUID] = []

    def fake_enqueue(scan_id: uuid.UUID, job_id: uuid.UUID | None = None) -> str:
        calls.append(scan_id)
        return "rq:fake"

    monkeypatch.setattr(scans_api, "enqueue_scan", fake_enqueue)
    return calls


def _create_scan(client: TestClient, headers: dict[str, str], address: str) -> uuid.UUID:
    """Create a scan through the API and return its id."""
    response = client.post(
        "/api/v1/scans",
        json={
            "contract_address": address,
            "chain_id": 1,
            "fork": "prague",
            "bytecode_hex": SAMPLE_BYTECODE.hex(),
        },
        headers=headers,
    )
    assert response.status_code == 202, response.text
    return uuid.UUID(response.json()["id"])


def test_the_report_is_stored_as_an_artefact(
    captured_scan: list[uuid.UUID],
    client: TestClient,
    db_session: Session,
    api_headers: dict[str, str],
) -> None:
    """Downloading the report files it as an artefact of the scan."""
    scan_id = _create_scan(client, api_headers, "0x" + "d1" * 20)

    response = client.get(f"/api/v1/scans/{scan_id}/report.pdf", headers=api_headers)

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"

    digest = response.headers["X-Report-SHA256"]
    assert digest == hashlib.sha256(response.content).hexdigest()

    artifact = db_session.scalars(
        select(ScanArtifact).where(
            ScanArtifact.scan_id == scan_id,
            ScanArtifact.kind == "report",
        )
    ).first()
    assert artifact is not None, "the report was not filed as an artefact"
    assert artifact.content_type == "application/pdf"
    assert artifact.byte_size == len(response.content)
    assert artifact.sha256 == digest
    assert artifact.object_key == f"scans/{scan_id}/report.pdf"


def test_the_stored_report_is_the_bytes_that_were_served(
    captured_scan: list[uuid.UUID],
    client: TestClient,
    api_headers: dict[str, str],
) -> None:
    """The filed bytes are the served bytes, not a re-render."""
    scan_id = _create_scan(client, api_headers, "0x" + "d2" * 20)

    response = client.get(f"/api/v1/scans/{scan_id}/report.pdf", headers=api_headers)
    assert response.status_code == 200

    from app.services import storage

    assert storage.get_bytes(f"scans/{scan_id}/report.pdf") == response.content


def test_only_one_report_artefact_is_recorded(
    captured_scan: list[uuid.UUID],
    client: TestClient,
    db_session: Session,
    api_headers: dict[str, str],
) -> None:
    """Downloading twice does not accumulate duplicate rows."""
    scan_id = _create_scan(client, api_headers, "0x" + "d3" * 20)

    for _ in range(2):
        response = client.get(f"/api/v1/scans/{scan_id}/report.pdf", headers=api_headers)
        assert response.status_code == 200

    rows = db_session.scalars(
        select(ScanArtifact).where(
            ScanArtifact.scan_id == scan_id,
            ScanArtifact.kind == "report",
        )
    ).all()
    assert len(rows) == 1


def test_the_manifest_endpoint_says_no_model_when_none_is_installed(
    client: TestClient,
    api_headers: dict[str, str],
) -> None:
    """With no model installed, the endpoint answers 404."""
    response = client.get("/api/v1/models/manifest", headers=api_headers)

    assert response.status_code == 404
    assert "no model" in response.json()["error"]["message"].lower()


def test_the_manifest_endpoint_requires_authentication(client: TestClient) -> None:
    """The manifest is not public."""
    response = client.get("/api/v1/models/manifest")

    assert response.status_code == 401


def test_the_manifest_endpoint_returns_the_manifest_and_its_digest(
    client: TestClient,
    api_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An installed model is served with the digest of the file."""
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    payload = {"version": "1.2.3", "training": {"samples": 10}}
    raw = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
    (model_dir / "manifest.json").write_bytes(raw)

    monkeypatch.setenv("ML_MODEL_DIR", str(model_dir))
    from app.core.config import get_settings

    get_settings.cache_clear()
    try:
        response = client.get("/api/v1/models/manifest", headers=api_headers)
    finally:
        monkeypatch.delenv("ML_MODEL_DIR", raising=False)
        get_settings.cache_clear()

    assert response.status_code == 200
    body = response.json()
    assert body["manifest_id"] == "1.2.3"
    assert body["sha256"] == hashlib.sha256(raw).hexdigest()
    assert body["manifest"] == payload


def test_a_broken_model_installation_is_not_reported_as_no_model(
    client: TestClient,
    api_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A configured model with an unreadable manifest is a failure."""
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    (model_dir / "manifest.json").write_text("{not json", encoding="utf-8")

    monkeypatch.setenv("ML_MODEL_DIR", str(model_dir))
    from app.core.config import get_settings

    get_settings.cache_clear()
    try:
        response = client.get("/api/v1/models/manifest", headers=api_headers)
    finally:
        monkeypatch.delenv("ML_MODEL_DIR", raising=False)
        get_settings.cache_clear()

    assert response.status_code == 503
    assert "cannot be read" in response.json()["error"]["message"].lower()


def test_a_missing_manifest_in_a_configured_directory_is_a_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The service refuses to pretend an empty model directory is empty."""
    model_dir = tmp_path / "model"
    model_dir.mkdir()

    monkeypatch.setenv("ML_MODEL_DIR", str(model_dir))
    from app.core.config import get_settings

    get_settings.cache_clear()
    try:
        with pytest.raises(ModelManifestError):
            read_model_manifest()
    finally:
        monkeypatch.delenv("ML_MODEL_DIR", raising=False)
        get_settings.cache_clear()
