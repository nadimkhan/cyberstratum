"""Tests for submitting a scan of raw runtime bytecode.

Bytecode is the third way into the product: a developer has the bytes
but not the source, and not always a node that will serve them. The
bytes are analysed by the same pipeline everything else goes through.

These tests care about the promises made about pasted bytes:

* the bytes that were pasted are the bytes that are analysed,
* the same bytes are the same contract, so a developer's history
  accumulates instead of splitting in two,
* the identity given to pasted bytes is honest about being a filing
  identity rather than a deployed address.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api import assets as assets_api
from app.api import scans as scans_api
from app.core.security import hash_api_key
from app.db.enums import WorkspaceRole
from app.db.models.assets import TrackedAsset
from app.db.models.identity import (
    ApiKey,
    ContractTarget,
    User,
    Workspace,
    WorkspaceMember,
)
from app.db.models.scans import Scan
from app.services.source_compile import bytecode_address

BYTECODE = "6080604052348015600e57600080fd5b50600436106024576003560006020fd5b3"
OTHER_BYTECODE = "6080604052600436106100225760003560e01c"


@dataclass(frozen=True)
class Tenant:
    """One tenant: its workspace, its member user and its API key."""

    workspace: Workspace
    user: User
    raw_key: str

    @property
    def headers(self) -> dict[str, str]:
        """The request headers that authenticate as this tenant."""
        return {"X-API-Key": self.raw_key}


@pytest.fixture()
def tenant(db_session: Session) -> Tenant:
    """A tenant whose key is scoped to its own workspace."""
    user = User(email=f"bytes-{uuid.uuid4().hex}@example.test", display_name="bytes")
    db_session.add(user)
    db_session.flush()

    space = Workspace(
        name="bytes workspace",
        slug=f"bytes-{uuid.uuid4().hex}",
        created_by=user.id,
    )
    db_session.add(space)
    db_session.flush()

    db_session.add(
        WorkspaceMember(
            workspace_id=space.id,
            user_id=user.id,
            role=WorkspaceRole.OWNER,
        )
    )

    raw_key = f"bytes-key-{uuid.uuid4().hex}"
    db_session.add(
        ApiKey(
            user_id=user.id,
            name="bytes key",
            key_hash=hash_api_key(raw_key),
            key_prefix=raw_key[:12],
        )
    )
    db_session.flush()
    return Tenant(workspace=space, user=user, raw_key=raw_key)


@pytest.fixture(autouse=True)
def _no_network_source_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the suite off the network."""
    from app.services import pipeline as pipeline_service

    monkeypatch.setattr(
        pipeline_service, "fetch_verified_source", lambda *a, **k: None
    )


@pytest.fixture()
def captured_enqueue(monkeypatch: pytest.MonkeyPatch) -> list[tuple[uuid.UUID, uuid.UUID]]:
    """Replace the RQ enqueue calls with a recording stub."""
    calls: list[tuple[uuid.UUID, uuid.UUID]] = []

    def fake_enqueue(scan_id: uuid.UUID, job_id: uuid.UUID | None = None) -> str:
        assert job_id is not None
        calls.append((scan_id, job_id))
        return "rq-job-id"

    monkeypatch.setattr(scans_api, "enqueue_scan", fake_enqueue)
    monkeypatch.setattr(assets_api, "enqueue_scan", fake_enqueue)
    return calls


def _submit(client: TestClient, tenant: Tenant, **payload: object):
    """Submit a scan with the given payload."""
    return client.post("/api/v1/scans", json=payload, headers=tenant.headers)


def test_pasted_bytecode_is_stored_and_queued(
    client: TestClient, tenant: Tenant, db_session: Session, captured_enqueue
) -> None:
    """The bytes that were pasted are the bytes that will be analysed."""
    response = _submit(client, tenant, bytecode_hex=BYTECODE)

    assert response.status_code == 202, response.text
    scan_id = uuid.UUID(response.json()["id"])

    scan = db_session.get(Scan, scan_id)
    assert scan is not None
    assert scan.bytecode_source == "upload"

    target = scan.target
    assert target.inline_bytecode_source == "upload"
    assert target.inline_bytecode
    assert target.inline_bytecode.hex() == BYTECODE
    assert target.address == bytecode_address(bytes.fromhex(BYTECODE))


def test_pasted_bytecode_is_tracked_so_its_history_accumulates(
    client: TestClient, tenant: Tenant, db_session: Session, captured_enqueue
) -> None:
    """The same bytes are the same contract, not two."""
    first = _submit(client, tenant, bytecode_hex=BYTECODE)
    second = _submit(client, tenant, bytecode_hex=BYTECODE)

    assert first.status_code == 202, first.text
    assert second.status_code == 202, second.text

    expected = bytecode_address(bytes.fromhex(BYTECODE))
    assets = db_session.scalars(select(TrackedAsset)).all()
    assert [asset.address for asset in assets] == [expected]

    targets = db_session.scalars(select(ContractTarget)).all()
    assert len(targets) == 1
    assert targets[0].address == expected


def test_different_bytecode_is_a_different_contract(
    client: TestClient, tenant: Tenant, db_session: Session, captured_enqueue
) -> None:
    """Two blobs are two contracts, each with its own history."""
    first = _submit(client, tenant, bytecode_hex=BYTECODE)
    second = _submit(client, tenant, bytecode_hex=OTHER_BYTECODE)

    assert first.status_code == 202, first.text
    assert second.status_code == 202, second.text

    targets = db_session.scalars(select(ContractTarget)).all()
    assert len(targets) == 2
    addresses = {target.address for target in targets}
    assert addresses == {
        bytecode_address(bytes.fromhex(BYTECODE)),
        bytecode_address(bytes.fromhex(OTHER_BYTECODE)),
    }


def test_bytecode_address_is_a_stable_filing_identity() -> None:
    """The identity is derived from the bytes, so it never drifts."""
    code = bytes.fromhex(BYTECODE)
    assert bytecode_address(code) == bytecode_address(code)
    assert bytecode_address(code) != bytecode_address(bytes.fromhex(OTHER_BYTECODE))
    assert bytecode_address(code).startswith("0x")
    assert len(bytecode_address(code)) == 42
