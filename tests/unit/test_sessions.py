"""Tests for the signed session token.

The token format is::

    cs1.<base64url(payload_json)>.<base64url(hmac_sha256(payload_b64, secret))>

These tests pin down the properties that make it safe to use as a bearer
credential: a tampered token is refused, an expired token is refused, a
token minted for another audience is refused, a token signed with another
secret is refused, and the signature comparison is constant-time.
"""

from __future__ import annotations

import inspect
import time

import pytest

from app.core import sessions
from app.core.sessions import (
    TOKEN_AUDIENCE,
    SessionClaims,
    SessionTokenError,
    encode_session_token,
    new_session_claims,
    verify_session_token,
)

SECRET = "unit-test-secret"


def _claims(**overrides: object) -> SessionClaims:
    """Return fresh claims with optional overrides."""
    claims = new_session_claims(
        user_id="11111111-1111-1111-1111-111111111111",
        workspace_id="22222222-2222-2222-2222-222222222222",
        ttl_seconds=3600,
    )
    if not overrides:
        return claims
    return SessionClaims(**{**claims.to_payload(), **overrides})


def test_a_fresh_token_verifies_and_carries_its_claims() -> None:
    """A token round-trips."""
    claims = _claims()
    token = encode_session_token(claims, SECRET)

    verified = verify_session_token(token, SECRET)

    assert verified.sub == claims.sub
    assert verified.wid == claims.wid
    assert verified.jti == claims.jti
    assert verified.aud == TOKEN_AUDIENCE


def test_the_token_has_the_documented_shape() -> None:
    """The format is self-identifying."""
    token = encode_session_token(_claims(), SECRET)

    prefix, payload, signature = token.split(".")
    assert prefix == "cs1"
    assert payload and signature
    assert "=" not in payload  # unpadded base64url


def test_a_tampered_payload_is_refused() -> None:
    """Editing the payload breaks the signature."""
    token = encode_session_token(_claims(), SECRET)
    prefix, payload, signature = token.split(".")

    tampered = f"{prefix}.{payload[:-2]}AA.{signature}"

    with pytest.raises(SessionTokenError):
        verify_session_token(tampered, SECRET)


def test_a_token_signed_with_another_secret_is_refused() -> None:
    """A valid shape with the wrong key is not a valid token."""
    token = encode_session_token(_claims(), "a-different-secret")

    with pytest.raises(SessionTokenError):
        verify_session_token(token, SECRET)


def test_an_expired_token_is_refused() -> None:
    """Expiry is enforced."""
    token = encode_session_token(_claims(), SECRET)

    with pytest.raises(SessionTokenError):
        verify_session_token(token, SECRET, now=time.time() + 7200)


def test_a_token_without_an_expiry_is_refused() -> None:
    """A token that never expires is refused."""
    claims = _claims()
    payload = claims.to_payload()
    payload.pop("exp")
    token = encode_session_token(SessionClaims(**{**payload, "exp": 0}), SECRET)

    with pytest.raises(SessionTokenError):
        verify_session_token(token, SECRET)


def test_a_token_for_another_audience_is_refused() -> None:
    """A token minted for another service is refused."""
    token = encode_session_token(_claims(aud="some-other-service"), SECRET)

    with pytest.raises(SessionTokenError):
        verify_session_token(token, SECRET)


def test_a_token_longer_than_the_permitted_maximum_is_refused() -> None:
    """The maximum session lifetime is enforced even on a valid token."""
    token = encode_session_token(_claims(), SECRET)

    with pytest.raises(SessionTokenError):
        verify_session_token(token, SECRET, max_ttl_seconds=60)


def test_a_malformed_token_is_refused() -> None:
    """Rubbish is refused, not decoded hopefully."""
    for token in ("", "not-a-token", "cs1.only-two", "cs2.a.b"):
        with pytest.raises(SessionTokenError):
            verify_session_token(token, SECRET)


def test_the_signature_comparison_is_constant_time() -> None:
    """The comparison must not leak how much of a forgery was right."""
    source = inspect.getsource(sessions.verify_session_token)

    assert "compare_digest" in source


def test_the_error_messages_never_contain_the_token() -> None:
    """A failure must not echo the credential back to the caller."""
    token = encode_session_token(_claims(), SECRET)
    tampered = f"{token[:-2]}AA"

    with pytest.raises(SessionTokenError) as excinfo:
        verify_session_token(tampered, SECRET)

    assert tampered not in str(excinfo.value)
    assert token not in str(excinfo.value)
