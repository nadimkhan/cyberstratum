"""Regression tests for multi-tenant (workspace) isolation.

The product's tenancy model is one workspace per tenant. Every query path
that touches tenant data must be scoped to the caller's workspace, so that
one tenant can never see or touch another tenant's scans, findings,
artifacts or jobs.

The conventions these tests pin down (defined in
:mod:`app.core.security` and repeated in each router's docstring):

* A tenant principal's effective workspace is always its own workspace. A
  ``workspace_id`` query parameter naming another workspace is refused
  with ``403``.
* A cross-tenant object read answers ``404``, exactly like a missing
  object, so the API never confirms that an id exists in another tenant.
* A scan is always filed inside the caller's own workspace: a request body
  naming another workspace does not move it there.
* A stored key whose owner has no workspace membership is denied with
  ``403``; it is never widened into an unrestricted principal.
* The configured service key is the administrative credential: it still
  sees every tenant.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api import scans as scans_api
from app.core.security import hash_api_key
from app.db.enums import FindingStatus, ScanStatus, Severity, WorkspaceRole
from app.db.models.identity import (
    ApiKey,
    Chain,
    ContractTarget,
    User,
    Workspace,
    WorkspaceMember,
)
from app.db.models.scans import Finding, Scan, ScanJob

#: A minimal runtime bytecode blob: PUSH1 0x00, SSTORE, STOP.
SAMPLE_BYTECODE = bytes.fromhex("6000556000")


@dataclass(frozen=True)
class Tenant:
    """One tenant: its workspace, its member user and its API key.

    Attributes:
        workspace: The tenant's workspace.
        user: The member user the API key belongs to.
        raw_key: The plaintext API key. It is only ever hashed on the way
            into the database.
    """

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
def tenant_a(db_session: Session) -> Tenant:
    """The first tenant."""
    return _make_tenant(db_session, "alpha")


@pytest.fixture()
def tenant_b(db_session: Session) -> Tenant:
    """The second tenant."""
    return _make_tenant(db_session, "beta")


@pytest.fixture()
def orphan_key(db_session: Session) -> str:
    """A stored API key whose owner belongs to no workspace at all."""
    user = User(
        email=f"orphan-{uuid.uuid4().hex}@example.test",
        display_name="Orphan user",
    )
    db_session.add(user)
    db_session.flush()

    raw_key = f"orphan-key-{uuid.uuid4().hex}"
    db_session.add(
        ApiKey(
            user_id=user.id,
            name="orphan key",
            key_hash=hash_api_key(raw_key),
            key_prefix=raw_key[:12],
        )
    )
    db_session.flush()
    return raw_key


@pytest.fixture()
def make_scan(db_session: Session, chain: Chain):
    """Return a factory that creates a scan (and a finding) inside a tenant."""

    def _make(tenant: Tenant, marker: str = "aa", with_finding: bool = True) -> Scan:
        target = ContractTarget(
            workspace_id=tenant.workspace.id,
            chain_id=chain.id,
            address="0x" + marker * 20,
            label=f"{tenant.workspace.slug} target",
            bytecode_type="runtime",
            authorization_status="unknown",
        )
        db_session.add(target)
        db_session.flush()

        scan = Scan(
            workspace_id=tenant.workspace.id,
            target_id=target.id,
            status=ScanStatus.COMPLETED,
            fork="cancun",
            bytecode_source="test",
        )
        db_session.add(scan)
        db_session.flush()

        if with_finding:
            db_session.add(
                Finding(
                    workspace_id=tenant.workspace.id,
                    scan_id=scan.id,
                    detector_id=f"{marker}.baseline",
                    detector_version="0.1.0",
                    category="reentrancy_candidate",
                    title=f"{marker} finding",
                    description="A deterministic test finding.",
                    severity=Severity.HIGH,
                    confidence=0.5,
                    status=FindingStatus.NEW,
                    evidence_json={"offsets": [1, 2]},
                    limitations="Test data.",
                )
            )
            db_session.flush()
        return scan

    return _make


@pytest.fixture()
def stub_enqueue(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """Replace every enqueue call on the scans router with a recording stub."""
    calls: list[Any] = []

    def fake_enqueue(scan_id: uuid.UUID, job_id: uuid.UUID | None = None) -> str:
        calls.append(scan_id)
        return "rq-job-id"

    monkeypatch.setattr(scans_api, "enqueue_scan", fake_enqueue)
    monkeypatch.setattr(scans_api, "enqueue_mythril", fake_enqueue)
    monkeypatch.setattr(scans_api, "enqueue_correspondence", fake_enqueue)
    return calls


# --------------------------------------------------- (a) cross-tenant reads


def test_tenant_a_cannot_list_tenant_b_scans(
    client: TestClient,
    tenant_a: Tenant,
    tenant_b: Tenant,
    make_scan: Any,
) -> None:
    """The scan list only ever contains the caller's own scans."""
    scan_a = make_scan(tenant_a, marker="a1")
    scan_b = make_scan(tenant_b, marker="b1")

    response = client.get("/api/v1/scans", headers=tenant_a.headers)

    assert response.status_code == 200
    body = response.json()
    ids = {item["id"] for item in body["items"]}
    assert str(scan_a.id) in ids
    assert str(scan_b.id) not in ids
    assert body["total"] == 1
    assert all(item["workspace_id"] == str(tenant_a.workspace.id) for item in body["items"])


def test_tenant_a_cannot_read_tenant_b_scan(
    client: TestClient,
    tenant_a: Tenant,
    tenant_b: Tenant,
    make_scan: Any,
) -> None:
    """A scan in another tenant's workspace reads as not found."""
    scan_b = make_scan(tenant_b, marker="a2")

    response = client.get(f"/api/v1/scans/{scan_b.id}", headers=tenant_a.headers)

    assert response.status_code == 404


def test_cross_tenant_read_is_indistinguishable_from_a_missing_object(
    client: TestClient,
    tenant_a: Tenant,
    tenant_b: Tenant,
    make_scan: Any,
) -> None:
    """The 404 for another tenant's scan is the same 404 as for no scan.

    A different status code, error code or wording would confirm that the
    id exists in another tenant, which is exactly the leak being closed.
    The message echoes the requested id, so only the wording is compared.
    """
    scan_b = make_scan(tenant_b, marker="a3")

    foreign = client.get(f"/api/v1/scans/{scan_b.id}", headers=tenant_a.headers)
    missing = client.get(f"/api/v1/scans/{uuid.uuid4()}", headers=tenant_a.headers)

    assert foreign.status_code == missing.status_code == 404
    foreign_error = foreign.json()["error"]
    missing_error = missing.json()["error"]
    assert foreign_error["code"] == missing_error["code"] == "http_404"
    assert foreign_error["message"].endswith("not found.")
    assert missing_error["message"].endswith("not found.")
    # The message names the id that was asked for, and nothing else.
    assert str(scan_b.id) in foreign_error["message"]


def test_tenant_a_cannot_list_findings_of_tenant_b_scan(
    client: TestClient,
    tenant_a: Tenant,
    tenant_b: Tenant,
    make_scan: Any,
) -> None:
    """The per-scan findings route refuses another tenant's scan."""
    scan_b = make_scan(tenant_b, marker="a4")

    response = client.get(f"/api/v1/scans/{scan_b.id}/findings", headers=tenant_a.headers)

    assert response.status_code == 404


def test_tenant_a_cannot_download_tenant_b_report(
    client: TestClient,
    tenant_a: Tenant,
    tenant_b: Tenant,
    make_scan: Any,
) -> None:
    """The PDF report of another tenant's scan is not downloadable."""
    scan_b = make_scan(tenant_b, marker="a5")

    response = client.get(f"/api/v1/scans/{scan_b.id}/report.pdf", headers=tenant_a.headers)

    assert response.status_code == 404


def test_tenant_a_cannot_trigger_an_action_on_tenant_b_scan(
    client: TestClient,
    tenant_a: Tenant,
    tenant_b: Tenant,
    make_scan: Any,
    stub_enqueue: list[Any],
) -> None:
    """Neither manual action can be started against another tenant's scan."""
    scan_b = make_scan(tenant_b, marker="a6")

    mythril = client.post(f"/api/v1/scans/{scan_b.id}/mythril", headers=tenant_a.headers)
    correspondence = client.post(
        f"/api/v1/scans/{scan_b.id}/correspondence", headers=tenant_a.headers
    )

    assert mythril.status_code == 404
    assert correspondence.status_code == 404
    # Nothing was queued, and no job row was written for the foreign scan.
    assert stub_enqueue == []


def test_tenant_a_cannot_read_tenant_b_correspondence_proof(
    client: TestClient,
    tenant_a: Tenant,
    tenant_b: Tenant,
    make_scan: Any,
) -> None:
    """The correspondence proof of another tenant's scan is not readable."""
    scan_b = make_scan(tenant_b, marker="a7")

    response = client.get(f"/api/v1/scans/{scan_b.id}/correspondence", headers=tenant_a.headers)

    assert response.status_code == 404


def test_tenant_a_findings_list_excludes_tenant_b_findings(
    client: TestClient,
    tenant_a: Tenant,
    tenant_b: Tenant,
    make_scan: Any,
) -> None:
    """The workspace-wide findings list contains only the caller's findings."""
    make_scan(tenant_a, marker="a8")
    scan_b = make_scan(tenant_b, marker="a9")

    response = client.get("/api/v1/findings", headers=tenant_a.headers)

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert all(item["workspace_id"] == str(tenant_a.workspace.id) for item in body["items"])
    assert all(item["scan_id"] != str(scan_b.id) for item in body["items"])


def test_tenant_a_severity_breakdown_excludes_tenant_b_findings(
    client: TestClient,
    tenant_a: Tenant,
    tenant_b: Tenant,
    make_scan: Any,
) -> None:
    """The severity breakdown counts only the caller's own findings."""
    make_scan(tenant_a, marker="b0")
    make_scan(tenant_b, marker="b1")

    response = client.get("/api/v1/findings/summary", headers=tenant_a.headers)

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1


def test_filtering_findings_by_a_foreign_scan_id_yields_an_empty_list(
    client: TestClient,
    tenant_a: Tenant,
    tenant_b: Tenant,
    make_scan: Any,
) -> None:
    """A foreign ``scan_id`` filters to nothing, exactly like an unknown one."""
    scan_b = make_scan(tenant_b, marker="b2")

    foreign = client.get(f"/api/v1/findings?scan_id={scan_b.id}", headers=tenant_a.headers)
    missing = client.get(f"/api/v1/findings?scan_id={uuid.uuid4()}", headers=tenant_a.headers)

    assert foreign.status_code == missing.status_code == 200
    assert foreign.json() == missing.json()
    assert foreign.json()["total"] == 0


def test_tenant_a_can_still_read_its_own_scan(
    client: TestClient,
    tenant_a: Tenant,
    make_scan: Any,
) -> None:
    """The isolation is not a blanket denial: the tenant sees its own data."""
    scan_a = make_scan(tenant_a, marker="b3")

    detail = client.get(f"/api/v1/scans/{scan_a.id}", headers=tenant_a.headers)
    findings = client.get(f"/api/v1/scans/{scan_a.id}/findings", headers=tenant_a.headers)
    listed = client.get("/api/v1/scans", headers=tenant_a.headers)

    assert detail.status_code == 200
    assert findings.status_code == 200
    assert findings.json()["total"] == 1
    assert listed.status_code == 200
    assert listed.json()["total"] == 1


# ------------------------------------- (b) a foreign workspace_id is refused


def test_tenant_a_cannot_list_tenant_b_scans_by_workspace_parameter(
    client: TestClient,
    tenant_a: Tenant,
    tenant_b: Tenant,
    make_scan: Any,
) -> None:
    """Asking for another tenant's workspace through the query string fails."""
    make_scan(tenant_a, marker="b4")
    scan_b = make_scan(tenant_b, marker="b5")

    response = client.get(
        f"/api/v1/scans?workspace_id={tenant_b.workspace.id}",
        headers=tenant_a.headers,
    )

    assert response.status_code == 403
    assert str(scan_b.id) not in response.text
    assert response.json()["error"]["code"] == "http_403"


def test_tenant_a_cannot_list_tenant_b_findings_by_workspace_parameter(
    client: TestClient,
    tenant_a: Tenant,
    tenant_b: Tenant,
    make_scan: Any,
) -> None:
    """The findings list refuses a foreign ``workspace_id``."""
    make_scan(tenant_b, marker="b6")

    response = client.get(
        f"/api/v1/findings?workspace_id={tenant_b.workspace.id}",
        headers=tenant_a.headers,
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "http_403"


def test_tenant_a_cannot_summarise_tenant_b_findings_by_workspace_parameter(
    client: TestClient,
    tenant_a: Tenant,
    tenant_b: Tenant,
    make_scan: Any,
) -> None:
    """The severity breakdown refuses a foreign ``workspace_id``."""
    make_scan(tenant_b, marker="b7")

    response = client.get(
        f"/api/v1/findings/summary?workspace_id={tenant_b.workspace.id}",
        headers=tenant_a.headers,
    )

    assert response.status_code == 403


def test_tenant_a_may_name_its_own_workspace(
    client: TestClient,
    tenant_a: Tenant,
    make_scan: Any,
) -> None:
    """Naming your own workspace is not an error."""
    scan_a = make_scan(tenant_a, marker="b8")

    response = client.get(
        f"/api/v1/scans?workspace_id={tenant_a.workspace.id}",
        headers=tenant_a.headers,
    )

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["id"] == str(scan_a.id)


# ------------------------------------ (c) a stored key with no membership


def test_stored_key_without_membership_is_denied(
    client: TestClient,
    orphan_key: str,
    tenant_b: Tenant,
    make_scan: Any,
) -> None:
    """A key whose owner is in no workspace is refused, not widened."""
    scan_b = make_scan(tenant_b, marker="c1")
    headers = {"X-API-Key": orphan_key}

    scans = client.get("/api/v1/scans", headers=headers)
    findings = client.get("/api/v1/findings", headers=headers)
    summary = client.get("/api/v1/findings/summary", headers=headers)
    detail = client.get(f"/api/v1/scans/{scan_b.id}", headers=headers)

    assert scans.status_code == 403
    assert findings.status_code == 403
    assert summary.status_code == 403
    assert detail.status_code == 403
    assert scans.json()["error"]["code"] == "http_403"
    # The refusal says why, and it says nothing about the other tenant.
    assert "workspace" in scans.json()["error"]["message"].lower()
    assert str(scan_b.id) not in scans.text


def test_stored_key_without_membership_cannot_write(
    client: TestClient,
    orphan_key: str,
    stub_enqueue: list[Any],
) -> None:
    """A key without a workspace cannot file a scan anywhere."""
    response = client.post(
        "/api/v1/scans",
        json={"contract_address": "0x" + "cc" * 20, "chain_id": 1},
        headers={"X-API-Key": orphan_key},
    )

    assert response.status_code == 403
    assert stub_enqueue == []


# ------------------------------------------- (d) the service key is admin


def test_service_key_sees_both_tenants(
    client: TestClient,
    api_headers: dict[str, str],
    tenant_a: Tenant,
    tenant_b: Tenant,
    make_scan: Any,
) -> None:
    """The configured service key remains the administrative credential."""
    scan_a = make_scan(tenant_a, marker="d1")
    scan_b = make_scan(tenant_b, marker="d2")

    response = client.get("/api/v1/scans", headers=api_headers)

    assert response.status_code == 200
    body = response.json()
    ids = {item["id"] for item in body["items"]}
    assert str(scan_a.id) in ids
    assert str(scan_b.id) in ids
    assert body["total"] == 2


def test_service_key_sees_both_tenants_findings(
    client: TestClient,
    api_headers: dict[str, str],
    tenant_a: Tenant,
    tenant_b: Tenant,
    make_scan: Any,
) -> None:
    """The service key's findings view spans every tenant."""
    make_scan(tenant_a, marker="d3")
    make_scan(tenant_b, marker="d4")

    response = client.get("/api/v1/findings", headers=api_headers)

    assert response.status_code == 200
    assert response.json()["total"] == 2


def test_service_key_can_read_a_tenant_scan_detail(
    client: TestClient,
    api_headers: dict[str, str],
    tenant_b: Tenant,
    make_scan: Any,
) -> None:
    """The service key is not narrowed to one tenant."""
    scan_b = make_scan(tenant_b, marker="d5")

    response = client.get(f"/api/v1/scans/{scan_b.id}", headers=api_headers)

    assert response.status_code == 200
    assert response.json()["id"] == str(scan_b.id)


# ------------------------------------------ (e) a scan lands in its own tenant


def test_scan_created_by_tenant_a_lands_in_tenant_a_workspace(
    client: TestClient,
    tenant_a: Tenant,
    tenant_b: Tenant,
    db_session: Session,
    stub_enqueue: list[Any],
) -> None:
    """A request body naming another workspace does not file the scan there."""
    response = client.post(
        "/api/v1/scans",
        json={
            "contract_address": "0x" + "dd" * 20,
            "chain_id": 1,
            "workspace_id": str(tenant_b.workspace.id),
        },
        headers=tenant_a.headers,
    )

    assert response.status_code == 202, response.text
    scan = db_session.get(Scan, uuid.UUID(response.json()["id"]))
    assert scan is not None
    assert scan.workspace_id == tenant_a.workspace.id
    # Nothing landed in the other tenant's workspace.
    assert db_session.query(Scan).filter(Scan.workspace_id == tenant_b.workspace.id).count() == 0


def test_scan_created_without_a_workspace_lands_in_the_callers_workspace(
    client: TestClient,
    tenant_a: Tenant,
    tenant_b: Tenant,
    db_session: Session,
    stub_enqueue: list[Any],
) -> None:
    """A tenant's scan never lands in the shared default workspace."""
    response = client.post(
        "/api/v1/scans",
        json={"contract_address": "0x" + "de" * 20, "chain_id": 1},
        headers=tenant_a.headers,
    )

    assert response.status_code == 202, response.text
    scan = db_session.get(Scan, uuid.UUID(response.json()["id"]))
    assert scan is not None
    assert scan.workspace_id == tenant_a.workspace.id
    assert scan.workspace_id != tenant_b.workspace.id


def test_a_tenant_scan_is_not_readable_by_another_tenant_after_submission(
    client: TestClient,
    tenant_a: Tenant,
    tenant_b: Tenant,
    stub_enqueue: list[Any],
) -> None:
    """The scan tenant A just created is invisible to tenant B."""
    created = client.post(
        "/api/v1/scans",
        json={"contract_address": "0x" + "ef" * 20, "chain_id": 1},
        headers=tenant_a.headers,
    )
    assert created.status_code == 202, created.text
    scan_id = created.json()["id"]

    own = client.get(f"/api/v1/scans/{scan_id}", headers=tenant_a.headers)
    foreign = client.get(f"/api/v1/scans/{scan_id}", headers=tenant_b.headers)
    foreign_list = client.get("/api/v1/scans", headers=tenant_b.headers)

    assert own.status_code == 200
    assert foreign.status_code == 404
    assert foreign_list.status_code == 200
    assert foreign_list.json()["total"] == 0
    assert scan_id not in foreign_list.text


def test_no_scan_job_is_written_for_a_refused_cross_tenant_action(
    client: TestClient,
    tenant_a: Tenant,
    tenant_b: Tenant,
    db_session: Session,
    make_scan: Any,
    stub_enqueue: list[Any],
) -> None:
    """A refused action leaves the other tenant's job table untouched."""
    scan_b = make_scan(tenant_b, marker="e1")

    response = client.post(f"/api/v1/scans/{scan_b.id}/mythril", headers=tenant_a.headers)

    assert response.status_code == 404
    assert db_session.query(ScanJob).filter(ScanJob.scan_id == scan_b.id).count() == 0


# --------------------------------------- discovery is shared, not tenant data


def test_discovery_never_returns_another_tenants_contracts(
    client: TestClient,
    tenant_a: Tenant,
    tenant_b: Tenant,
    db_session: Session,
    chain: Chain,
) -> None:
    """The discovery routes read the shared discovery workspace only.

    Discovery is deliberately shared, so a tenant sees the same public
    contract corpus as everybody else. What it must never do is expose a
    contract that lives inside a tenant's own workspace.
    """
    db_session.add(
        ContractTarget(
            workspace_id=tenant_b.workspace.id,
            chain_id=chain.id,
            address="0x" + "f1" * 20,
            label="Tenant B private target",
            bytecode_type="runtime",
            authorization_status="unknown",
        )
    )
    db_session.flush()

    response = client.get("/api/v1/discovery/contracts", headers=tenant_a.headers)

    assert response.status_code == 200
    assert "Tenant B private target" not in response.text
    assert response.json()["total"] == 0


def test_discovery_is_reachable_by_a_tenant_principal(
    client: TestClient,
    tenant_a: Tenant,
) -> None:
    """A tenant key can read the shared discovery feed.

    The feed is public-chain data published into one shared workspace, so
    denying it to a tenant would break the product without protecting
    anything.
    """
    response = client.get("/api/v1/discovery/contracts", headers=tenant_a.headers)

    assert response.status_code == 200
    assert response.json()["total"] == 0


def test_a_stored_key_without_membership_cannot_use_discovery(
    client: TestClient,
    orphan_key: str,
) -> None:
    """A key with no workspace is denied everywhere, discovery included."""
    response = client.get(
        "/api/v1/discovery/contracts",
        headers={"X-API-Key": orphan_key},
    )

    assert response.status_code == 403

