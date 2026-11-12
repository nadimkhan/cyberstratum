"""Tests for the authorised scope of a workspace."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models.identity import Workspace
from app.db.models.scope import ScopeGrant

OTHER_ADDRESS = "0x6666666666666666666666666666666666666666"


def _grant(
    session: Session,
    workspace: Workspace,
    *,
    kind: str = "contract",
    value: str = "0x1111111111111111111111111111111111111111",
    chain_id: int | None = None,
    safe_harbour: bool = False,
    expires_at: datetime | None = None,
) -> ScopeGrant:
    grant = ScopeGrant(
        workspace_id=workspace.id,
        kind=kind,
        value=value,
        chain_id=chain_id,
        safe_harbour=safe_harbour,
        expires_at=expires_at,
    )
    session.add(grant)
    session.flush()
    return grant


def _status(
    client: TestClient,
    headers: dict[str, str],
    workspace: Workspace,
    *,
    address: str,
    chain_id: int = 1,
) -> dict:
    response = client.get(
        "/api/v1/scope/status",
        headers=headers,
        params={
            "address": address,
            "chain_id": chain_id,
            "workspace_id": str(workspace.id),
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_a_workspace_with_no_scope_is_unknown_not_refused(
    client: TestClient, api_headers: dict[str, str], workspace: Workspace
) -> None:
    """Nothing has been claimed either way, so nothing is invented."""
    body = _status(client, api_headers, workspace, address="0xabc")

    assert body["status"] == "unknown"
    assert body["reason"]
    assert "not authorised for disclosure" in body["statement"]


def test_a_declared_grant_makes_the_target_in_scope(
    client: TestClient,
    api_headers: dict[str, str],
    db_session: Session,
    workspace: Workspace,
) -> None:
    """A contract the workspace declared is in scope."""
    address = "0x2222222222222222222222222222222222222222"
    _grant(db_session, workspace, kind="contract", value=address, safe_harbour=True)
    db_session.flush()

    body = _status(client, api_headers, workspace, address=address)

    assert body["status"] == "in_scope"
    assert body["safe_harbour"] is True
    assert "authorised scope grant" in body["statement"]


def test_a_declared_scope_leaves_another_contract_out_of_scope(
    client: TestClient,
    api_headers: dict[str, str],
    db_session: Session,
    workspace: Workspace,
) -> None:
    """A workspace that declared a scope is refused for what it did not declare."""
    _grant(
        db_session,
        workspace,
        kind="contract",
        value="0x3333333333333333333333333333333333333333",
    )
    db_session.flush()

    body = _status(
        client,
        api_headers,
        workspace,
        address="0x4444444444444444444444444444444444444444",
    )

    assert body["status"] == "out_of_scope"
    assert "not authorised for disclosure" in body["statement"]


def test_an_expired_grant_leaves_the_workspace_unknown(
    client: TestClient,
    api_headers: dict[str, str],
    db_session: Session,
    workspace: Workspace,
) -> None:
    """A grant that has expired is not a grant."""
    address = "0x5555555555555555555555555555555555555555"
    _grant(
        db_session,
        workspace,
        value=address,
        expires_at=datetime.now(UTC) - timedelta(days=1),
    )
    db_session.flush()

    body = _status(client, api_headers, workspace, address=address)

    assert body["status"] == "unknown"


def test_the_grants_are_listed_and_created(
    client: TestClient, api_headers: dict[str, str], workspace: Workspace
) -> None:
    """A workspace can declare its scope and read it back."""
    created = client.post(
        "/api/v1/scope/grants",
        headers=api_headers,
        params={"workspace_id": str(workspace.id)},
        json={
            "kind": "programme",
            "value": "Example Bug Bounty",
            "chain_id": 1,
            "safe_harbour": True,
            "reference": "https://example.invalid/scope",
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["kind"] == "programme"
    assert body["safe_harbour"] is True
    assert body["reference"] == "https://example.invalid/scope"

    listed = client.get(
        "/api/v1/scope/grants",
        headers=api_headers,
        params={"workspace_id": str(workspace.id)},
    )
    assert listed.status_code == 200
    assert any(item["id"] == body["id"] for item in listed.json())


def test_a_bad_grant_is_refused(
    client: TestClient, api_headers: dict[str, str], workspace: Workspace
) -> None:
    """A grant of an unknown kind, or with nothing in it, is not stored."""
    bad_kind = client.post(
        "/api/v1/scope/grants",
        headers=api_headers,
        params={"workspace_id": str(workspace.id)},
        json={"kind": "everything", "value": "x"},
    )
    assert bad_kind.status_code == 422

    empty = client.post(
        "/api/v1/scope/grants",
        headers=api_headers,
        params={"workspace_id": str(workspace.id)},
        json={"kind": "contract", "value": "   "},
    )
    assert empty.status_code == 422


def test_another_workspaces_grants_are_not_visible(
    client: TestClient,
    api_headers: dict[str, str],
    db_session: Session,
    workspace: Workspace,
) -> None:
    """The scope of one tenant is not the scope of another."""
    other = Workspace(name="Other", slug=f"other-{uuid.uuid4().hex[:8]}")
    db_session.add(other)
    db_session.flush()
    _grant(db_session, other, value=OTHER_ADDRESS, safe_harbour=True)
    db_session.flush()

    listed = client.get(
        "/api/v1/scope/grants",
        headers=api_headers,
        params={"workspace_id": str(workspace.id)},
    )
    assert listed.status_code == 200
    assert all(item["value"] != OTHER_ADDRESS for item in listed.json())

    body = _status(client, api_headers, workspace, address=OTHER_ADDRESS)
    assert body["status"] == "unknown"


def test_the_scope_needs_a_credential(
    client: TestClient,
) -> None:
    """The scope of a workspace is not public."""
    assert client.get("/api/v1/scope/grants").status_code in (401, 403)
    assert client.get("/api/v1/scope/status").status_code in (401, 403)


def test_an_administrative_action_must_name_its_workspace(
    client: TestClient, api_headers: dict[str, str]
) -> None:
    """A scope that applies to every workspace at once is not a scope."""
    refused = client.get("/api/v1/scope/grants", headers=api_headers)
    assert refused.status_code == 403

    refused_write = client.post(
        "/api/v1/scope/grants",
        headers=api_headers,
        json={"kind": "contract", "value": "0xabc"},
    )
    assert refused_write.status_code == 403


def test_an_expiry_is_stored_and_is_read_back(
    client: TestClient, api_headers: dict[str, str], workspace: Workspace
) -> None:
    """A grant that says when it ends says it when it is stored."""
    created = client.post(
        "/api/v1/scope/grants",
        headers=api_headers,
        params={"workspace_id": str(workspace.id)},
        json={
            "kind": "contract",
            "value": "0x7777777777777777777777777777777777777777",
            "expires_at": "2027-01-01T00:00:00Z",
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["expires_at"].startswith("2027-01-01T00:00:00")

    listed = client.get(
        "/api/v1/scope/grants",
        headers=api_headers,
        params={"workspace_id": str(workspace.id)},
    )
    assert listed.status_code == 200
    stored = [item for item in listed.json() if item["expires_at"]]
    assert len(stored) == 1


def test_an_expiry_that_cannot_be_read_is_refused(
    client: TestClient, api_headers: dict[str, str], workspace: Workspace
) -> None:
    """A grant whose date the product cannot read is not stored at all."""
    refused = client.post(
        "/api/v1/scope/grants",
        headers=api_headers,
        params={"workspace_id": str(workspace.id)},
        json={
            "kind": "contract",
            "value": "0x8888888888888888888888888888888888888888",
            "expires_at": "whenever",
        },
    )
    assert refused.status_code == 422

    listed = client.get(
        "/api/v1/scope/grants",
        headers=api_headers,
        params={"workspace_id": str(workspace.id)},
    )
    assert all(
        item["value"] != "0x8888888888888888888888888888888888888888" for item in listed.json()
    )


def test_a_declaration_can_be_withdrawn(
    client: TestClient, api_headers: dict[str, str], workspace: Workspace
) -> None:
    """A declaration that was made in error has to be withdrawable."""
    created = client.post(
        "/api/v1/scope/grants",
        headers=api_headers,
        params={"workspace_id": str(workspace.id)},
        json={"kind": "contract", "value": "0x9999999999999999999999999999999999999999"},
    )
    assert created.status_code == 201, created.text
    grant_id = created.json()["id"]

    withdrawn = client.delete(
        f"/api/v1/scope/grants/{grant_id}",
        headers=api_headers,
        params={"workspace_id": str(workspace.id)},
    )
    assert withdrawn.status_code == 204, withdrawn.text

    listed = client.get(
        "/api/v1/scope/grants",
        headers=api_headers,
        params={"workspace_id": str(workspace.id)},
    )
    assert all(item["id"] != grant_id for item in listed.json())


def test_another_workspaces_grant_cannot_be_withdrawn(
    client: TestClient,
    api_headers: dict[str, str],
    db_session: Session,
    workspace: Workspace,
) -> None:
    """A declaration belongs to one workspace, and only that one."""
    other = Workspace(name="Other", slug=f"other-{uuid.uuid4().hex[:8]}")
    db_session.add(other)
    db_session.flush()
    grant = _grant(db_session, other, value=OTHER_ADDRESS)
    db_session.flush()

    refused = client.delete(
        f"/api/v1/scope/grants/{grant.id}",
        headers=api_headers,
        params={"workspace_id": str(workspace.id)},
    )
    assert refused.status_code == 404

    # The row is still there: the refusal did not withdraw it. The
    # session is told to forget what it cached, so the check reads the
    # database and not the object the test happens to be holding.
    db_session.expire_all()
    assert db_session.get(ScopeGrant, grant.id) is not None
