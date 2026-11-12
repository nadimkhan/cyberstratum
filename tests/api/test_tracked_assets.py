"""Tests for the tracked-asset registry.

The asset registry is the memory the product keeps between scans. These
tests care about four things:

* registering the same address twice does not create two assets, because
  two assets would split the contract's history in half,
* a scan attaches itself to the asset, so the history actually grows,
* the progress numbers count what exists -- a dismissed finding is
  closed, and the open count is the number that moves when a fix ships,
* another tenant's asset is indistinguishable from one that does not
  exist.
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
from app.db.enums import AssetKind, FindingStatus, ScanStatus, Severity, WorkspaceRole
from app.db.models.assets import TrackedAsset
from app.db.models.identity import (
    ApiKey,
    Chain,
    ContractTarget,
    User,
    Workspace,
    WorkspaceMember,
)
from app.db.models.scans import Finding, Scan
from app.services.promotion import promote_contracts

ADDRESS = "0x" + "ab" * 20
OTHER_ADDRESS = "0x" + "cd" * 20


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


def _make_tenant(db_session: Session, label: str) -> Tenant:
    """Create a workspace, a member user and a stored API key for one tenant."""
    user = User(email=f"{label}-{uuid.uuid4().hex}@example.test", display_name=f"{label} user")
    db_session.add(user)
    db_session.flush()

    space = Workspace(
        name=f"{label} workspace",
        slug=f"{label}-{uuid.uuid4().hex}",
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

    raw_key = f"{label}-key-{uuid.uuid4().hex}"
    db_session.add(
        ApiKey(
            user_id=user.id,
            name=f"{label} key",
            key_hash=hash_api_key(raw_key),
            key_prefix=raw_key[:12],
        )
    )
    db_session.flush()
    return Tenant(workspace=space, user=user, raw_key=raw_key)


@pytest.fixture()
def tenant(db_session: Session) -> Tenant:
    """A tenant whose key is scoped to its own workspace."""
    return _make_tenant(db_session, "alpha")


@pytest.fixture()
def other_tenant(db_session: Session) -> Tenant:
    """A second tenant, so isolation can be tested against a real id."""
    return _make_tenant(db_session, "beta")


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


def _register(client: TestClient, tenant: Tenant, address: str = ADDRESS, **extra: object):
    """Register an address and return the response."""
    payload: dict[str, object] = {"address": address, "chain_id": 1, "label": "my token"}
    payload.update(extra)
    return client.post("/api/v1/assets", json=payload, headers=tenant.headers)


def test_registering_an_address_returns_an_asset(
    client: TestClient, tenant: Tenant, db_session: Session
) -> None:
    """The address comes back with its kind and the moment it was first seen."""
    response = _register(client, tenant)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["asset"]["address"] == ADDRESS
    assert body["asset"]["kind"] == AssetKind.OWNED.value
    assert body["asset"]["label"] == "my token"
    assert body["asset"]["first_seen_at"] is not None
    assert body["evm_chain_id"] == 1
    assert body["progress"]["scan_count"] == 0


def test_registering_the_same_address_twice_is_idempotent(
    client: TestClient, tenant: Tenant, db_session: Session
) -> None:
    """Two assets for one address would split the history in half."""
    first = _register(client, tenant)
    second = _register(client, tenant)

    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert first.json()["asset"]["id"] == second.json()["asset"]["id"]

    rows = db_session.scalars(
        select(TrackedAsset).where(TrackedAsset.workspace_id == tenant.workspace.id)
    ).all()
    assert len(rows) == 1


def test_an_address_that_is_not_an_address_is_refused(client: TestClient, tenant: Tenant) -> None:
    """A malformed address is a client error, not a stored asset."""
    response = _register(client, tenant, address="not-an-address")
    assert response.status_code == 422


def test_a_scan_starts_the_history_of_an_address(
    client: TestClient, tenant: Tenant, captured_enqueue: list[tuple[uuid.UUID, uuid.UUID]]
) -> None:
    """Scanning an address attaches the scan to the address."""
    response = client.post(
        "/api/v1/scans",
        json={"contract_address": ADDRESS, "chain_id": 1},
        headers=tenant.headers,
    )
    assert response.status_code == 202, response.text
    scan_id = response.json()["id"]

    assets = client.get("/api/v1/assets", headers=tenant.headers)
    assert assets.status_code == 200, assets.text
    body = assets.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["asset"]["address"] == ADDRESS
    assert item["asset"]["kind"] == AssetKind.OWNED.value
    assert item["progress"]["scan_count"] == 1

    history = client.get(f"/api/v1/assets/{item['asset']['id']}/history", headers=tenant.headers)
    assert history.status_code == 200, history.text
    timeline = history.json()["timeline"]
    assert len(timeline) == 1
    assert timeline[0]["scan_id"] == scan_id


def test_the_progress_counts_findings_and_dismisses_false_positives(
    client: TestClient, tenant: Tenant, db_session: Session, chain: Chain
) -> None:
    """A dismissed finding is closed; the open count is what a fix moves."""
    response = _register(client, tenant)
    asset_id = response.json()["asset"]["id"]
    asset = db_session.get(TrackedAsset, uuid.UUID(asset_id))

    target = ContractTarget(
        workspace_id=tenant.workspace.id,
        chain_id=chain.id,
        address=ADDRESS,
        label="my token",
        bytecode_type="runtime",
        authorization_status="unknown",
    )
    db_session.add(target)
    db_session.flush()

    scan = Scan(
        workspace_id=tenant.workspace.id,
        target_id=target.id,
        asset_id=asset.id,
        status=ScanStatus.COMPLETED,
        fork="cancun",
        bytecode_source="test",
    )
    db_session.add(scan)
    db_session.flush()

    for status in (FindingStatus.NEW, FindingStatus.CONFIRMED, FindingStatus.FALSE_POSITIVE):
        db_session.add(
            Finding(
                workspace_id=tenant.workspace.id,
                scan_id=scan.id,
                detector_id="baseline.test",
                detector_version="0.1.0",
                category="reentrancy_candidate",
                title="a deterministic test finding",
                description="A deterministic test finding.",
                severity=Severity.HIGH,
                confidence=0.5,
                status=status,
                evidence_json={"offsets": [1]},
            )
        )
    db_session.flush()

    detail = client.get(f"/api/v1/assets/{asset_id}", headers=tenant.headers)
    assert detail.status_code == 200, detail.text
    progress = detail.json()["progress"]
    assert progress["finding_count"] == 3
    assert progress["open_finding_count"] == 2
    assert progress["by_status"]["false_positive"] == 1
    assert progress["by_severity"]["high"] == 3


def test_another_tenants_asset_is_indistinguishable_from_a_missing_one(
    client: TestClient, tenant: Tenant, other_tenant: Tenant
) -> None:
    """Cross-tenant reads answer 404, never 403."""
    created = _register(client, tenant)
    asset_id = created.json()["asset"]["id"]

    response = client.get(f"/api/v1/assets/{asset_id}", headers=other_tenant.headers)
    assert response.status_code == 404

    history = client.get(f"/api/v1/assets/{asset_id}/history", headers=other_tenant.headers)
    assert history.status_code == 404

    rescan = client.post(f"/api/v1/assets/{asset_id}/scan", headers=other_tenant.headers)
    assert rescan.status_code == 404

    missing = client.get(f"/api/v1/assets/{uuid.uuid4()}", headers=other_tenant.headers)
    assert missing.status_code == 404


def test_a_list_only_contains_the_callers_own_assets(
    client: TestClient, tenant: Tenant, other_tenant: Tenant
) -> None:
    """One tenant's assets never appear in another tenant's list."""
    _register(client, tenant)
    _register(client, other_tenant, address=OTHER_ADDRESS)

    mine = client.get("/api/v1/assets", headers=tenant.headers)
    assert mine.status_code == 200
    assert mine.json()["total"] == 1
    assert mine.json()["items"][0]["asset"]["address"] == ADDRESS

    theirs = client.get("/api/v1/assets", headers=other_tenant.headers)
    assert theirs.json()["total"] == 1
    assert theirs.json()["items"][0]["asset"]["address"] == OTHER_ADDRESS


def test_a_discovered_contract_is_tracked_as_discovered(
    db_session: Session, tenant: Tenant, chain: Chain
) -> None:
    """The autonomous path gives its contracts a memory too."""
    target = ContractTarget(
        workspace_id=tenant.workspace.id,
        chain_id=chain.id,
        address=OTHER_ADDRESS,
        label="discovered",
        bytecode_type="runtime",
        authorization_status="unknown",
    )
    db_session.add(target)
    db_session.flush()

    outcome = promote_contracts(
        db_session,
        tenant.workspace,
        chain,
        [target],
        enqueue=False,
    )
    assert outcome.queued == 1

    asset = db_session.scalars(
        select(TrackedAsset).where(TrackedAsset.workspace_id == tenant.workspace.id)
    ).one()
    assert asset.kind == AssetKind.DISCOVERED.value
    assert asset.address == OTHER_ADDRESS

    scan = db_session.scalars(select(Scan).where(Scan.asset_id == asset.id)).one()
    assert scan.target_id == target.id


def test_stopping_the_tracking_keeps_the_history(
    client: TestClient, tenant: Tenant, captured_enqueue: list[tuple[uuid.UUID, uuid.UUID]]
) -> None:
    """The history of a contract outlives the decision to keep watching it."""
    client.post(
        "/api/v1/scans",
        json={"contract_address": ADDRESS, "chain_id": 1},
        headers=tenant.headers,
    )
    created = _register(client, tenant)
    asset_id = created.json()["asset"]["id"]

    deleted = client.delete(f"/api/v1/assets/{asset_id}", headers=tenant.headers)
    assert deleted.status_code == 204

    detail = client.get(f"/api/v1/assets/{asset_id}", headers=tenant.headers)
    assert detail.status_code == 200
    assert detail.json()["asset"]["active"] is False
    assert detail.json()["progress"]["scan_count"] == 1


def test_rescanning_an_asset_grows_the_history(
    client: TestClient, tenant: Tenant, captured_enqueue: list[tuple[uuid.UUID, uuid.UUID]]
) -> None:
    """A re-scan is what makes progress visible."""
    created = _register(client, tenant)
    asset_id = created.json()["asset"]["id"]

    response = client.post(f"/api/v1/assets/{asset_id}/scan", headers=tenant.headers)
    assert response.status_code == 202, response.text

    history = client.get(f"/api/v1/assets/{asset_id}/history", headers=tenant.headers)
    assert history.status_code == 200, history.text
    assert history.json()["progress"]["scan_count"] == 1
    assert len(history.json()["timeline"]) == 1
    assert history.json()["timeline"][0]["scan_id"] == response.json()["id"]


def test_the_history_reads_as_a_progress_log(
    client: TestClient, tenant: Tenant, captured_enqueue: list[tuple[uuid.UUID, uuid.UUID]]
) -> None:
    """The timeline is chronological: oldest scan first.

    A progress log that reads newest-first is a list, not a log. The
    reader wants to see the order the work happened in.
    """
    created = _register(client, tenant)
    asset_id = created.json()["asset"]["id"]

    first = client.post(f"/api/v1/assets/{asset_id}/scan", headers=tenant.headers)
    assert first.status_code == 202, first.text
    second = client.post(f"/api/v1/assets/{asset_id}/scan", headers=tenant.headers)
    assert second.status_code == 202, second.text

    history = client.get(f"/api/v1/assets/{asset_id}/history", headers=tenant.headers)
    assert history.status_code == 200, history.text

    timeline = history.json()["timeline"]
    assert len(timeline) == 2
    assert [row["scan_id"] for row in timeline] == [first.json()["id"], second.json()["id"]]
    assert timeline[0]["created_at"] <= timeline[1]["created_at"]
