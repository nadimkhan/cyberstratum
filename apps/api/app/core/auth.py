"""Google sign-in client, one-time tickets and session revocation.

Three things live here, and they are the only pieces of server-side state a
human sign-in needs:

1. **The Google OAuth client** (:class:`GoogleClient`). It builds the
   authorization request, exchanges an authorization code for an id token, and
   validates that id token against Google's ``tokeninfo`` endpoint. The id
   token is *never* trusted on the strength of its own claims: it is checked
   against Google before a single row is written.
2. **The one-time ticket store** (:class:`AuthStore`). After a successful
   sign-in the backend hands the browser a random ticket instead of a
   credential. The ticket is redeemed exactly once, atomically, and only then
   becomes a session token.
3. **The revocation list** (:class:`AuthStore`). A session token is
   stateless, so logging out cannot delete it. Instead the token's unique
   id (``jti``) is recorded until the token would have expired anyway, and
   verification refuses a revoked id.

Every Redis key this module writes is prefixed ``cs_auth:`` so it can never
collide with the queue's own keys.

The discipline this module exists to enforce (ADR-0020): **an unverified
caller is not a user.** A failed state check, a failed token validation or a
missing email ends the flow. There is no path on which an unverified
identity produces a user row.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any, Final

import httpx

from app.core.config import Settings
from app.core.sessions import SessionClaims, b64u_encode

#: Prefix of every Redis key this module owns.
AUTH_KEY_PREFIX: Final[str] = "cs_auth:"

#: Prefix of the short-lived OAuth ``state`` records.
STATE_KEY_PREFIX: Final[str] = "cs_auth:state:"

#: Prefix of the one-time sign-in tickets.
TICKET_KEY_PREFIX: Final[str] = "cs_auth:ticket:"

#: Prefix of the revoked-session records.
REVOKED_KEY_PREFIX: Final[str] = "cs_auth:revoked:"

#: The issuers Google is allowed to sign an id token with.
GOOGLE_ISSUERS: Final[frozenset[str]] = frozenset(
    {
        "https://accounts.google.com",
        "accounts.google.com",
    }
)

#: How long the backend waits for Google before giving up. An unbounded
#: request would tie up a worker for as long as Google chose to stall.
GOOGLE_TIMEOUT_SECONDS: Final[float] = 10.0


class GoogleAuthError(Exception):
    """Google's response could not be validated.

    The message describes what was wrong with the *response*, never the
    id token itself, so it is safe to log and to return.
    """


class AuthStoreError(Exception):
    """The one-time ticket or the state record could not be used."""


@dataclass(frozen=True, slots=True)
class GoogleIdentity:
    """A verified Google identity.

    Every field here has been checked against Google's ``tokeninfo``
    endpoint. An instance of this class is the only thing that may cause a
    user to be provisioned.
    """

    sub: str
    email: str
    display_name: str | None
    email_verified: bool


@dataclass(frozen=True, slots=True)
class StoredState:
    """The OAuth ``state`` recorded when a sign-in was started."""

    redirect_uri: str


def _b64u_hmac(secret: str, message: str) -> str:
    """Return the base64url HMAC-SHA256 of ``message`` under ``secret``."""
    mac = hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256)
    return b64u_encode(mac.digest())


def build_state(secret: str, nonce: str) -> str:
    """Return the signed ``state`` value for an OAuth round trip.

    The state is ``<nonce>.<signature>``: the nonce is unpredictable, and
    the signature proves the state was issued by this backend. The nonce
    alone identifies the Redis record, which carries the binding to the
    ``redirect_uri`` the sign-in was started with.
    """
    return f"{nonce}.{_b64u_hmac(secret, nonce)}"


def verify_state_signature(secret: str, state: str) -> str:
    """Return the nonce of a signed ``state``, or raise.

    Raises:
        AuthStoreError: when the state is malformed or not authentic.
    """
    nonce, _, signature = state.partition(".")
    if not nonce or not signature:
        raise AuthStoreError("OAuth state is malformed.")
    expected = _b64u_hmac(secret, nonce)
    if not hmac.compare_digest(expected, signature):
        raise AuthStoreError("OAuth state signature is not valid.")
    return nonce


class GoogleClient:
    """The Google OpenID Connect client.

    The server is a *confidential* client: it holds a client secret and
    exchanges the authorization code itself, so no PKCE challenge is needed
    on this side. The client secret is never sent to the browser and never
    written to a log.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout: float = GOOGLE_TIMEOUT_SECONDS,
    ) -> None:
        self._settings = settings
        self._transport = transport
        self._timeout = timeout

    def _client(self) -> httpx.Client:
        """Return a short-lived HTTP client with an explicit timeout."""
        return httpx.Client(transport=self._transport, timeout=self._timeout)

    def authorization_url(self, *, redirect_uri: str, state: str) -> str:
        """Return the Google authorization URL the browser is sent to."""
        from urllib.parse import urlencode

        params = {
            "client_id": self._settings.google_client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "access_type": "offline",
        }
        return f"{self._settings.google_auth_endpoint}?{urlencode(params)}"

    def exchange_code(self, *, code: str, redirect_uri: str) -> str:
        """Exchange an authorization code for Google's id token.

        Raises:
            GoogleAuthError: when Google refuses the exchange.
        """
        payload = {
            "code": code,
            "client_id": self._settings.google_client_id,
            "client_secret": self._settings.google_client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }
        try:
            with self._client() as client:
                response = client.post(self._settings.google_token_endpoint, data=payload)
        except httpx.HTTPError as exc:
            raise GoogleAuthError("Could not reach the Google token endpoint.") from exc

        if response.status_code != 200:
            raise GoogleAuthError("Google refused the authorization code.")
        try:
            body = response.json()
        except ValueError as exc:
            raise GoogleAuthError("Google returned a malformed token response.") from exc
        id_token = body.get("id_token") if isinstance(body, dict) else None
        if not isinstance(id_token, str) or not id_token:
            raise GoogleAuthError("Google returned no id token.")
        return id_token

    def validate_id_token(self, id_token: str) -> GoogleIdentity:
        """Validate an id token against Google's ``tokeninfo`` endpoint.

        The token's own claims are not trusted: the endpoint is asked
        whether Google vouches for it, and only then are the audience, the
        issuer, the email, the email verification and the expiry checked.

        Raises:
            GoogleAuthError: when the token is not valid for this client.
        """
        try:
            with self._client() as client:
                response = client.get(
                    self._settings.google_tokeninfo_endpoint,
                    params={"id_token": id_token},
                )
        except httpx.HTTPError as exc:
            raise GoogleAuthError("Could not reach the Google tokeninfo endpoint.") from exc

        if response.status_code != 200:
            raise GoogleAuthError("Google did not validate the id token.")
        try:
            body = response.json()
        except ValueError as exc:
            raise GoogleAuthError("Google returned a malformed tokeninfo response.") from exc
        if not isinstance(body, dict):
            raise GoogleAuthError("Google returned a malformed tokeninfo response.")

        return self._identity_from_claims(body)

    def _identity_from_claims(self, claims: dict[str, Any]) -> GoogleIdentity:
        """Turn validated ``tokeninfo`` claims into an identity.

        Raises:
            GoogleAuthError: when any of the required properties is wrong.
        """
        audience = claims.get("aud")
        if not isinstance(audience, str) or audience != self._settings.google_client_id:
            raise GoogleAuthError("The id token was issued for a different client.")

        issuer = claims.get("iss")
        if not isinstance(issuer, str) or issuer not in GOOGLE_ISSUERS:
            raise GoogleAuthError("The id token was issued by an unknown issuer.")

        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject:
            raise GoogleAuthError("The id token carries no subject.")

        email = claims.get("email")
        if not isinstance(email, str) or not email.strip():
            raise GoogleAuthError("The id token carries no email address.")

        if not _is_email_verified(claims.get("email_verified")):
            raise GoogleAuthError("The email address is not verified.")

        expiry = claims.get("exp")
        if not isinstance(expiry, (int, float)) or expiry <= time.time():
            raise GoogleAuthError("The id token has expired.")

        name = claims.get("name")
        display_name = name.strip() if isinstance(name, str) and name.strip() else None

        return GoogleIdentity(
            sub=subject,
            email=email.strip().lower(),
            display_name=display_name,
            email_verified=True,
        )


def _is_email_verified(value: Any) -> bool:
    """Return whether a ``tokeninfo`` ``email_verified`` value is true.

    Google returns a boolean, but the field has also been observed as the
    string ``"true"``; both are accepted, everything else is not.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() == "true"
    return False


class AuthStore:
    """The Redis-backed state, ticket and revocation store.

    Only a small, explicit slice of the Redis API is used, which keeps the
    store testable with an in-memory fake and keeps the blast radius of this
    module inside the ``cs_auth:`` key prefix.
    """

    def __init__(self, client: Any) -> None:
        self._client = client

    # -- OAuth state ----------------------------------------------------

    def put_state(self, *, nonce: str, state: str, redirect_uri: str, ttl_seconds: int) -> None:
        """Record the state of a sign-in that is about to start."""
        payload = json.dumps({"state": state, "redirect_uri": redirect_uri})
        self._client.set(f"{STATE_KEY_PREFIX}{nonce}", payload, ex=int(ttl_seconds))

    def consume_state(self, *, nonce: str) -> StoredState | None:
        """Consume a state record and return what it was bound to.

        Returns ``None`` when the record is unknown or has expired. The
        record is deleted on read, so a state can be used only once.
        """
        key = f"{STATE_KEY_PREFIX}{nonce}"
        raw = self._client.getdel(key)
        if raw is None:
            return None
        try:
            body = json.loads(raw)
        except (TypeError, ValueError):
            return None
        if not isinstance(body, dict):
            return None
        redirect_uri = body.get("redirect_uri")
        if not isinstance(redirect_uri, str) or not redirect_uri:
            return None
        return StoredState(redirect_uri=redirect_uri)

    # -- one-time tickets ------------------------------------------------

    def put_ticket(self, *, ticket: str, claims: SessionClaims, ttl_seconds: int) -> None:
        """Store a one-time ticket carrying the session payload."""
        self._client.set(
            f"{TICKET_KEY_PREFIX}{ticket}",
            json.dumps(claims.to_payload()),
            ex=int(ttl_seconds),
        )

    def consume_ticket(self, *, ticket: str) -> SessionClaims | None:
        """Consume a ticket and return the session payload it carried.

        The read and the delete are a single atomic operation, so a ticket
        can be redeemed exactly once even when two requests race.
        """
        raw = self._client.getdel(f"{TICKET_KEY_PREFIX}{ticket}")
        if raw is None:
            return None
        try:
            body = json.loads(raw)
        except (TypeError, ValueError):
            return None
        if not isinstance(body, dict):
            return None
        try:
            return SessionClaims.from_payload(body)
        except Exception:  # noqa: BLE001 - a corrupt payload is simply unusable
            return None

    # -- revocation ------------------------------------------------------

    def revoke(self, *, jti: str, ttl_seconds: int) -> None:
        """Record a session id as revoked for the rest of its lifetime."""
        self._client.set(f"{REVOKED_KEY_PREFIX}{jti}", "1", ex=int(max(ttl_seconds, 1)))

    def is_revoked(self, *, jti: str) -> bool:
        """Return whether a session id has been revoked."""
        return bool(self._client.exists(f"{REVOKED_KEY_PREFIX}{jti}"))


def new_ticket_value() -> str:
    """Return a fresh, unpredictable one-time ticket.

    The ticket carries 256 bits of entropy and is a bearer credential in
    its own right, so it is generated with the cryptographic RNG and never
    derived from anything guessable.
    """
    return secrets.token_urlsafe(32)


def _default_store() -> AuthStore:
    """Return the store backed by the application's Redis."""
    from app.queue.connection import get_redis

    return AuthStore(get_redis())


def verify_session_claims(
    token: str,
    settings: Settings,
    *,
    store: AuthStore | None = None,
) -> SessionClaims:
    """Verify a session token and confirm that it has not been revoked.

    The signature and the expiry are checked by the stateless verifier; the
    revocation list is the one piece of server-side state a session has,
    because a stateless token cannot delete itself.

    Raises:
        AuthStoreError: when the token is invalid, expired, minted for
            another audience, or has been revoked. The message never
            contains the token.
    """
    from app.core.sessions import SessionTokenError, verify_session_token

    try:
        claims = verify_session_token(
            token,
            settings.auth_secret,
            max_ttl_seconds=settings.session_ttl_minutes * 60,
        )
    except SessionTokenError as exc:
        raise AuthStoreError("Session token is not valid.") from exc

    active_store = store if store is not None else _default_store()
    try:
        revoked = active_store.is_revoked(jti=claims.jti)
    except Exception as exc:  # noqa: BLE001 - an unreachable store is a refusal
        raise AuthStoreError("Session verification is temporarily unavailable.") from exc
    if revoked:
        raise AuthStoreError("Session has been revoked.")
    return claims


def new_state_nonce() -> str:
    """Return a fresh, unpredictable OAuth state nonce."""
    return secrets.token_urlsafe(32)


__all__ = [
    "AUTH_KEY_PREFIX",
    "GOOGLE_ISSUERS",
    "GOOGLE_TIMEOUT_SECONDS",
    "REVOKED_KEY_PREFIX",
    "STATE_KEY_PREFIX",
    "TICKET_KEY_PREFIX",
    "AuthStore",
    "AuthStoreError",
    "GoogleAuthError",
    "GoogleClient",
    "GoogleIdentity",
    "StoredState",
    "build_state",
    "new_state_nonce",
    "new_ticket_value",
    "verify_session_claims",
    "verify_state_signature",
]
