"""Tests for submitting a scan of a developer's pasted Solidity.

The developer tool is the second way into the product. A developer pastes
source, the server compiles it, and the bytecode that comes out is
analysed by exactly the same pipeline a deployed contract goes through.

These tests care about the promises the developer is given:

* their source is compiled on the server and the bytes analysed are the
  bytes the compiler produced,
* a source that does not compile comes back with the compiler's own
  message, because that message is their next action,
* the same source filed twice is the same contract, so its history
  accumulates instead of splitting in two,
* the findings come from the same engine as everywhere else.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api import assets as assets_api
from app.api import scans as scans_api
from app.core.security import hash_api_key
from app.db.enums import ScanStatus, WorkspaceRole
from app.db.models.assets import TrackedAsset
from app.db.models.identity import (
    ApiKey,
    ContractTarget,
    User,
    Workspace,
    WorkspaceMember,
)
from app.db.models.scans import Finding, Scan, ScanArtifact
from app.services.pipeline import run_scan
from app.services.source_compile import pasted_address

SOURCE = """// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

contract Pasted {
    address public owner;

    constructor() {
        owner = msg.sender;
    }

    function withdraw() public {
        (bool ok, ) = msg.sender.call{value: address(this).balance}("");
        require(ok);
    }

    function originalSender() public view returns (address) {
        return tx.origin;
    }
}
"""

BROKEN_SOURCE = """// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

contract Broken {
    function oops() public {
        this is not solidity
    }
}
"""


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


@pytest.fixture()
def tenant(db_session: Session) -> Tenant:
    """A tenant whose key is scoped to its own workspace."""
    user = User(email=f"dev-{uuid.uuid4().hex}@example.test", display_name="dev")
    db_session.add(user)
    db_session.flush()

    space = Workspace(
        name="dev workspace",
        slug=f"dev-{uuid.uuid4().hex}",
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

    raw_key = f"dev-key-{uuid.uuid4().hex}"
    db_session.add(
        ApiKey(
            user_id=user.id,
            name="dev key",
            key_hash=hash_api_key(raw_key),
            key_prefix=raw_key[:12],
        )
    )
    db_session.flush()
    return Tenant(workspace=space, user=user, raw_key=raw_key)


@pytest.fixture(autouse=True)
def _no_network_source_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the suite off the network.

    The pipeline looks for a contract's verified source so the source
    engine can have a second opinion. A pasted source is read from the
    product's own storage, but the deployed-contract route would be a
    live HTTP request, so it is stubbed out here.
    """
    from app.services import pipeline as pipeline_service

    monkeypatch.setattr(
        pipeline_service, "fetch_verified_source", lambda *a, **k: None
    )


@pytest.fixture()
def captured_enqueue(monkeypatch: pytest.MonkeyPatch) -> list[tuple[uuid.UUID, uuid.UUID]]:
    """Replace the RQ enqueue calls with a recording stub."""
    calls: list[tuple[uuid.UUID, uuid.UUID]] = []

    def fake_enqueue(scan_id: uuid.UUID, job_id: uuid.UUID | None = None) -> str:
        assert job_id is not None
        calls.append((scan_id, job_id))
        return "rq-job-id"

    monkeypatch.setattr(scans_api, "enqueue_scan", fake_enqueue)
    monkeypatch.setattr(assets_api, "enqueue_scan", fake_enqueue)
    return calls


def _submit(client: TestClient, tenant: Tenant, **payload: object):
    """Submit a scan with the given payload."""
    return client.post("/api/v1/scans", json=payload, headers=tenant.headers)


def test_pasted_source_is_compiled_and_queued(
    client: TestClient, tenant: Tenant, db_session: Session, captured_enqueue
) -> None:
    """The scan analyses the bytes the compiler produced."""
    response = _submit(client, tenant, source_code=SOURCE)

    assert response.status_code == 202, response.text
    scan_id = uuid.UUID(response.json()["id"])

    scan = db_session.get(Scan, scan_id)
    assert scan is not None
    assert scan.bytecode_source == "compiled"

    target = scan.target
    assert target.inline_bytecode_source == "compiled"
    assert target.inline_bytecode
    assert len(target.inline_bytecode) > 0
    assert target.source_object_key
    assert "pasted_source" in (target.provenance or "")


def test_a_pasted_source_is_tracked_so_its_history_accumulates(
    client: TestClient, tenant: Tenant, db_session: Session, captured_enqueue
) -> None:
    """The same source is the same contract, not two."""
    first = _submit(client, tenant, source_code=SOURCE)
    second = _submit(client, tenant, source_code=SOURCE)

    assert first.status_code == 202, first.text
    assert second.status_code == 202, second.text

    expected = pasted_address(SOURCE)
    assets = db_session.scalars(select(TrackedAsset)).all()
    assert [asset.address for asset in assets] == [expected]

    targets = db_session.scalars(select(ContractTarget)).all()
    assert len(targets) == 1
    assert targets[0].address == expected


def test_a_source_that_does_not_compile_returns_the_compilers_message(
    client: TestClient, tenant: Tenant, captured_enqueue
) -> None:
    """The developer needs the compiler's message, not a summary of it."""
    response = _submit(client, tenant, source_code=BROKEN_SOURCE)

    assert response.status_code == 422, response.text
    detail = response.json()["error"]["message"]
    assert "Contract.sol" in detail or "Error" in detail
    assert not captured_enqueue


def test_source_and_bytecode_cannot_both_be_supplied(
    client: TestClient, tenant: Tenant, captured_enqueue
) -> None:
    """Two answers to one question is a mistake, not a choice."""
    response = _submit(
        client, tenant, source_code=SOURCE, bytecode_hex="60006000f3"
    )

    assert response.status_code == 422, response.text
    assert not captured_enqueue


def test_a_scan_with_nothing_to_analyse_is_refused(
    client: TestClient, tenant: Tenant, captured_enqueue
) -> None:
    """A scan needs something to analyse."""
    response = _submit(client, tenant)

    assert response.status_code == 422, response.text
    assert not captured_enqueue


def test_the_pasted_contract_is_analysed_by_the_same_engine(
    client: TestClient, tenant: Tenant, db_session: Session, captured_enqueue
) -> None:
    """The findings come from the bytecode engine, on the compiled bytes."""
    response = _submit(client, tenant, source_code=SOURCE)
    assert response.status_code == 202, response.text
    scan = db_session.get(Scan, uuid.UUID(response.json()["id"]))
    assert scan is not None

    outcome = run_scan(db_session, scan)
    db_session.commit()

    # Real compiled code has branches the CFG cannot always resolve, so
    # "partial" is the honest outcome here; what matters is that the
    # engine ran on the compiled bytes and said what it found.
    assert outcome.status in {ScanStatus.COMPLETED, ScanStatus.PARTIAL}
    findings = db_session.scalars(
        select(Finding).where(Finding.scan_id == scan.id)
    ).all()
    assert findings
    assert any("origin" in finding.detector_id.lower() for finding in findings)

    artifacts = db_session.scalars(
        select(ScanArtifact).where(ScanArtifact.scan_id == scan.id)
    ).all()
    kinds = {artifact.kind for artifact in artifacts}
    assert "bytecode" in kinds
    assert "source" in kinds


def test_a_finding_points_at_the_line_the_developer_wrote(
    client: TestClient, tenant: Tenant, db_session: Session, captured_enqueue
) -> None:
    """The offset becomes a line, and the line is the right one.

    The source was compiled by this server, so the mapping from bytecode
    to source is true by construction -- a finding can say "line 17"
    and mean it.
    """
    response = _submit(client, tenant, source_code=SOURCE)
    assert response.status_code == 202, response.text
    scan = db_session.get(Scan, uuid.UUID(response.json()["id"]))
    assert scan is not None

    run_scan(db_session, scan)
    db_session.commit()

    findings = db_session.scalars(
        select(Finding).where(Finding.scan_id == scan.id)
    ).all()
    origin = next(
        finding
        for finding in findings
        if "origin" in finding.detector_id.lower() and finding.source == "rule"
    )
    evidence = origin.evidence_json or {}
    assert "source_line" in evidence, evidence
    assert evidence.get("source_file") == "Contract.sol"

    line_number = int(evidence["source_line"])
    source_lines = SOURCE.splitlines()
    assert 1 <= line_number <= len(source_lines)
    assert "tx.origin" in source_lines[line_number - 1]
