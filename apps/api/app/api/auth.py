"""Human identity: Google sign-in, one-time ticket exchange and sessions.

The flow (ADR-0020) has four steps and no shortcuts:

1. ``GET /api/v1/auth/google/start`` sends the browser to Google, with a
   signed ``state`` that is recorded server-side and bound to the
   ``redirect_uri`` the sign-in was started with.
2. ``GET /api/v1/auth/google/callback`` verifies that state, exchanges the
   authorization code, and validates the id token **against Google** before
   a single row is written. Only then is the user provisioned and a
   one-time ticket issued.
3. ``POST /api/v1/auth/exchange`` redeems that ticket - exactly once - and
   returns the session token the frontend stores in an ``HttpOnly`` cookie.
4. The session token is presented as ``Authorization: Bearer <token>`` and
   is verified by :mod:`app.core.security` as a tenant credential.

The discipline this module exists to enforce: **an unverified caller is not
a user.** A state that does not verify, an id token Google does not vouch
for, an email that is not verified, or a ticket that has already been used
all end the flow. None of them falls through to "provision the user
anyway".

A ticket, not a credential, is handed to the browser: the browser carries a
value that is worthless once redeemed, and the session token only ever
reaches the frontend server, which keeps it in an ``HttpOnly`` cookie.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import (
    AuthStore,
    AuthStoreError,
    GoogleAuthError,
    GoogleClient,
    GoogleIdentity,
    build_state,
    new_state_nonce,
    new_ticket_value,
    verify_session_claims,
    verify_state_signature,
)
from app.core.config import Settings, get_settings
from app.core.security import SessionDep
from app.core.sessions import SessionClaims, encode_session_token, new_session_claims
from app.db.enums import UserStatus, WorkspaceRole
from app.db.models.identity import User, Workspace, WorkspaceMember
from app.queue.connection import get_redis

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _auth_store() -> AuthStore:
    """Return the Redis-backed auth store."""
    return AuthStore(get_redis())


def _google_client(settings: Settings) -> GoogleClient:
    """Return the Google client."""
    return GoogleClient(settings)


def _slug_for(email: str) -> str:
    """Return a workspace slug derived from an email address.

    The slug is only a human-readable label; the workspace id is what
    scopes the data. The suffix keeps two people with the same local part
    apart without needing a lookup first.
    """
    local = email.split("@", 1)[0]
    base = "".join(char if char.isalnum() else "-" for char in local.lower()).strip("-")
    base = base or "workspace"
    return f"{base}-{uuid.uuid4().hex[:8]}"


def _provision_user(
    session: Session,
    identity: GoogleIdentity,
) -> tuple[User, Workspace]:
    """Return the user and workspace for a verified Google identity.

    The user is matched on the provider's subject id first, then on the
    email address. An email that already belongs to a *different* provider
    account is refused rather than merged: linking two identities on the
    strength of an email address is how one tenant ends up owning another
    tenant's data.

    Raises:
        HTTPException: 409 when the email belongs to another account.
    """
    user = session.scalars(
        select(User).where(User.auth_provider_id == identity.sub)
    ).one_or_none()

    if user is None:
        by_email = session.scalars(select(User).where(User.email == identity.email)).one_or_none()
        if by_email is not None:
            if by_email.auth_provider_id not in (None, identity.sub):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        "This email address is already linked to another sign-in "
                        "method. Use the original one to sign in."
                    ),
                )
            user = by_email
            user.auth_provider_id = identity.sub

    if user is None:
        user = User(
            email=identity.email,
            display_name=identity.display_name,
            auth_provider_id=identity.sub,
            status=UserStatus.ACTIVE,
        )
        session.add(user)
        session.flush()

    if identity.display_name and not user.display_name:
        user.display_name = identity.display_name

    workspace = _ensure_workspace(session, user)
    session.commit()
    return user, workspace


def _ensure_workspace(session: Session, user: User) -> Workspace:
    """Return the user's workspace, creating one if they have none."""
    membership = session.scalars(
        select(WorkspaceMember)
        .where(WorkspaceMember.user_id == user.id)
        .order_by(WorkspaceMember.created_at, WorkspaceMember.id)
        .limit(1)
    ).first()

    if membership is not None:
        workspace = session.get(Workspace, membership.workspace_id)
        if workspace is not None:
            return workspace

    workspace = Workspace(
        name=f"{user.display_name or user.email}'s workspace",
        slug=_slug_for(user.email),
        kind="tenant",
        created_by=user.id,
    )
    session.add(workspace)
    session.flush()
    session.add(
        WorkspaceMember(
            workspace_id=workspace.id,
            user_id=user.id,
            role=WorkspaceRole.OWNER,
        )
    )
    session.flush()
    return workspace


def _session_response(
    claims: SessionClaims,
    user: User,
    workspace: Workspace,
) -> dict[str, Any]:
    """Return the JSON body describing the signed-in caller."""
    return {
        "expires_at": claims.expires_at_iso(),
        "user": {
            "id": str(user.id),
            "email": user.email,
            "display_name": user.display_name,
        },
        "workspace": {
            "id": str(workspace.id),
            "name": workspace.name,
            "slug": workspace.slug,
        },
    }


def _require_session_claims(
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: Annotated[str | None, Header()] = None,
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> SessionClaims:
    """Return the verified claims of the caller's session.

    A request that presents both an API key and a session is refused: the
    same rule the API-wide authentication applies, so that a client cannot
    end up with an ambiguous identity by sending both.

    Raises:
        HTTPException: 401 when the session is missing, malformed, invalid,
            expired or revoked; 503 when the revocation list cannot be
            consulted.
    """
    if x_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "Present either an X-API-Key header or an Authorization header, "
                "not both."
            ),
        )
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing session token.",
        )

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed Authorization header. Use 'Bearer <session token>'.",
        )

    try:
        claims = verify_session_claims(token.strip(), settings, store=_auth_store())
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
    return claims


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------


@router.get("/google/start")
def google_start(
    settings: Annotated[Settings, Depends(get_settings)],
    redirect_uri: Annotated[str, Query(min_length=1)],
) -> RedirectResponse:
    """Start a Google sign-in.

    The browser is redirected to Google with a signed ``state``. The state
    is also recorded in Redis together with the ``redirect_uri`` it was
    started with, so the callback can prove that it is completing the same
    sign-in and knows where to send the browser afterwards.
    """
    if not settings.google_client_id or not settings.google_client_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google sign-in is not configured on this deployment.",
        )

    nonce = new_state_nonce()
    state = build_state(settings.auth_secret, nonce)
    store = _auth_store()
    try:
        store.put_state(
            nonce=nonce,
            state=state,
            redirect_uri=redirect_uri,
            ttl_seconds=settings.auth_state_ttl_seconds,
        )
    except Exception as exc:  # noqa: BLE001 - Redis failure must not sign anyone in
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Sign-in is temporarily unavailable.",
        ) from exc

    url = _google_client(settings).authorization_url(redirect_uri=redirect_uri, state=state)
    return RedirectResponse(url=url, status_code=status.HTTP_302_FOUND)


@router.get("/google/callback")
def google_callback(
    session: SessionDep,
    settings: Annotated[Settings, Depends(get_settings)],
    code: Annotated[str, Query(min_length=1)],
    state: Annotated[str, Query(min_length=1)],
) -> RedirectResponse:
    """Complete a Google sign-in.

    The state is verified first, then the code is exchanged, then the id
    token is validated against Google. Only after all three have succeeded
    is a user provisioned and a one-time ticket issued.
    """
    try:
        nonce = verify_state_signature(settings.auth_secret, state)
    except AuthStoreError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The sign-in request could not be verified. Start again.",
        ) from exc

    store = _auth_store()
    try:
        stored = store.consume_state(nonce=nonce)
    except Exception as exc:  # noqa: BLE001 - Redis failure must not sign anyone in
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Sign-in is temporarily unavailable.",
        ) from exc

    if stored is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The sign-in request has expired. Start again.",
        )

    client = _google_client(settings)
    try:
        id_token = client.exchange_code(code=code, redirect_uri=stored.redirect_uri)
        identity = client.validate_id_token(id_token)
    except GoogleAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Google did not confirm this sign-in.",
        ) from exc

    user, workspace = _provision_user(session, identity)

    claims = new_session_claims(
        user_id=user.id,
        workspace_id=workspace.id,
        ttl_seconds=settings.session_ttl_minutes * 60,
    )
    ticket = new_ticket_value()
    try:
        store.put_ticket(
            ticket=ticket,
            claims=claims,
            ttl_seconds=settings.auth_ticket_ttl_seconds,
        )
    except Exception as exc:  # noqa: BLE001 - Redis failure must not sign anyone in
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Sign-in is temporarily unavailable.",
        ) from exc

    separator = "&" if "?" in stored.redirect_uri else "?"
    target = f"{stored.redirect_uri}{separator}ticket={ticket}"
    return RedirectResponse(url=target, status_code=status.HTTP_302_FOUND)


class ExchangeRequest(BaseModel):
    """The body of a ticket exchange."""

    ticket: str = Field(min_length=1, max_length=512)


@router.post("/exchange")
def exchange_ticket(
    session: SessionDep,
    settings: Annotated[Settings, Depends(get_settings)],
    payload: ExchangeRequest,
) -> dict[str, Any]:
    """Redeem a one-time ticket and issue a session token.

    The ticket is consumed atomically, so it can be redeemed exactly once
    even if two requests race. A ticket that is unknown, expired or already
    used is refused.
    """
    store = _auth_store()
    try:
        claims = store.consume_ticket(ticket=payload.ticket)
    except Exception as exc:  # noqa: BLE001 - Redis failure must not issue a session
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Sign-in is temporarily unavailable.",
        ) from exc

    if claims is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="This sign-in ticket is not valid.",
        )

    user = session.get(User, uuid.UUID(claims.sub))
    workspace = session.get(Workspace, uuid.UUID(claims.wid))
    if user is None or workspace is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="This sign-in ticket is not valid.",
        )

    token = encode_session_token(claims, settings.auth_secret)
    body = _session_response(claims, user, workspace)
    body["session_token"] = token
    return body


@router.get("/me")
def current_user(
    session: SessionDep,
    claims: Annotated[SessionClaims, Depends(_require_session_claims)],
) -> dict[str, Any]:
    """Return the signed-in caller.

    The caller's identity is taken from the verified session token, never
    from the request body. A user whose account is no longer active has no
    session, however recently it was issued.
    """
    user = session.get(User, uuid.UUID(claims.sub))
    workspace = session.get(Workspace, uuid.UUID(claims.wid))
    if user is None or workspace is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid session token.",
        )
    if user.status is not UserStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is not active.",
        )

    return _session_response(claims, user, workspace)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    settings: Annotated[Settings, Depends(get_settings)],
    claims: Annotated[SessionClaims, Depends(_require_session_claims)],
) -> None:
    """End a session.

    The session token is stateless, so ending a session means recording
    its id as revoked for the rest of its lifetime.
    """
    store = _auth_store()
    try:
        store.revoke(jti=claims.jti, ttl_seconds=max(claims.exp - claims.iat, 1))
    except Exception as exc:  # noqa: BLE001 - a failed revocation must not be silent
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Sign-out is temporarily unavailable.",
        ) from exc


__all__ = ["ExchangeRequest", "router"]
