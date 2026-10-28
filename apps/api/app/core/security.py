"""API-key authentication.

Two credential sources are supported:

1. The static key configured through ``API_KEY`` (the documented dev default).
2. Per-user API keys stored in the ``api_keys`` table, verified by SHA-256
   digest lookup.

The dependency resolves to a principal describing who is calling; requests
without a usable key are rejected with ``401``.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.enums import UserStatus
from app.db.models.identity import ApiKey, User, WorkspaceMember
from app.db.session import get_session_factory


@dataclass(frozen=True, slots=True)
class Principal:
    """The authenticated caller."""

    user_id: uuid.UUID | None
    workspace_id: uuid.UUID | None
    api_key_id: uuid.UUID | None
    source: str

    @property
    def is_service_key(self) -> bool:
        """True when the caller authenticated with the static configured key."""
        return self.source == "configured"


def hash_api_key(raw_key: str) -> str:
    """Return the hex SHA-256 digest of ``raw_key``."""
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def get_session() -> Iterator[Session]:
    """FastAPI dependency yielding a database session."""
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


SessionDep = Annotated[Session, Depends(get_session)]


def _principal_for_configured_key() -> Principal:
    return Principal(
        user_id=None,
        workspace_id=None,
        api_key_id=None,
        source="configured",
    )


def _principal_for_stored_key(session: Session, raw_key: str) -> Principal | None:
    digest = hash_api_key(raw_key)
    api_key = session.scalars(select(ApiKey).where(ApiKey.key_hash == digest)).one_or_none()
    if api_key is None or not api_key.is_active:
        return None

    workspace_id: uuid.UUID | None = None
    if api_key.user_id is not None:
        membership = session.scalars(
            select(WorkspaceMember)
            .where(WorkspaceMember.user_id == api_key.user_id)
            .limit(1)
        ).first()
        if membership is not None:
            workspace_id = membership.workspace_id

    return Principal(
        user_id=api_key.user_id,
        workspace_id=workspace_id,
        api_key_id=api_key.id,
        source="stored",
    )


def authenticate(
    session: SessionDep,
    settings: Annotated[Settings, Depends(get_settings)],
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> Principal:
    """Authenticate a request via the ``X-API-Key`` header.

    Raises:
        HTTPException: 401 when no valid key is presented.
    """
    if not x_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API key. Supply the X-API-Key header.",
        )

    if settings.api_key and x_api_key == settings.api_key:
        return _principal_for_configured_key()

    principal = _principal_for_stored_key(session, x_api_key)
    if principal is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key.",
        )
    return principal


CurrentPrincipal = Annotated[Principal, Depends(authenticate)]


def ensure_active_user(session: Session, principal: Principal) -> Principal:
    """Ensure the principal maps to an active user when it is user-scoped.

    Raises:
        HTTPException: 403 when the backing user is missing or not active.
    """
    if principal.user_id is None:
        return principal
    user = session.get(User, principal.user_id)
    if user is None or user.status is not UserStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is not active.",
        )
    return principal


__all__ = [
    "CurrentPrincipal",
    "Principal",
    "SessionDep",
    "authenticate",
    "ensure_active_user",
    "get_session",
    "hash_api_key",
]
