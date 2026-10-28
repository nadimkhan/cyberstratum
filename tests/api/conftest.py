"""Shared pytest fixtures for the API test suite.

The tests run against the dedicated ``cyberstratum_test`` database, selected
through the ``TEST_DATABASE_URL`` environment variable. The RQ enqueue call is
replaced by a recording stub so the suite never depends on a running worker.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.db.base import Base
from app.db.enums import WorkspaceRole
from app.db.models.identity import Chain, ContractTarget, User, Workspace, WorkspaceMember

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _test_database_url() -> str:
    """Resolve the test database URL without hard-coding credentials.

    The value comes from the ``TEST_DATABASE_URL`` environment variable, or
    from the same key in the repository ``.env`` file.
    """
    from_url = os.environ.get("TEST_DATABASE_URL")
    if from_url:
        return from_url

    env_file = os.path.join(REPO_ROOT, ".env")
    if os.path.exists(env_file):
        with open(env_file, encoding="utf-8") as handle:
            for line in handle:
                key, _, value = line.partition("=")
                if key.strip() == "TEST_DATABASE_URL":
                    return value.strip()
    raise RuntimeError(
        "TEST_DATABASE_URL is not set. Add it to the environment or to the "
        "repository .env file before running the test suite."
    )


@pytest.fixture(scope="session", autouse=True)
def _configure_test_env() -> Iterator[None]:
    """Point the application at the test database for the whole session."""
    os.environ["APP_ENV"] = "test"
    os.environ["DATABASE_URL"] = _test_database_url()
    os.environ["TEST_DATABASE_URL"] = _test_database_url()
    os.environ["API_KEY"] = "test-api-key"
    os.environ["OBJECT_STORAGE_ROOT"] = os.path.join(REPO_ROOT, "var", "test-artifacts")

    get_settings.cache_clear()

    from app.db import session as db_session

    db_session.reset_engine()
    yield
    db_session.reset_engine()
    get_settings.cache_clear()


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    """Provide a session-scoped engine bound to the test database."""
    from app.db import session as db_session

    eng = db_session.get_engine()
    Base.metadata.drop_all(bind=eng)
    Base.metadata.create_all(bind=eng)
    yield eng
    eng.dispose()


@pytest.fixture()
def connection(engine: Engine) -> Iterator[Any]:
    """Provide a connection wrapped in a transaction rolled back after the test."""
    conn = engine.connect()
    transaction = conn.begin()
    try:
        yield conn
    finally:
        transaction.rollback()
        conn.close()


@pytest.fixture()
def db_session(connection: Any) -> Iterator[Session]:
    """Provide a session bound to the test transaction."""
    factory = sessionmaker(bind=connection, autoflush=False, expire_on_commit=False)
    session = factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(connection: Any) -> Iterator[TestClient]:
    """Provide a TestClient whose sessions share the test transaction."""
    from app.core.security import get_session as get_db_session
    from app.main import app

    def override_session() -> Iterator[Session]:
        factory = sessionmaker(bind=connection, autoflush=False, expire_on_commit=False)
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db_session] = override_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture()
def api_headers() -> dict[str, str]:
    """Headers for an authenticated request."""
    return {"X-API-Key": "test-api-key"}


@pytest.fixture()
def workspace(db_session: Session) -> Workspace:
    """Create a workspace with one member."""
    user = User(email=f"user-{uuid.uuid4().hex}@example.test", display_name="Test User")
    db_session.add(user)
    db_session.flush()

    space = Workspace(name="Test workspace", slug=f"test-{uuid.uuid4().hex}", created_by=user.id)
    db_session.add(space)
    db_session.flush()

    db_session.add(
        WorkspaceMember(workspace_id=space.id, user_id=user.id, role=WorkspaceRole.RESEARCHER)
    )
    db_session.flush()
    return space


@pytest.fixture()
def chain(db_session: Session) -> Chain:
    """Return the chain row for chain id 1, creating it when absent."""
    existing = db_session.query(Chain).filter(Chain.chain_id == 1).one_or_none()
    if existing is not None:
        return existing
    row = Chain(name="Ethereum", chain_id=1, environment="mainnet")
    db_session.add(row)
    db_session.flush()
    return row


@pytest.fixture()
def target(db_session: Session, workspace: Workspace, chain: Chain) -> ContractTarget:
    """Create a contract target with a known address."""
    row = ContractTarget(
        workspace_id=workspace.id,
        chain_id=chain.id,
        address="0x" + "11" * 20,
        label="Test target",
        bytecode_type="runtime",
        authorization_status="unknown",
    )
    db_session.add(row)
    db_session.flush()
    return row
