"""Tests for settling many findings of one kind at once.

The reviewed corpus is what the machine learning pipeline learns from,
and it is written one verdict at a time. A reviewer who has read one
naming-convention finding and decided that it is a style question has
decided the same thing about the others of its kind, so the product has
to be able to record that once.

These tests care about three things: that the verdict reaches every
open finding of that detector and no other, that a finding which has
already been settled is never overwritten, and that the action cannot
reach across tenants.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from sqlalchemy.orm import Session as OrmSession

from app.core.security import hash_api_key
from app.db.enums import FindingStatus, ScanStatus, Severity, WorkspaceRole
from app.db.models.identity import (
    ApiKey,
    AuditEvent,
    Chain,
    ContractTarget,
    User,
    Workspace,
    WorkspaceMember,
)
from app.db.models.scans import Finding, Scan


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
def scan(db_session: Session, tenant: Tenant, chain: Chain) -> Scan:
    """Create a completed scan, with a target, inside the tenant's workspace."""
    target = ContractTarget(
        workspace_id=tenant.workspace.id,
        chain_id=chain.id,
        address="0x" + "cd" * 20,
        label="bulk review target",
        bytecode_type="runtime",
        authorization_status="unknown",
    )
    db_session.add(target)
    db_session.flush()

    row = Scan(
        workspace_id=tenant.workspace.id,
        target_id=target.id,
        status=ScanStatus.COMPLETED,
        fork="cancun",
        bytecode_source="test",
    )
    db_session.add(row)
    db_session.flush()
    return row


def _add_finding(
    session: Session,
    scan: Scan,
    detector_id: str,
    *,
    status: FindingStatus = FindingStatus.NEW,
    workspace_id: uuid.UUID | None = None,
) -> Finding:
    """Add one finding of a detector to a scan."""
    finding = Finding(
        workspace_id=workspace_id or scan.workspace_id,
        scan_id=scan.id,
        detector_id=detector_id,
        detector_version="0.1.0",
        category="style",
        title=f"a {detector_id} finding",
        description="A deterministic test finding.",
        severity=Severity.LOW,
        confidence=0.5,
        status=status,
        evidence_json={"offsets": [1]},
    )
    session.add(finding)
    session.flush()
    return finding


def test_one_verdict_settles_every_open_finding_of_the_detector(
    client: TestClient, tenant: Tenant, db_session: Session, scan: Scan
) -> None:
    """The whole point: three findings, one action."""
    for _ in range(3):
        _add_finding(db_session, scan, "slither.naming_convention")
    other = _add_finding(db_session, scan, "slither.dead_code")
    db_session.flush()

    response = client.post(
        "/api/v1/findings/review-bulk",
        headers=tenant.headers,
        json={"detector_id": "slither.naming_convention", "status": "false_positive",
              "note": "a style question, not a defect"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["applied"] == 3
    assert len(body["finding_ids"]) == 3
    db_session.expire_all()
    assert other.status is FindingStatus.NEW


def test_a_settled_finding_is_not_overwritten(
    client: TestClient, tenant: Tenant, db_session: Session, scan: Scan
) -> None:
    """A reviewed label is not something to refresh without a reason."""
    settled = _add_finding(db_session, scan, "slither.naming_convention",
                           status=FindingStatus.CONFIRMED)
    settled.review_note = "decided by hand"
    db_session.flush()

    response = client.post(
        "/api/v1/findings/review-bulk",
        headers=tenant.headers,
        json={"detector_id": "slither.naming_convention", "status": "false_positive",
              "note": "a style question"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["applied"] == 0
    assert response.json()["skipped"] == 1
    db_session.expire_all()
    assert settled.status is FindingStatus.CONFIRMED
    assert settled.review_note == "decided by hand"


def test_a_false_positive_without_a_reason_is_refused(
    client: TestClient, tenant: Tenant, db_session: Session, scan: Scan
) -> None:
    """Without a reason it cannot be told apart from a mistaken verdict."""
    _add_finding(db_session, scan, "slither.naming_convention")
    db_session.flush()

    response = client.post(
        "/api/v1/findings/review-bulk",
        headers=tenant.headers,
        json={"detector_id": "slither.naming_convention", "status": "false_positive"},
    )

    assert response.status_code == 422
    assert "reason" in response.json()["error"]["message"].lower()


def test_new_is_not_a_verdict(
    client: TestClient, tenant: Tenant, db_session: Session, scan: Scan
) -> None:
    """'new' is not something a reviewer can decide."""
    _add_finding(db_session, scan, "slither.naming_convention")
    db_session.flush()

    response = client.post(
        "/api/v1/findings/review-bulk",
        headers=tenant.headers,
        json={"detector_id": "slither.naming_convention", "status": "new"},
    )

    assert response.status_code == 422


def test_the_action_does_not_reach_another_tenant(
    client: TestClient, tenant: Tenant, db_session: Session, scan: Scan
) -> None:
    """The same detector id in another workspace is another tenant's data."""
    other_tenant = _make_tenant(db_session, "beta")
    theirs = _add_finding(
        db_session,
        scan,
        "slither.naming_convention",
        workspace_id=other_tenant.workspace.id,
    )
    db_session.flush()

    response = client.post(
        "/api/v1/findings/review-bulk",
        headers=tenant.headers,
        json={"detector_id": "slither.naming_convention", "status": "confirmed"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["applied"] == 0
    db_session.expire_all()
    assert theirs.status is FindingStatus.NEW


def test_the_verdicts_are_written_to_the_audit_trail(
    client: TestClient, tenant: Tenant, db_session: Session, scan: Scan
) -> None:
    """Every finding the action touches leaves a trace."""
    finding = _add_finding(db_session, scan, "slither.naming_convention")
    db_session.flush()

    client.post(
        "/api/v1/findings/review-bulk",
        headers=tenant.headers,
        json={"detector_id": "slither.naming_convention", "status": "confirmed",
              "note": "read the code"},
    )
    db_session.flush()

    events = (
        db_session.query(AuditEvent)
        .filter(AuditEvent.resource_id == str(finding.id))
        .all()
    )
    assert len(events) == 1
    assert events[0].action == "finding.reviewed"
    assert events[0].metadata_redacted["bulk"] is True
    assert events[0].metadata_redacted["status"] == "confirmed"


def test_the_verdicts_are_committed_and_not_only_flushed(
    client: TestClient,
    tenant: Tenant,
    db_session: Session,
    scan: Scan,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A verdict that is only flushed is a verdict that never happened."""
    commits: list[str] = []
    original = OrmSession.commit

    def spy(self: OrmSession, *args: object, **kwargs: object) -> None:
        commits.append("commit")
        original(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(OrmSession, "commit", spy)

    _add_finding(db_session, scan, "slither.naming_convention")
    db_session.flush()
    commits.clear()

    response = client.post(
        "/api/v1/findings/review-bulk",
        headers=tenant.headers,
        json={"detector_id": "slither.naming_convention", "status": "confirmed"},
    )

    assert response.status_code == 200, response.text
    assert commits, "the endpoint flushed but never committed"


def test_the_action_requires_authentication(
    client: TestClient, db_session: Session, scan: Scan
) -> None:
    """No key, no verdict."""
    _add_finding(db_session, scan, "slither.naming_convention")
    db_session.flush()

    response = client.post(
        "/api/v1/findings/review-bulk",
        json={"detector_id": "slither.naming_convention", "status": "confirmed"},
    )

    assert response.status_code == 401


# ---------------------------------------------------------------- the workspace rule


def _service_headers() -> dict[str, str]:
    """The administrative service key, which acts across every tenant."""
    from app.core.config import get_settings

    return {"X-API-Key": get_settings().api_key}


def test_the_service_key_must_name_the_workspace_it_acts_in(
    client: TestClient, tenant: Tenant, db_session: Session, scan: Scan
) -> None:
    """A verdict that reaches every tenant is not a verdict."""
    _add_finding(db_session, scan, "slither.naming_convention")
    db_session.flush()

    response = client.post(
        "/api/v1/findings/review-bulk",
        headers=_service_headers(),
        json={"detector_id": "slither.naming_convention", "status": "confirmed"},
    )

    assert response.status_code == 403
    assert "workspace" in response.json()["error"]["message"].lower()


def test_the_service_key_acts_in_the_workspace_it_names(
    client: TestClient, tenant: Tenant, db_session: Session, scan: Scan
) -> None:
    """Naming a workspace settles that tenant's findings and no others."""
    other = _make_tenant(db_session, "beta")
    theirs = _add_finding(
        db_session,
        scan,
        "slither.naming_convention",
        workspace_id=other.workspace.id,
    )
    ours = _add_finding(db_session, scan, "slither.naming_convention")
    db_session.flush()

    response = client.post(
        "/api/v1/findings/review-bulk",
        headers=_service_headers(),
        params={"workspace_id": str(tenant.workspace.id)},
        json={"detector_id": "slither.naming_convention", "status": "confirmed"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["applied"] == 1
    db_session.expire_all()
    assert ours.status is FindingStatus.CONFIRMED
    assert theirs.status is FindingStatus.NEW


def test_a_tenant_cannot_name_another_workspace(
    client: TestClient, tenant: Tenant, db_session: Session, scan: Scan
) -> None:
    """A tenant's key only ever acts in its own workspace."""
    other = _make_tenant(db_session, "beta")
    _add_finding(db_session, scan, "slither.naming_convention")
    db_session.flush()

    response = client.post(
        "/api/v1/findings/review-bulk",
        headers=tenant.headers,
        params={"workspace_id": str(other.workspace.id)},
        json={"detector_id": "slither.naming_convention", "status": "confirmed"},
    )

    assert response.status_code == 403


def test_a_tenant_sees_only_its_own_workspace(
    client: TestClient, tenant: Tenant, db_session: Session
) -> None:
    """The list a reviewer picks from holds their own tenant and no other."""
    _make_tenant(db_session, "beta")

    response = client.get("/api/v1/workspaces", headers=tenant.headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body) == 1
    assert body[0]["id"] == str(tenant.workspace.id)
    assert body[0]["slug"] == tenant.workspace.slug


def test_the_service_key_sees_every_workspace_with_its_open_findings(
    client: TestClient, tenant: Tenant, db_session: Session, scan: Scan
) -> None:
    """The administrative view names every tenant and how much is waiting."""
    other = _make_tenant(db_session, "beta")
    _add_finding(db_session, scan, "slither.naming_convention")
    _add_finding(
        db_session,
        scan,
        "slither.dead_code",
        workspace_id=other.workspace.id,
    )
    db_session.flush()

    response = client.get("/api/v1/workspaces", headers=_service_headers())

    assert response.status_code == 200, response.text
    body = {row["id"]: row for row in response.json()}
    assert set(body) == {str(tenant.workspace.id), str(other.workspace.id)}
    assert body[str(tenant.workspace.id)]["open_findings"] == 1
    assert body[str(other.workspace.id)]["open_findings"] == 1
