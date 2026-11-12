"""Tests for the discovery endpoints.

The routes are exercised against the test database with the RQ enqueue
replaced by a recording stub, so the suite never needs a live worker or a
live Blockscout route.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models.discovery import DiscoveryRun, FeedCursor
from app.db.models.identity import Chain, ContractTarget, Workspace


@pytest.fixture()
def enqueued(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Replace the discovery enqueue with a recording stub."""
    calls: list[dict[str, Any]] = []

    def fake_enqueue(batch_size: int = 10, chain_ids: list[int] | None = None) -> str:
        calls.append({"batch_size": batch_size, "chain_ids": chain_ids})
        return f"rq-{uuid.uuid4().hex}"

    monkeypatch.setattr("app.api.discovery.enqueue_discovery", fake_enqueue)
    return calls


def test_queueing_a_cycle_returns_202(
    client: TestClient, api_headers: dict[str, str], enqueued: list[dict[str, Any]]
) -> None:
    """A discovery cycle is queued, not run inline."""
    response = client.post(
        "/api/v1/discovery/runs",
        json={"batch_size": 5, "chain_ids": [1, 10]},
        headers=api_headers,
    )

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    assert body["queue_name"].endswith(":discovery")
    assert enqueued == [{"batch_size": 5, "chain_ids": [1, 10]}]


def test_queueing_requires_authentication(client: TestClient) -> None:
    """The route is behind the API key."""
    response = client.post("/api/v1/discovery/runs", json={})
    assert response.status_code in (401, 403)


def test_listing_runs_is_empty_at_first(client: TestClient, api_headers: dict[str, str]) -> None:
    """A fresh installation has no discovery cycles."""
    response = client.get("/api/v1/discovery/runs", headers=api_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["items"] == []
    assert body["total"] == 0


def test_listing_runs_returns_the_recorded_cycles(
    client: TestClient,
    api_headers: dict[str, str],
    db_session: Session,
) -> None:
    """Recorded cycles are listed, newest first."""
    workspace = Workspace(name="Discovery", slug="discovery", kind="discovery")
    db_session.add(workspace)
    db_session.flush()
    db_session.add(
        DiscoveryRun(
            workspace_id=workspace.id,
            status="completed",
            started_at=datetime.now(UTC),
            chains_covered=3,
            contracts_found=10,
            contracts_new=8,
            contracts_updated=2,
        )
    )
    db_session.flush()

    response = client.get("/api/v1/discovery/runs", headers=api_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["status"] == "completed"
    assert body["items"][0]["contracts_found"] == 10


def test_listing_discovered_contracts(
    client: TestClient,
    api_headers: dict[str, str],
    db_session: Session,
) -> None:
    """Discovered contracts are listed with their chain."""
    workspace = Workspace(name="Discovery", slug="discovery", kind="discovery")
    db_session.add(workspace)
    chain_row = Chain(name="Ethereum", chain_id=1, environment="mainnet")
    db_session.add(chain_row)
    db_session.flush()
    db_session.add(
        ContractTarget(
            workspace_id=workspace.id,
            chain_id=chain_row.id,
            address="0x" + "ab" * 20,
            label="Found token",
            bytecode_type="runtime",
            authorization_status="unknown",
            verification_state="verified",
            discovery_route="instance",
            source_uri="https://example.test/address/0xab",
        )
    )
    db_session.flush()

    response = client.get("/api/v1/discovery/contracts", headers=api_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["label"] == "Found token"
    assert item["chain_id"] == 1
    assert item["verification_state"] == "verified"


def test_listing_cursors(
    client: TestClient,
    api_headers: dict[str, str],
    db_session: Session,
) -> None:
    """The per-chain cursors are reported."""
    workspace = Workspace(name="Discovery", slug="discovery", kind="discovery")
    db_session.add(workspace)
    chain_row = Chain(name="Ethereum", chain_id=1, environment="mainnet")
    db_session.add(chain_row)
    db_session.flush()
    db_session.add(
        FeedCursor(
            workspace_id=workspace.id,
            chain_id=chain_row.id,
            last_address="0x" + "cd" * 20,
            contracts_seen=12,
        )
    )
    db_session.flush()

    response = client.get("/api/v1/discovery/cursors", headers=api_headers)

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["chain_id"] == 1
    assert body[0]["contracts_seen"] == 12
