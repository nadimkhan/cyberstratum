"""Tests for workspace-scoped API keys.

A machine client belongs to one tenant. These tests pin the two things
that make that true: a key acts in the workspace it was issued for, and
a key whose expiry has passed stops working.

The legacy case matters too: a key issued before the ``workspace_id``
column existed carries no workspace, and then falls back to the owner's
earliest membership -- the only workspace it could have been used in.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app.cli.issue_key import KeyIssuanceError, issue_key
from app.core.security import _principal_for_stored_key, hash_api_key
from app.db.enums import WorkspaceRole
from app.db.models.identity import ApiKey, User, Workspace, WorkspaceMember


def _user(session: Session, label: str) -> User:
    user = User(email=f"{label}-{uuid.uuid4().hex}@example.test", display_name=label)
    session.add(user)
    session.flush()
    return user


def _workspace(session: Session, label: str, user: User) -> Workspace:
    space = Workspace(name=f"{label} space", slug=f"{label}-{uuid.uuid4().hex}")
    session.add(space)
    session.flush()
    session.add(
        WorkspaceMember(
            workspace_id=space.id,
            user_id=user.id,
            role=WorkspaceRole.OWNER,
        )
    )
    session.flush()
    return space


def _key(
    session: Session,
    *,
    user: User,
    workspace: Workspace | None,
    raw_key: str | None = None,
    is_active: bool = True,
    expires_at: datetime | None = None,
) -> str:
    raw = raw_key or f"key-{uuid.uuid4().hex}"
    session.add(
        ApiKey(
            user_id=user.id,
            workspace_id=workspace.id if workspace is not None else None,
            name="test key",
            key_hash=hash_api_key(raw),
            key_prefix=raw[:12],
            is_active=is_active,
            expires_at=expires_at,
        )
    )
    session.flush()
    return raw


def test_a_key_acts_in_the_workspace_it_was_issued_for(db_session: Session):
    """The workspace on the key wins, even when another came first."""
    user = _user(db_session, "owner")
    first = _workspace(db_session, "first", user)
    second = _workspace(db_session, "second", user)

    raw = _key(db_session, user=user, workspace=second)

    principal = _principal_for_stored_key(db_session, raw)

    assert principal is not None
    assert principal.workspace_id == second.id
    assert principal.workspace_id != first.id


def test_a_key_without_a_workspace_falls_back_to_the_earliest_membership(
    db_session: Session,
):
    """A key issued before the column existed keeps its old meaning."""
    user = _user(db_session, "legacy")
    early = _workspace(db_session, "early", user)
    late = _workspace(db_session, "late", user)

    now = datetime.now(UTC)
    early_member = db_session.query(WorkspaceMember).filter_by(
        user_id=user.id, workspace_id=early.id
    ).one()
    late_member = db_session.query(WorkspaceMember).filter_by(
        user_id=user.id, workspace_id=late.id
    ).one()
    early_member.created_at = now - timedelta(days=1)
    late_member.created_at = now
    db_session.flush()

    raw = _key(db_session, user=user, workspace=None)

    principal = _principal_for_stored_key(db_session, raw)

    assert principal is not None
    assert principal.workspace_id == early.id


def test_an_expired_key_stops_working(db_session: Session):
    """An expiry that has passed means the key is refused."""
    user = _user(db_session, "expired")
    space = _workspace(db_session, "expired space", user)

    raw = _key(
        db_session,
        user=user,
        workspace=space,
        expires_at=datetime.now(UTC) - timedelta(minutes=1),
    )

    assert _principal_for_stored_key(db_session, raw) is None


def test_a_key_that_has_not_expired_still_works(db_session: Session):
    user = _user(db_session, "live")
    space = _workspace(db_session, "live space", user)

    raw = _key(
        db_session,
        user=user,
        workspace=space,
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )

    principal = _principal_for_stored_key(db_session, raw)

    assert principal is not None
    assert principal.workspace_id == space.id


def test_an_inactive_key_is_refused(db_session: Session):
    user = _user(db_session, "disabled")
    space = _workspace(db_session, "disabled space", user)

    raw = _key(db_session, user=user, workspace=space, is_active=False)

    assert _principal_for_stored_key(db_session, raw) is None


def test_the_command_issues_a_key_for_the_asked_workspace(db_session: Session):
    """The key the operator gets acts in the workspace they named."""
    user = _user(db_session, "operator")
    space = _workspace(db_session, "operator space", user)

    raw, row = issue_key(
        db_session,
        workspace_slug=space.slug,
        name="ci pipeline",
        user_email=user.email,
    )

    assert row.workspace_id == space.id
    assert row.key_hash == hash_api_key(raw)
    assert raw not in row.key_hash
    principal = _principal_for_stored_key(db_session, raw)
    assert principal is not None
    assert principal.workspace_id == space.id


def test_the_command_refuses_a_workspace_that_does_not_exist(db_session: Session):
    with pytest.raises(KeyIssuanceError):
        issue_key(db_session, workspace_slug="no-such-workspace", name="key")


def test_the_command_refuses_a_user_who_is_not_a_member(db_session: Session):
    """A key must not hand out access its owner does not have."""
    user = _user(db_session, "outsider")
    other = _user(db_session, "insider")
    space = _workspace(db_session, "insider space", other)

    with pytest.raises(KeyIssuanceError):
        issue_key(
            db_session,
            workspace_slug=space.slug,
            name="key",
            user_email=user.email,
        )
