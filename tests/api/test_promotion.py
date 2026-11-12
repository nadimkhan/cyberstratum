"""Tests for promoting discovered contracts into scans.

The feed finds contracts; these tests cover what happens to them next:
that a new contract is scanned, that a known contract is not scanned
twice, that a re-verified contract is scanned again, and that the queue
cannot be flooded.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.db.enums import ScanStatus
from app.db.models.identity import Chain, ContractTarget, Workspace
from app.db.models.scans import Scan, ScanJob
from app.services.promotion import promote_contracts


def _target(
    session: Session,
    workspace: Workspace,
    chain: Chain,
    address: str,
    *,
    verified_at: datetime | None = None,
) -> ContractTarget:
    target = ContractTarget(
        workspace_id=workspace.id,
        chain_id=chain.id,
        address=address,
        label="promotion target",
        bytecode_type="runtime",
        authorization_status="unknown",
        verification_state="verified",
        verified_at=verified_at,
    )
    session.add(target)
    session.flush()
    return target


def test_a_new_contract_is_queued_for_scanning(
    db_session: Session, workspace: Workspace, chain: Chain
) -> None:
    target = _target(db_session, workspace, chain, "0x" + "11" * 20)

    outcome = promote_contracts(db_session, workspace, chain, [target], enqueue=False)

    assert outcome.queued == 1
    assert outcome.skipped_already_scanned == 0
    scans = db_session.query(Scan).filter(Scan.target_id == target.id).all()
    assert len(scans) == 1
    assert scans[0].status is ScanStatus.QUEUED
    # The fork is left unresolved on purpose: the pipeline infers it from
    # the bytecode, because "cancun" is wrong for too many chains.
    assert scans[0].fork == ""
    jobs = db_session.query(ScanJob).filter(ScanJob.scan_id == scans[0].id).all()
    assert len(jobs) == 1


def test_a_contract_is_not_scanned_twice(
    db_session: Session, workspace: Workspace, chain: Chain
) -> None:
    target = _target(db_session, workspace, chain, "0x" + "22" * 20)

    first = promote_contracts(db_session, workspace, chain, [target], enqueue=False)
    second = promote_contracts(db_session, workspace, chain, [target], enqueue=False)

    assert first.queued == 1
    assert second.queued == 0
    assert second.skipped_already_scanned == 1
    assert db_session.query(Scan).filter(Scan.target_id == target.id).count() == 1


def test_a_reverified_contract_is_scanned_again(
    db_session: Session, workspace: Workspace, chain: Chain
) -> None:
    target = _target(db_session, workspace, chain, "0x" + "33" * 20)
    promote_contracts(db_session, workspace, chain, [target], enqueue=False)

    # The source was verified again after the first scan: the contract
    # may have changed under the same address, so it is looked at again.
    target.verified_at = datetime.now(UTC) + timedelta(hours=1)
    db_session.flush()

    outcome = promote_contracts(db_session, workspace, chain, [target], enqueue=False)

    assert outcome.queued == 1
    assert db_session.query(Scan).filter(Scan.target_id == target.id).count() == 2


def test_the_per_cycle_cap_is_respected(
    db_session: Session, workspace: Workspace, chain: Chain
) -> None:
    targets = [
        _target(db_session, workspace, chain, "0x" + f"{index:02x}" * 20)
        for index in range(5)
    ]

    outcome = promote_contracts(
        db_session, workspace, chain, targets, limit=2, enqueue=False
    )

    assert outcome.queued == 2
    assert outcome.skipped_capped == 3


def test_a_full_queue_stops_promotion(
    db_session: Session, workspace: Workspace, chain: Chain
) -> None:
    targets = [
        _target(db_session, workspace, chain, "0x" + f"{index:02x}" * 20)
        for index in range(4)
    ]
    # One scan is already waiting, and the queue is allowed to hold one.
    existing = _target(db_session, workspace, chain, "0x" + "ee" * 20)
    promote_contracts(db_session, workspace, chain, [existing], enqueue=False)

    outcome = promote_contracts(
        db_session, workspace, chain, targets, max_pending=1, enqueue=False
    )

    assert outcome.queued == 0
    assert outcome.skipped_pending == 4


def test_nothing_to_promote_is_not_an_error(
    db_session: Session, workspace: Workspace, chain: Chain
) -> None:
    outcome = promote_contracts(db_session, workspace, chain, [], enqueue=False)
    assert outcome.queued == 0
    assert not outcome.errors
