"""Tests for reading back the source that was analysed.

The source of a scan is stored as an artifact, because the source is
evidence: it is what the bytes were made from, and it is what a finding
points at when it names a line. Reading it back is what lets the web
app put the line a finding names next to the code it names.

These tests care about three promises:

* a scan with a stored source returns that source, file by file,
* a scan without one says so in words, instead of returning an empty
  list that reads like "there was nothing there",
* a scan belonging to another tenant is a 404, like every other
  tenant-scoped read.
"""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import hash_api_key
from app.db.enums import ScanStatus
from app.db.models.identity import (
    ApiKey,
    ContractTarget,
    User,
    Workspace,
    WorkspaceMember,
)
from app.db.models.scans import Scan, ScanArtifact
from app.services import storage

SOURCE = "// SPDX-License-Identifier: MIT\ncontract Stored {\n    uint256 x;\n}\n"


def _scan(session: Session, workspace: Workspace, chain) -> Scan:
    """A completed scan in a workspace, with a contract target under it."""
    target = ContractTarget(
        workspace_id=workspace.id,
        chain_id=chain.id,
        address="0x" + "44" * 20,
        label="stored source target",
        bytecode_type="runtime",
        authorization_status="unknown",
    )
    session.add(target)
    session.flush()
    scan = Scan(
        workspace_id=workspace.id,
        target_id=target.id,
        status=ScanStatus.COMPLETED,
        fork="cancun",
        bytecode_source="test",
    )
    session.add(scan)
    session.flush()
    return scan


def _store_source(session: Session, scan: Scan) -> ScanArtifact:
    """Store a source artifact for the scan, the way the pipeline does."""
    object_key = storage.put_json(
        f"scans/{scan.id}/source.json",
        {
            "language": "solidity",
            "compilerVersion": "0.8.26",
            "verified": True,
            "sourceUri": "https://example.test/contract",
            "files": [{"path": "Stored.sol", "content": SOURCE}],
        },
    )
    artifact = ScanArtifact(
        scan_id=scan.id,
        kind="source",
        content_type="application/json",
        object_key=object_key,
    )
    session.add(artifact)
    session.flush()
    return artifact


def _tenant_key(session: Session, workspace: Workspace) -> str:
    """Mint a key that acts only inside one workspace."""
    raw = f"key-{uuid.uuid4().hex}"
    user = User(email=f"user-{uuid.uuid4().hex}@example.test", display_name="Tenant")
    session.add(user)
    session.flush()
    session.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="owner"))
    session.flush()
    session.add(
        ApiKey(
            user_id=user.id,
            workspace_id=workspace.id,
            name="tenant key",
            key_hash=hash_api_key(raw),
            key_prefix=raw[:12],
        )
    )
    session.flush()
    return raw


def test_the_source_comes_back_with_its_files(
    client: TestClient, api_headers: dict[str, str], db_session: Session, workspace, chain
) -> None:
    scan = _scan(db_session, workspace, chain)
    _store_source(db_session, scan)

    response = client.get(f"/api/v1/scans/{scan.id}/source", headers=api_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["available"] is True
    assert body["compiler_version"] == "0.8.26"
    assert body["language"] == "solidity"
    assert body["verified"] is True
    assert body["source_uri"] == "https://example.test/contract"
    assert len(body["files"]) == 1
    assert body["files"][0]["path"] == "Stored.sol"
    assert body["files"][0]["content"] == SOURCE


def test_a_scan_without_a_source_says_so(
    client: TestClient, api_headers: dict[str, str], db_session: Session, workspace, chain
) -> None:
    scan = _scan(db_session, workspace, chain)

    response = client.get(f"/api/v1/scans/{scan.id}/source", headers=api_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["available"] is False
    assert body["reason"], "a scan without source must say why it has none"
    assert body["files"] == []


def test_another_tenants_scan_is_not_found(
    client: TestClient, db_session: Session, workspace, chain
) -> None:
    other = Workspace(name="Other", slug=f"other-{uuid.uuid4().hex[:8]}", created_by=None)
    db_session.add(other)
    db_session.flush()
    scan = _scan(db_session, other, chain)
    raw = _tenant_key(db_session, workspace)

    response = client.get(f"/api/v1/scans/{scan.id}/source", headers={"X-API-Key": raw})

    assert response.status_code == 404


def test_an_unknown_scan_is_not_found(client: TestClient, api_headers: dict[str, str]) -> None:
    response = client.get(f"/api/v1/scans/{uuid.uuid4()}/source", headers=api_headers)

    assert response.status_code == 404
