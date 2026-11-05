"""Stateless, signed session tokens for human callers.

A session token is a compact, self-describing bearer credential::

    cs1.<base64url(payload_json)>.<base64url(hmac_sha256(payload_b64, AUTH_SECRET))>

The payload is JSON::

    {"sub": "<user uuid>", "wid": "<workspace uuid>", "jti": "<random>",
     "iat": <epoch>, "exp": <epoch>, "aud": "cyberstratum-api"}

The token is *stateless*: nothing about it is stored server-side, so any
process holding ``AUTH_SECRET`` can verify it without a database or a cache
lookup. The one piece of server-side state that does exist is the revocation
list (see :mod:`app.core.auth`), which is consulted only to *deny* a token
that was explicitly logged out.

Security properties this module is responsible for:

* **The signature is checked with a constant-time comparison.** A byte-wise
  comparison would leak, through its timing, how many leading characters of
  a forged signature were correct. ``hmac.compare_digest`` is used instead.
* **Every failure mode is a rejection.** A bad signature, a token for
  another audience, an expired token and a token with no ``exp`` are all
  refused. There is no "trust it anyway" path.
* **The token is never echoed.** The error messages in this module describe
  *what* was wrong, never *what* was presented, so a token cannot leak into
  a log, an error body or a traceback through this module.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import time
import uuid
from dataclasses import dataclass
from typing import Any, Final

#: The version prefix of every session token. It makes the format
#: self-identifying, so a future format can coexist with this one.
TOKEN_PREFIX: Final[str] = "cs1"  # noqa: S105 - a format prefix, not a secret

#: The audience this API accepts. A token minted for another service is
#: refused even if it carries a valid signature.
TOKEN_AUDIENCE: Final[str] = "cyberstratum-api"  # noqa: S105 - a public identifier


class SessionTokenError(Exception):
    """A session token was missing, malformed, expired or not authentic.

    The message never contains the token itself, so it is safe to return to
    a caller and to log.
    """


@dataclass(frozen=True, slots=True)
class SessionClaims:
    """The verified contents of a session token.

    Attributes:
        sub: The user id the session belongs to.
        wid: The workspace the session is scoped to.
        jti: The unique id of this session, used to revoke it.
        iat: When the session was issued (epoch seconds).
        exp: When the session expires (epoch seconds).
        aud: The audience the token was minted for.
    """

    sub: str
    wid: str
    jti: str
    iat: int
    exp: int
    aud: str = TOKEN_AUDIENCE

    def to_payload(self) -> dict[str, Any]:
        """Return the JSON-serialisable payload of this session."""
        return {
            "sub": self.sub,
            "wid": self.wid,
            "jti": self.jti,
            "iat": self.iat,
            "exp": self.exp,
            "aud": self.aud,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> SessionClaims:
        """Build claims from a decoded payload.

        Raises:
            SessionTokenError: when a required field is missing or has the
                wrong type.
        """
        try:
            sub = str(payload["sub"])
            wid = str(payload["wid"])
            jti = str(payload["jti"])
            iat = int(payload["iat"])
            exp = int(payload["exp"])
            aud = str(payload["aud"])
        except (KeyError, TypeError, ValueError) as exc:
            raise SessionTokenError("Session token payload is malformed.") from exc
        return cls(sub=sub, wid=wid, jti=jti, iat=iat, exp=exp, aud=aud)

    def expires_at_iso(self) -> str:
        """Return the expiry as an ISO-8601 UTC timestamp."""
        from datetime import UTC, datetime

        return datetime.fromtimestamp(self.exp, tz=UTC).isoformat()


def b64u_encode(raw: bytes) -> str:
    """Encode bytes as unpadded base64url."""
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def b64u_decode(value: str) -> bytes:
    """Decode unpadded base64url.

    Raises:
        SessionTokenError: when the value is not valid base64url.
    """
    padding = "=" * (-len(value) % 4)
    try:
        return base64.urlsafe_b64decode(value + padding)
    except (binascii.Error, ValueError) as exc:
        raise SessionTokenError("Session token encoding is malformed.") from exc


def sign_payload(payload_b64: str, secret: str) -> str:
    """Return the base64url HMAC-SHA256 signature of a base64url payload."""
    mac = hmac.new(secret.encode("utf-8"), payload_b64.encode("ascii"), hashlib.sha256)
    return b64u_encode(mac.digest())


def encode_session_token(claims: SessionClaims, secret: str) -> str:
    """Sign ``claims`` into a session token.

    Args:
        claims: The session contents to encode.
        secret: The signing secret (``AUTH_SECRET``).

    Returns:
        The token, in the documented ``cs1.<payload>.<signature>`` format.
    """
    payload_json = json.dumps(claims.to_payload(), separators=(",", ":"), sort_keys=True)
    payload_b64 = b64u_encode(payload_json.encode("utf-8"))
    signature = sign_payload(payload_b64, secret)
    return f"{TOKEN_PREFIX}.{payload_b64}.{signature}"


def verify_session_token(
    token: str,
    secret: str,
    *,
    now: float | None = None,
    max_ttl_seconds: int | None = None,
) -> SessionClaims:
    """Verify a session token and return its claims.

    Args:
        token: The token presented by the caller.
        secret: The signing secret (``AUTH_SECRET``).
        now: The current time, for tests. Defaults to the wall clock.
        max_ttl_seconds: When given, a token whose lifetime exceeds this
            bound is refused. This keeps the *maximum* possible session
            lifetime tied to the configured token TTL even if a token was
            minted elsewhere.

    Raises:
        SessionTokenError: when the token is missing, malformed, not
            authentic, minted for another audience, expired, or claims a
            lifetime beyond ``max_ttl_seconds``.
    """
    if not token:
        raise SessionTokenError("Session token is missing.")

    parts = token.split(".")
    if len(parts) != 3:
        raise SessionTokenError("Session token is malformed.")
    prefix, payload_b64, signature = parts
    if prefix != TOKEN_PREFIX:
        raise SessionTokenError("Session token format is not supported.")

    expected = sign_payload(payload_b64, secret)
    # Constant-time: a byte-wise comparison would leak how much of a
    # forged signature was correct.
    if not hmac.compare_digest(expected, signature):
        raise SessionTokenError("Session token signature is not valid.")

    try:
        decoded = json.loads(b64u_decode(payload_b64).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SessionTokenError("Session token payload is malformed.") from exc
    if not isinstance(decoded, dict):
        raise SessionTokenError("Session token payload is malformed.")

    claims = SessionClaims.from_payload(decoded)

    if claims.aud != TOKEN_AUDIENCE:
        raise SessionTokenError("Session token audience is not valid.")

    current = time.time() if now is None else now
    if claims.exp <= current:
        raise SessionTokenError("Session token has expired.")

    if max_ttl_seconds is not None and claims.exp - claims.iat > max_ttl_seconds:
        raise SessionTokenError("Session token lifetime exceeds the permitted maximum.")

    return claims


def new_session_claims(
    *,
    user_id: uuid.UUID | str,
    workspace_id: uuid.UUID | str,
    ttl_seconds: int,
    now: float | None = None,
) -> SessionClaims:
    """Create fresh claims for a new session.

    Args:
        user_id: The user the session belongs to.
        workspace_id: The workspace the session is scoped to.
        ttl_seconds: How long the session is valid for.
        now: The current time, for tests. Defaults to the wall clock.
    """
    issued = int(time.time() if now is None else now)
    return SessionClaims(
        sub=str(user_id),
        wid=str(workspace_id),
        jti=uuid.uuid4().hex,
        iat=issued,
        exp=issued + int(ttl_seconds),
        aud=TOKEN_AUDIENCE,
    )


__all__ = [
    "TOKEN_AUDIENCE",
    "TOKEN_PREFIX",
    "SessionClaims",
    "SessionTokenError",
    "b64u_decode",
    "b64u_encode",
    "encode_session_token",
    "new_session_claims",
    "sign_payload",
    "verify_session_token",
]
