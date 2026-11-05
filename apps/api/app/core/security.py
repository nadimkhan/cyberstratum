"""API-key authentication and workspace (tenant) scoping.

Two credential sources are supported:

1. The static key configured through ``API_KEY``. This is the
   **administrative** credential: it is deliberately unscoped and may read
   and write every tenant's data. It exists for the single-developer local
   setup, the web frontend and the CLI.
2. Per-user API keys stored in the ``api_keys`` table, verified by SHA-256
   digest lookup. These are **tenant** credentials: they are scoped to the
   workspace of their owner's membership.

The dependency resolves to a principal describing who is calling; requests
without a usable key are rejected with ``401``.

Scoping conventions
-------------------

These rules are implemented once, here, and applied by every route that
reads or writes tenant data (scans, findings, artifacts, jobs, targets).
Each router repeats them in its own module docstring.

1. **A tenant principal is scoped to exactly one workspace** -- the
   workspace of its owner's membership. A stored key whose owner belongs to
   no workspace is rejected with ``403``: it never receives unrestricted
   visibility of every tenant's data.

2. **The static configured key is an explicit administrative capability.**
   It is unscoped by design, and the code says so through
   ``Principal.is_service_key`` rather than through an accidental ``None``.
   Routers ask ``read_scope()`` / ``write_workspace_id()`` /
   ``may_read_workspace()`` instead of testing ``workspace_id is not None``
   themselves.

3. **A supplied ``workspace_id`` never selects another tenant's data.**
   The effective workspace of a tenant principal is always its own
   workspace, and a ``workspace_id`` naming a different workspace is never
   honoured:

   - On a **read**, the request is refused with ``403``. The caller asked
     for a scope it does not have, and answering with the caller's own
     rows instead would misrepresent what was asked for.
   - On a **write**, the object is filed under the principal's own
     workspace. The scan is created, but never inside another tenant.

4. **A cross-tenant object read is indistinguishable from a missing one.**
   Detail, findings, report and action endpoints answer ``404 Not Found``
   for an object that belongs to another workspace, exactly as they do for
   an object that does not exist, so the API never confirms that an id
   exists in another tenant. A list endpoint never contains another
   tenant's objects: asking for one is the same as asking for something
   that does not exist.
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

from app.core.auth import AuthStoreError, verify_session_claims
from app.core.config import Settings, get_settings
from app.db.enums import UserStatus
from app.db.models.identity import ApiKey, User, WorkspaceMember
from app.db.session import get_session_factory

#: Detail returned when a stored key has no workspace to be scoped to.
NO_MEMBERSHIP_DETAIL = (
    "This API key is not a member of any workspace, so it cannot access tenant data. "
    "Add the key's owner to a workspace, or use the configured service key."
)


@dataclass(frozen=True, slots=True)
class Principal:
    """The authenticated caller.

    Attributes:
        user_id: The owning user, or ``None`` for the service key.
        workspace_id: The tenant workspace the caller is scoped to, or
            ``None`` for the administrative service key.
        api_key_id: The stored key's id, or ``None`` for the service key.
        source: ``"configured"`` for the static key, ``"stored"`` for a row
            in ``api_keys``.
    """

    user_id: uuid.UUID | None
    workspace_id: uuid.UUID | None
    api_key_id: uuid.UUID | None
    source: str

    @property
    def is_service_key(self) -> bool:
        """True when the caller authenticated with the static configured key.

        This is the administrative credential: it is deliberately unscoped
        and may act across every tenant. Routers must branch on this flag
        rather than on ``workspace_id is None``, so that the capability is
        explicit instead of an accident of a missing value.
        """
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
    """Resolve a stored key to a tenant principal.

    The key is scoped to the owner's earliest workspace membership. The
    ``api_keys`` table carries no workspace column, so a key owned by a
    member of several workspaces is bound to exactly one of them; binding a
    key to a specific workspace needs a schema change.

    Returns:
        The principal, or ``None`` when no active key matches the digest.
    """
    digest = hash_api_key(raw_key)
    api_key = session.scalars(select(ApiKey).where(ApiKey.key_hash == digest)).one_or_none()
    if api_key is None or not api_key.is_active:
        return None

    workspace_id: uuid.UUID | None = None
    user_id = api_key.user_id
    if user_id is not None:
        membership = session.scalars(
            select(WorkspaceMember)
            .where(WorkspaceMember.user_id == user_id)
            .order_by(WorkspaceMember.created_at, WorkspaceMember.id)
            .limit(1)
        ).first()
        if membership is not None:
            workspace_id = membership.workspace_id

    return Principal(
        user_id=user_id,
        workspace_id=workspace_id,
        api_key_id=api_key.id,
        source="stored",
    )


def _principal_for_session_token(
    token: str,
    settings: Settings,
) -> Principal:
    """Resolve a session token to a tenant principal.

    The token is signed and stateless, so verification needs no database
    lookup. The workspace it is scoped to is the one in the token, which
    was fixed when the session was issued.

    A revoked session is refused. The revocation list lives in Redis, so a
    Redis outage means the revocation state cannot be established: the
    request is refused rather than allowed through, because a session that
    was explicitly ended must not keep working when the check cannot run.

    Raises:
        HTTPException: 401 when the token is invalid, expired, revoked or
            minted for another audience; 503 when the revocation list
            cannot be consulted.
    """
    try:
        claims = verify_session_claims(token, settings)
    except AuthStoreError as exc:
        status_code = (
            status.HTTP_503_SERVICE_UNAVAILABLE
            if "temporarily unavailable" in str(exc)
            else status.HTTP_401_UNAUTHORIZED
        )
        raise HTTPException(
            status_code=status_code,
            detail="Invalid session token.",
        ) from exc

    return Principal(
        user_id=uuid.UUID(claims.sub),
        workspace_id=uuid.UUID(claims.wid),
        api_key_id=None,
        source="session",
    )


def authenticate(
    session: SessionDep,
    settings: Annotated[Settings, Depends(get_settings)],
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> Principal:
    """Authenticate a request via the ``X-API-Key`` header or a session.

    Two credentials are accepted, and they are never combined:

    * ``X-API-Key`` — a machine credential. The configured key is the
      administrative service key; a stored key is a tenant key scoped to
      its owner's workspace.
    * ``Authorization: Bearer <session token>`` — a human session issued
      by the OAuth flow (ADR-0020). It is a tenant credential scoped to
      the workspace the session was issued for.

    A request presenting both is refused. Ambiguity about which
    credential applies is a security smell, and resolving it in favour of
    one of them would mean a client could accidentally widen its own
    access.

    Raises:
        HTTPException: 401 when no valid credential is presented, 403 when
            a valid key has no workspace to be scoped to, or when its owner
            is not an active user.
    """
    if x_api_key and authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "Present either an X-API-Key header or an Authorization header, "
                "not both."
            ),
        )

    if authorization:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Malformed Authorization header. Use 'Bearer <session token>'.",
            )
        principal = _principal_for_session_token(token.strip(), settings)
        ensure_active_user(session, principal)
        return principal

    if not x_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API key. Supply the X-API-Key header.",
        )

    if settings.api_key and x_api_key == settings.api_key:
        return _principal_for_configured_key()

    stored_principal = _principal_for_stored_key(session, x_api_key)
    if stored_principal is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key.",
        )
    principal = stored_principal

    if principal.workspace_id is None:
        # A stored key with no membership is denied, never widened: an
        # unscoped tenant principal would see every tenant's data.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=NO_MEMBERSHIP_DETAIL,
        )

    ensure_active_user(session, principal)
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


def read_scope(principal: Principal, requested: uuid.UUID | None) -> uuid.UUID | None:
    """Return the workspace a read must be restricted to.

    For a tenant principal the scope is always the principal's own
    workspace, and a ``requested`` workspace naming a different one is
    refused with ``403``. For the administrative service key the scope is
    the requested workspace, or ``None`` when none was requested -- which
    means "every workspace", and is the service key's documented
    capability.

    Raises:
        HTTPException: 403 when a tenant principal asks for another
            workspace.
    """
    if principal.is_service_key:
        return requested

    own = principal.workspace_id
    if own is None:  # pragma: no cover - authenticate() denies this case
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=NO_MEMBERSHIP_DETAIL)

    if requested is not None and requested != own:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"workspace_id {requested} is not accessible with this API key. "
                "This key is scoped to a single workspace."
            ),
        )
    return own


def write_workspace_id(principal: Principal, requested: uuid.UUID | None) -> uuid.UUID | None:
    """Return the workspace a newly created object must be filed under.

    For a tenant principal this is always the principal's own workspace: a
    ``requested`` workspace naming a different one is never honoured, so a
    tenant can never file an object inside somebody else's workspace. For
    the administrative service key the requested workspace is honoured, and
    ``None`` means "use the default workspace".
    """
    if principal.is_service_key:
        return requested

    own = principal.workspace_id
    if own is None:  # pragma: no cover - authenticate() denies this case
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=NO_MEMBERSHIP_DETAIL)
    return own


def may_read_workspace(principal: Principal, workspace_id: uuid.UUID) -> bool:
    """Return whether the principal may read objects of ``workspace_id``.

    The administrative service key may read every workspace. A tenant
    principal may read only its own.
    """
    if principal.is_service_key:
        return True
    return principal.workspace_id == workspace_id


__all__ = [
    "CurrentPrincipal",
    "NO_MEMBERSHIP_DETAIL",
    "Principal",
    "SessionDep",
    "authenticate",
    "ensure_active_user",
    "get_session",
    "hash_api_key",
    "may_read_workspace",
    "read_scope",
    "write_workspace_id",
]
