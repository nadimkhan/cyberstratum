"""Promote discovered contracts into scans.

The discovery feed finds contracts; the scan pipeline analyses them.
Until now nothing joined the two, so a verified contract could sit in the
feed forever without being looked at.

The policy here is deliberately blunt, because the alternative -- a
person deciding which contracts are worth analysing -- does not scale to
every verification on every chain:

* **Every newly verified contract is scanned.** Not a sample, not a
  shortlist. The value of the feed is that it covers what nobody else
  looked at.
* **A contract is not scanned twice.** The target is unique per
  (workspace, chain, address), so a re-discovery is recognised and
  skipped. The one exception is a re-verification: a contract whose
  source was verified again may have changed, so it is analysed again.
* **The queue is bounded.** Two valves stop a busy chain from burying
  the worker: a cap on how many scans one cycle may queue, and a cap on
  how many scans may be waiting in total. When the second valve is
  closed, the feed keeps discovering and the queue stays honest.

The scans are queued in the *discovery workspace*, which the product
owns. Promoting a contract into a tenant's workspace is a separate,
human decision and is not done here: a public feed has no business
filling a paying customer's workspace with contracts they never asked
for.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.enums import ScanJobStatus, ScanJobType, ScanStatus
from app.db.models.identity import Chain, ContractTarget, Workspace
from app.db.models.scans import Scan, ScanJob

__all__ = [
    "DEFAULT_MAX_PENDING_SCANS",
    "DEFAULT_MAX_SCANS_PER_CYCLE",
    "PromotionOutcome",
    "promote_contracts",
]

#: How many scans one discovery cycle may queue for a single chain.
DEFAULT_MAX_SCANS_PER_CYCLE = 50

#: How many scans may be waiting in total before the feed stops queueing.
DEFAULT_MAX_PENDING_SCANS = 500


@dataclass
class PromotionOutcome:
    """What a promotion pass did.

    Attributes:
        queued: Scans queued.
        skipped_already_scanned: Contracts that had already been
            analysed and were not re-verified since.
        skipped_capped: Contracts left alone because a limit was
            reached.
        skipped_pending: Contracts left alone because the queue was
            already full.
        failed: Scans that could not be queued.
    """

    queued: int = 0
    skipped_already_scanned: int = 0
    skipped_capped: int = 0
    skipped_pending: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        """A JSON-friendly view, for the run row and the log."""
        return {
            "queued": self.queued,
            "skipped_already_scanned": self.skipped_already_scanned,
            "skipped_capped": self.skipped_capped,
            "skipped_pending": self.skipped_pending,
            "failed": self.failed,
            "errors": list(self.errors),
        }


#: The statuses a scan is in while it is still waiting for, or working
#: through, the pipeline. A scan in one of these has not reached a
#: verdict yet, so it counts against the queue depth.
IN_FLIGHT_STATUSES = (
    ScanStatus.QUEUED,
    ScanStatus.FETCHING_BYTECODE,
    ScanStatus.DISASSEMBLING,
    ScanStatus.BUILDING_CFG,
    ScanStatus.EXTRACTING_FEATURES,
    ScanStatus.RUNNING_DETECTORS,
)


def _pending_scan_count(session: Session) -> int:
    """How many scans are waiting for, or working through, the pipeline."""
    return int(
        session.execute(
            select(func.count())
            .select_from(Scan)
            .where(Scan.status.in_(IN_FLIGHT_STATUSES))
        ).scalar_one()
    )


def _latest_scan(session: Session, target_id: object) -> Scan | None:
    """The most recent scan of a target, if there is one."""
    return session.execute(
        select(Scan)
        .where(Scan.target_id == target_id)
        .order_by(Scan.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def promote_contracts(
    session: Session,
    workspace: Workspace,
    chain_row: Chain,
    targets: Sequence[ContractTarget],
    *,
    limit: int = DEFAULT_MAX_SCANS_PER_CYCLE,
    max_pending: int = DEFAULT_MAX_PENDING_SCANS,
    enqueue: bool = True,
) -> PromotionOutcome:
    """Queue scans for contracts that have not been analysed yet.

    Args:
        session: The database session.
        workspace: The workspace the scans are filed under.
        chain_row: The chain the contracts live on.
        targets: The contracts to consider.
        limit: How many scans this pass may queue.
        max_pending: How many scans may be waiting in total.
        enqueue: When False, the scans are created and recorded but not
            handed to the queue. Used by the tests, and by a dry run.

    Returns:
        What the pass did.
    """
    outcome = PromotionOutcome()
    if not targets:
        return outcome

    pending = _pending_scan_count(session)
    now = datetime.now(UTC)

    for target in targets:
        if outcome.queued >= limit:
            outcome.skipped_capped += 1
            continue

        if pending >= max_pending:
            outcome.skipped_pending += 1
            continue

        previous = _latest_scan(session, target.id)
        if previous is not None:
            # A re-verification is the one event that justifies looking
            # again: the source may have changed under the same address.
            reverified = (
                target.verified_at is not None
                and previous.created_at is not None
                and target.verified_at > previous.created_at
            )
            if not reverified:
                outcome.skipped_already_scanned += 1
                continue

        scan = Scan(
            workspace_id=workspace.id,
            target_id=target.id,
            status=ScanStatus.QUEUED,
            requested_by=None,
            fork="",
            bytecode_source="rpc",
            queued_at=now,
        )
        session.add(scan)
        session.flush()

        job = ScanJob(
            scan_id=scan.id,
            job_type=ScanJobType.SCAN,
            status=ScanJobStatus.QUEUED,
            attempt=0,
        )
        session.add(job)
        session.flush()

        if not enqueue:
            outcome.queued += 1
            pending += 1
            continue

        # Imported here rather than at module scope: the worker imports
        # the discovery service, which imports this module, and a
        # module-level import would close the cycle.
        from app.worker import enqueue_scan  # noqa: PLC0415

        try:
            rq_job_id = enqueue_scan(scan.id, job.id)
        except Exception as exc:  # noqa: BLE001 - a queue failure is reported, not raised
            job.status = ScanJobStatus.FAILED
            scan.status = ScanStatus.FAILED
            scan.error_code = "enqueue_failed"
            scan.error_message_redacted = f"Could not queue the scan: {exc}"[:500]
            outcome.failed += 1
            outcome.errors.append(f"{target.address}: {exc}"[:300])
            continue

        job.rq_job_id = rq_job_id
        outcome.queued += 1
        pending += 1

    session.flush()
    return outcome
