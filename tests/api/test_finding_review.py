"""Tests for the review surface.

The machine learning labels come from here, so these tests care about
three things: that a verdict is stored with who made it and why, that a
false positive without a reason is refused (it would be unusable as
ground truth), and that a finding belonging to another tenant cannot be
reviewed at all.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

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
    user = User(
        email=f"{label}-{uuid.uuid4().hex}@example.test", display_name=f"{label} user"
    )
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
        label="review target",
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


def _add_finding(session: Session, scan: Scan) -> Finding:
    finding = Finding(
        workspace_id=scan.workspace_id,
        scan_id=scan.id,
        detector_id="baseline.test",
        detector_version="0.1.0",
        category="reentrancy_candidate",
        title="a deterministic test finding",
        description="A deterministic test finding.",
        severity=Severity.HIGH,
        confidence=0.5,
        status=FindingStatus.NEW,
        evidence_json={"offsets": [1, 2]},
    )
    session.add(finding)
    session.flush()
    return finding


def test_a_verdict_is_recorded_with_its_reviewer_and_reason(
    client: TestClient, tenant: Tenant, db_session: Session, scan: Scan
) -> None:
    finding = _add_finding(db_session, scan)
    db_session.flush()

    response = client.post(
        f"/api/v1/findings/{finding.id}/review",
        headers=tenant.headers,
        json={"status": "confirmed", "note": "the reentrancy is reachable"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "confirmed"
    assert body["review_note"] == "the reentrancy is reachable"
    assert body["reviewed_at"] is not None
    assert body["reviewed_by"] == str(tenant.user.id)


def test_a_false_positive_without_a_reason_is_refused(
    client: TestClient, tenant: Tenant, db_session: Session, scan: Scan
) -> None:
    finding = _add_finding(db_session, scan)
    db_session.flush()

    response = client.post(
        f"/api/v1/findings/{finding.id}/review",
        headers=tenant.headers,
        json={"status": "false_positive"},
    )

    assert response.status_code == 422
    message = response.json()["error"]["message"].lower()
    assert "reason" in message


def test_a_false_positive_with_a_reason_is_accepted(
    client: TestClient, tenant: Tenant, db_session: Session, scan: Scan
) -> None:
    finding = _add_finding(db_session, scan)
    db_session.flush()

    response = client.post(
        f"/api/v1/findings/{finding.id}/review",
        headers=tenant.headers,
        json={"status": "false_positive", "note": "the state is written before the call"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "false_positive"


def test_new_is_not_a_verdict(
    client: TestClient, tenant: Tenant, db_session: Session, scan: Scan
) -> None:
    finding = _add_finding(db_session, scan)
    db_session.flush()

    response = client.post(
        f"/api/v1/findings/{finding.id}/review",
        headers=tenant.headers,
        json={"status": "new"},
    )

    assert response.status_code == 422


def test_a_review_is_written_to_the_audit_trail(
    client: TestClient, tenant: Tenant, db_session: Session, scan: Scan
) -> None:
    finding = _add_finding(db_session, scan)
    db_session.flush()

    client.post(
        f"/api/v1/findings/{finding.id}/review",
        headers=tenant.headers,
        json={"status": "needs_more_evidence", "note": "needs the source"},
    )
    db_session.flush()

    events = (
        db_session.query(AuditEvent)
        .filter(AuditEvent.resource_id == str(finding.id))
        .all()
    )
    assert len(events) == 1
    assert events[0].action == "finding.reviewed"
    assert events[0].metadata_redacted["status"] == "needs_more_evidence"


def test_a_finding_from_another_tenant_cannot_be_reviewed(
    client: TestClient, tenant: Tenant, db_session: Session, scan: Scan
) -> None:
    finding = _add_finding(db_session, scan)
    # Move it to another workspace that really exists: the id must become
    # invisible rather than forbidden, so the endpoint never confirms
    # that it exists.
    other = _make_tenant(db_session, "beta")
    finding.workspace_id = other.workspace.id
    db_session.flush()

    response = client.post(
        f"/api/v1/findings/{finding.id}/review",
        headers=tenant.headers,
        json={"status": "confirmed", "note": "not mine"},
    )

    assert response.status_code == 404


def test_an_unknown_finding_is_not_found(
    client: TestClient, tenant: Tenant
) -> None:
    response = client.post(
        f"/api/v1/findings/{uuid.uuid4()}/review",
        headers=tenant.headers,
        json={"status": "confirmed"},
    )
    assert response.status_code == 404


def test_reviewing_requires_authentication(
    client: TestClient, db_session: Session, scan: Scan
) -> None:
    finding = _add_finding(db_session, scan)
    db_session.flush()

    response = client.post(
        f"/api/v1/findings/{finding.id}/review",
        json={"status": "confirmed"},
    )
    assert response.status_code == 401
