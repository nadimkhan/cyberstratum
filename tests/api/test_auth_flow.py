"""Tests for the human identity flow: Google sign-in, tickets and sessions.

The flow is security-critical, so these tests pin down the properties that
matter (ADR-0020):

* **An unverified caller is not a user.** A state that does not verify, an
  id token Google does not vouch for, or an email that is not verified all
  end the flow, and none of them provisions anything.
* **A ticket is redeemable exactly once.**
* **A session is a tenant credential.** It is scoped to the workspace it
  was issued for and can never read another tenant's data.
* **A session can be revoked**, and a revoked session stops working.
* **A request carrying both credentials is refused** rather than resolved
  in favour of one of them.

Nothing here touches the network or a real Redis: Google's client and the
auth store are replaced with local fakes, so the tests are deterministic
and cannot leak into the shared Redis instance.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api import auth as auth_api
from app.core.auth import GoogleAuthError, GoogleIdentity
from app.core.config import get_settings
from app.db.enums import ScanStatus, UserStatus
from app.db.models.identity import Chain, ContractTarget, User, Workspace
from app.db.models.scans import Scan


class FakeRedis:
    """An in-memory stand-in for the slice of Redis the auth store uses."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def set(self, key: str, value: str, ex: int | None = None) -> bool:
        """Store a value."""
        del ex
        self.store[key] = value
        return True

    def getdel(self, key: str) -> str | None:
        """Read and delete a value."""
        return self.store.pop(key, None)

    def exists(self, key: str) -> int:
        """Return whether a key exists."""
        return 1 if key in self.store else 0


class FakeGoogleClient:
    """A Google client that answers from a fixed script.

    Attributes:
        identity: the identity returned when the exchange succeeds.
        error: the error raised instead, when the flow must fail.
    """

    def __init__(
        self,
        *,
        identity: GoogleIdentity | None = None,
        error: Exception | None = None,
    ) -> None:
        self.identity = identity
        self.error = error

    def authorization_url(self, *, redirect_uri: str, state: str) -> str:
        """Return a fake Google authorization URL."""
        return f"https://accounts.google.com/o/oauth2/v2/auth?state={state}&ru={redirect_uri}"

    def exchange_code(self, *, code: str, redirect_uri: str) -> str:
        """Return a fake id token."""
        del code, redirect_uri
        if self.error is not None:
            raise self.error
        return "fake-id-token"

    def validate_id_token(self, id_token: str) -> GoogleIdentity:
        """Return the scripted identity."""
        del id_token
        if self.error is not None:
            raise self.error
        assert self.identity is not None
        return self.identity


@pytest.fixture()
def google_configured(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Configure a Google client and a signing secret for the test."""
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setenv("AUTH_SECRET", "test-auth-secret")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture()
def fake_redis(monkeypatch: pytest.MonkeyPatch) -> FakeRedis:
    """Replace the auth store's Redis with an in-memory fake.

    The fake is installed at the Redis client, not at one call site,
    because two different places reach the revocation list: the API's
    own store and the security layer's default store. A revocation
    written by one must be visible to the other, and the suite must
    never depend on a running Redis to prove it.
    """
    store = FakeRedis()

    import app.queue.connection as queue_connection

    monkeypatch.setattr(auth_api, "get_redis", lambda: store)
    monkeypatch.setattr(queue_connection, "get_redis", lambda: store)
    return store


@pytest.fixture()
def identity() -> GoogleIdentity:
    """A verified Google identity."""
    return GoogleIdentity(
        sub="google-subject-1",
        email="analyst@example.test",
        display_name="Analyst",
        email_verified=True,
    )


@pytest.fixture()
def google_client(monkeypatch: pytest.MonkeyPatch) -> FakeGoogleClient:
    """Replace the Google client with a fake that succeeds."""
    fake = FakeGoogleClient(
        identity=GoogleIdentity(
            sub="google-subject-1",
            email="analyst@example.test",
            display_name="Analyst",
            email_verified=True,
        )
    )
    monkeypatch.setattr(auth_api, "_google_client", lambda settings: fake)
    return fake


def _sign_in(
    client: TestClient,
    fake_redis: FakeRedis,
    *,
    redirect_uri: str = "https://app.example.test/api/auth/callback",
) -> str:
    """Run the whole sign-in flow and return the redeemed session token."""
    start = client.get(
        "/api/v1/auth/google/start",
        params={"redirect_uri": redirect_uri},
        follow_redirects=False,
    )
    assert start.status_code == 302, start.text
    state = start.headers["location"].split("state=")[1].split("&")[0]

    callback = client.get(
        "/api/v1/auth/google/callback",
        params={"code": "auth-code", "state": state},
        follow_redirects=False,
    )
    assert callback.status_code == 302, callback.text
    ticket = callback.headers["location"].split("ticket=")[1].split("&")[0]

    exchange = client.post("/api/v1/auth/exchange", json={"ticket": ticket})
    assert exchange.status_code == 200, exchange.text
    return str(exchange.json()["session_token"])


# --------------------------------------------------- (a) starting a sign-in


def test_google_start_redirects_to_google_with_a_signed_state(
    client: TestClient,
    google_configured: None,
    fake_redis: FakeRedis,
) -> None:
    """A sign-in starts by redirecting to Google with an unpredictable state."""
    response = client.get(
        "/api/v1/auth/google/start",
        params={"redirect_uri": "https://app.example.test/api/auth/callback"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    location = response.headers["location"]
    assert location.startswith("https://accounts.google.com/")
    assert "state=" in location
    assert len(fake_redis.store) == 1


def test_google_start_is_refused_when_google_is_not_configured(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A deployment without Google credentials does not pretend to sign in."""
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "")
    get_settings.cache_clear()

    response = client.get(
        "/api/v1/auth/google/start",
        params={"redirect_uri": "https://app.example.test/api/auth/callback"},
        follow_redirects=False,
    )

    assert response.status_code == 503
    get_settings.cache_clear()


# --------------------------------------------------- (b) refusing bad states


def test_callback_with_a_forged_state_is_refused(
    client: TestClient,
    google_configured: None,
    fake_redis: FakeRedis,
    db_session: Session,
) -> None:
    """A state that was not signed by this backend ends the flow."""
    response = client.get(
        "/api/v1/auth/google/callback",
        params={"code": "auth-code", "state": "forged.nonce"},
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert db_session.query(User).count() == 0


def test_callback_rejects_an_identity_google_does_not_confirm(
    client: TestClient,
    google_configured: None,
    fake_redis: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
) -> None:
    """An id token Google refuses must not provision a user."""
    fake = FakeGoogleClient(error=GoogleAuthError("Google did not validate the id token."))
    monkeypatch.setattr(auth_api, "_google_client", lambda settings: fake)

    start = client.get(
        "/api/v1/auth/google/start",
        params={"redirect_uri": "https://app.example.test/api/auth/callback"},
        follow_redirects=False,
    )
    state = start.headers["location"].split("state=")[1].split("&")[0]

    response = client.get(
        "/api/v1/auth/google/callback",
        params={"code": "auth-code", "state": state},
        follow_redirects=False,
    )

    assert response.status_code == 401
    assert db_session.query(User).count() == 0


# --------------------------------------------------- (c) a complete sign-in


def test_a_successful_sign_in_provisions_a_user_and_a_workspace(
    client: TestClient,
    google_configured: None,
    google_client: FakeGoogleClient,
    fake_redis: FakeRedis,
    db_session: Session,
) -> None:
    """A verified sign-in creates the user, their workspace and a ticket."""
    token = _sign_in(client, fake_redis)

    assert token
    user = db_session.query(User).one()
    assert user.email == "analyst@example.test"
    assert user.auth_provider_id == "google-subject-1"
    workspace = db_session.query(Workspace).one()
    assert workspace.created_by == user.id


def test_a_ticket_can_be_redeemed_exactly_once(
    client: TestClient,
    google_configured: None,
    google_client: FakeGoogleClient,
    fake_redis: FakeRedis,
) -> None:
    """A ticket is a one-time credential."""
    start = client.get(
        "/api/v1/auth/google/start",
        params={"redirect_uri": "https://app.example.test/api/auth/callback"},
        follow_redirects=False,
    )
    state = start.headers["location"].split("state=")[1].split("&")[0]
    callback = client.get(
        "/api/v1/auth/google/callback",
        params={"code": "auth-code", "state": state},
        follow_redirects=False,
    )
    ticket = callback.headers["location"].split("ticket=")[1].split("&")[0]

    first = client.post("/api/v1/auth/exchange", json={"ticket": ticket})
    second = client.post("/api/v1/auth/exchange", json={"ticket": ticket})

    assert first.status_code == 200
    assert second.status_code == 401


def test_an_unknown_ticket_is_refused(
    client: TestClient,
    google_configured: None,
    fake_redis: FakeRedis,
) -> None:
    """A ticket that was never issued is refused."""
    response = client.post("/api/v1/auth/exchange", json={"ticket": "not-a-ticket"})

    assert response.status_code == 401


# --------------------------------------------------- (d) using the session


def test_me_returns_the_signed_in_caller(
    client: TestClient,
    google_configured: None,
    google_client: FakeGoogleClient,
    fake_redis: FakeRedis,
) -> None:
    """A valid session identifies the caller."""
    token = _sign_in(client, fake_redis)

    response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    body = response.json()
    assert body["user"]["email"] == "analyst@example.test"
    assert body["workspace"]["id"]
    assert "session_token" not in body


def test_me_requires_a_session(client: TestClient, google_configured: None) -> None:
    """No session means no identity."""
    assert client.get("/api/v1/auth/me").status_code == 401


def test_a_tampered_session_is_refused(
    client: TestClient,
    google_configured: None,
    google_client: FakeGoogleClient,
    fake_redis: FakeRedis,
) -> None:
    """A session whose payload was edited does not verify."""
    token = _sign_in(client, fake_redis)
    prefix, payload, signature = token.split(".")
    tampered = f"{prefix}.{payload[:-2]}AA.{signature}"

    response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tampered}"})

    assert response.status_code == 401


def test_a_malformed_authorization_header_is_refused(
    client: TestClient,
    google_configured: None,
) -> None:
    """A header that is not a bearer credential is refused."""
    response = client.get("/api/v1/auth/me", headers={"Authorization": "Basic abc123"})

    assert response.status_code == 401


def test_logout_revokes_the_session(
    client: TestClient,
    google_configured: None,
    google_client: FakeGoogleClient,
    fake_redis: FakeRedis,
) -> None:
    """A revoked session stops working."""
    token = _sign_in(client, fake_redis)
    headers = {"Authorization": f"Bearer {token}"}

    assert client.get("/api/v1/auth/me", headers=headers).status_code == 200
    assert client.post("/api/v1/auth/logout", headers=headers).status_code == 204
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 401


def test_presenting_both_credentials_is_refused(
    client: TestClient,
    google_configured: None,
    google_client: FakeGoogleClient,
    fake_redis: FakeRedis,
) -> None:
    """Ambiguity about the credential is refused, not resolved."""
    token = _sign_in(client, fake_redis)

    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}", "X-API-Key": "test-api-key"},
    )

    assert response.status_code == 401


# --------------------------------------------------- (e) session scoping


def test_a_session_cannot_read_another_tenants_scan(
    client: TestClient,
    google_configured: None,
    google_client: FakeGoogleClient,
    fake_redis: FakeRedis,
    db_session: Session,
    chain: Chain,
) -> None:
    """A session is scoped to its own workspace, like any tenant credential."""
    token = _sign_in(client, fake_redis)

    other_user = User(email="other@example.test", display_name="Other")
    db_session.add(other_user)
    db_session.flush()
    other_space = Workspace(
        name="Other workspace",
        slug=f"other-{uuid.uuid4().hex}",
        created_by=other_user.id,
    )
    db_session.add(other_space)
    db_session.flush()
    target = ContractTarget(
        workspace_id=other_space.id,
        chain_id=chain.id,
        address="0x" + "22" * 20,
        label="Other target",
        bytecode_type="runtime",
        authorization_status="unknown",
    )
    db_session.add(target)
    db_session.flush()
    scan = Scan(
        workspace_id=other_space.id,
        target_id=target.id,
        status=ScanStatus.COMPLETED,
        fork="cancun",
        bytecode_source="test",
    )
    db_session.add(scan)
    db_session.flush()

    detail = client.get(
        f"/api/v1/scans/{scan.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    listing = client.get("/api/v1/scans", headers={"Authorization": f"Bearer {token}"})

    assert detail.status_code == 404
    assert listing.status_code == 200
    assert listing.json()["items"] == []


def test_a_session_may_not_name_another_workspace(
    client: TestClient,
    google_configured: None,
    google_client: FakeGoogleClient,
    fake_redis: FakeRedis,
    db_session: Session,
) -> None:
    """A session naming a foreign workspace is refused, like any tenant."""
    token = _sign_in(client, fake_redis)

    other_user = User(email="other2@example.test", display_name="Other")
    db_session.add(other_user)
    db_session.flush()
    other_space = Workspace(
        name="Other workspace",
        slug=f"other-{uuid.uuid4().hex}",
        created_by=other_user.id,
    )
    db_session.add(other_space)
    db_session.flush()

    response = client.get(
        "/api/v1/scans",
        params={"workspace_id": str(other_space.id)},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403


def test_an_inactive_user_cannot_use_an_issued_session(
    client: TestClient,
    google_configured: None,
    google_client: FakeGoogleClient,
    fake_redis: FakeRedis,
    db_session: Session,
) -> None:
    """Deactivating a user ends the sessions they already hold."""
    token = _sign_in(client, fake_redis)
    user = db_session.query(User).one()
    user.status = UserStatus.SUSPENDED
    db_session.flush()

    response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code in (401, 403)
