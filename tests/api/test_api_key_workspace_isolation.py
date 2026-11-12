"""Tests that an API key acts in exactly one tenant.

A key issued for a workspace is the key's only boundary. The owner of
the key may well be a member of another workspace as well -- often of
several -- and the key must still act in the workspace it was issued
for, or a machine client can read another tenant's data by accident.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import hash_api_key
from app.db.enums import AssetKind, WorkspaceRole
from app.db.models.assets import TrackedAsset
from app.db.models.identity import ApiKey, Chain, User, Workspace, WorkspaceMember

ADDRESS_A = "0x" + "aa" * 20
ADDRESS_B = "0x" + "bb" * 20


def _user(session: Session, label: str) -> User:
    user = User(email=f"{label}-{uuid.uuid4().hex}@example.test", display_name=label)
    session.add(user)
    session.flush()
    return user


def _workspace(session: Session, label: str, owner: User) -> Workspace:
    space = Workspace(name=f"{label} space", slug=f"{label}-{uuid.uuid4().hex}")
    session.add(space)
    session.flush()
    session.add(
        WorkspaceMember(
            workspace_id=space.id,
            user_id=owner.id,
            role=WorkspaceRole.OWNER,
        )
    )
    session.flush()
    return space


def _key(session: Session, user: User, workspace: Workspace) -> str:
    raw = f"key-{uuid.uuid4().hex}"
    session.add(
        ApiKey(
            user_id=user.id,
            workspace_id=workspace.id,
            name="key",
            key_hash=hash_api_key(raw),
            key_prefix=raw[:12],
        )
    )
    session.flush()
    return raw


def _asset(session: Session, workspace: Workspace, chain: Chain, address: str) -> None:
    session.add(
        TrackedAsset(
            workspace_id=workspace.id,
            chain_id=chain.id,
            address=address,
            label="asset",
            kind=AssetKind.OWNED,
            first_seen_at=datetime.now(UTC),
        )
    )
    session.flush()


@pytest.fixture()
def two_tenants(db_session: Session, chain: Chain) -> dict[str, str]:
    """Two workspaces, and a key for the second whose owner is in both."""
    owner_a = _user(db_session, "owner-a")
    owner_b = _user(db_session, "owner-b")

    space_a = _workspace(db_session, "space-a", owner_a)
    space_b = _workspace(db_session, "space-b", owner_b)

    # The owner of the second key is also a member of the first
    # workspace, and was there first. A key that followed the owner's
    # earliest membership would act in the first workspace.
    db_session.add(
        WorkspaceMember(
            workspace_id=space_a.id,
            user_id=owner_b.id,
            role=WorkspaceRole.RESEARCHER,
        )
    )
    db_session.flush()
    early = (
        db_session.query(WorkspaceMember)
        .filter_by(user_id=owner_b.id, workspace_id=space_a.id)
        .one()
    )
    early.created_at = datetime.now(UTC) - timedelta(days=1)
    db_session.flush()

    _asset(db_session, space_a, chain, ADDRESS_A)
    _asset(db_session, space_b, chain, ADDRESS_B)

    return {
        "a": _key(db_session, owner_a, space_a),
        "b": _key(db_session, owner_b, space_b),
    }


def test_a_key_only_sees_the_workspace_it_was_issued_for(
    client: TestClient, two_tenants: dict[str, str]
):
    """The second key sees the second workspace and not the first."""
    response = client.get("/api/v1/assets", headers={"X-API-Key": two_tenants["b"]})

    assert response.status_code == 200
    payload = response.json()
    addresses = {item["asset"]["address"] for item in payload["items"]}
    assert ADDRESS_B in addresses
    assert ADDRESS_A not in addresses


def test_the_first_key_still_sees_the_first_workspace(
    client: TestClient, two_tenants: dict[str, str]
):
    response = client.get("/api/v1/assets", headers={"X-API-Key": two_tenants["a"]})

    assert response.status_code == 200
    payload = response.json()
    addresses = {item["asset"]["address"] for item in payload["items"]}
    assert ADDRESS_A in addresses
    assert ADDRESS_B not in addresses
