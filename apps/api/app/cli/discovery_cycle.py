"""Queue one discovery cycle.

The autonomous path needs a trigger that nobody has to press. This
command is that trigger: a systemd timer calls it on a schedule, it
queues one discovery cycle, and the discovery worker runs it.

The cycle is *queued* rather than run in-process for two reasons:

* there is exactly one execution path -- the same code the API and the
  worker use -- so a scheduled cycle and a manual one behave identically;
* a cycle waits patiently in the queue if the worker is restarting,
  instead of dying half-way through a sweep of sixty chains.

Running the command twice in a row is harmless: discovery is idempotent
(contracts are unique per workspace, chain and address) and promotion
skips a contract that has already been scanned. The guard below only
avoids piling up cycles that would overlap.

Run with::

    python -m app.cli.discovery_cycle
    python -m app.cli.discovery_cycle --batch-size 8 --chain-id 1
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from sqlalchemy import select

from app.core.logging import get_logger
from app.db.models.discovery import DiscoveryRun
from app.db.session import session_scope
from app.queue.connection import get_discovery_queue

#: A cycle that has been running for longer than this is not in flight;
#: it is a row whose worker died, and the next cycle must not be blocked
#: by it.
STALE_CYCLE_SECONDS = 2 * 60 * 60

log = get_logger(__name__)


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for the command."""
    parser = argparse.ArgumentParser(
        prog="python -m app.cli.discovery_cycle",
        description=(
            "Queue one discovery cycle: read the newest verified contracts "
            "from the chain registry and queue a scan for each new one."
        ),
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=None,
        help="How many chains to sweep in this cycle.",
    )
    parser.add_argument(
        "--chain-id",
        type=int,
        action="append",
        dest="chain_ids",
        help="Only sweep this chain. May be given more than once.",
    )
    parser.add_argument(
        "--pages",
        type=int,
        default=None,
        help=(
            "How many pages of the feed each chain reads in this cycle. "
            "More than one page walks into the history of the chain."
        ),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Queue a cycle even when one is already in flight.",
    )
    return parser


def _job_pending() -> bool:
    """Whether a discovery cycle is already waiting in the queue."""
    try:
        queue = get_discovery_queue()
        job_ids = queue.get_job_ids()
    except Exception:  # noqa: BLE001 - an unreadable queue is not a reason to skip
        return False
    for job_id in job_ids:
        try:
            job = queue.fetch_job(job_id)
        except Exception as exc:  # noqa: BLE001 - a job that cannot be read is not a reason to skip
            log.warning("discovery_queue_job_unreadable", job_id=job_id, error=str(exc))
            continue
        if job is None:
            continue
        func_name = getattr(job, "func_name", "") or ""
        if "process_discovery_job" in func_name:
            return True
    return False


def _cycle_running(session: object) -> bool:
    """Whether a discovery cycle is currently running."""
    from datetime import UTC, datetime, timedelta

    from sqlalchemy.orm import Session

    if not isinstance(session, Session):
        return False
    cutoff = datetime.now(UTC) - timedelta(seconds=STALE_CYCLE_SECONDS)
    rows = session.scalars(
        select(DiscoveryRun)
        .where(DiscoveryRun.status == "running")
        .where(DiscoveryRun.started_at >= cutoff)
    ).all()
    return bool(rows)


def main(argv: Sequence[str] | None = None) -> int:
    """Queue one discovery cycle and report what happened."""
    args = build_parser().parse_args(argv)

    from app.services.discovery import DEFAULT_BATCH_SIZE, DEFAULT_PAGES_PER_CHAIN
    from app.worker import enqueue_discovery

    batch_size = args.batch_size if args.batch_size is not None else DEFAULT_BATCH_SIZE
    pages = args.pages if args.pages is not None else DEFAULT_PAGES_PER_CHAIN
    if pages < 1:
        print("--pages must be at least 1", file=sys.stderr)
        return 2

    with session_scope() as session:
        if not args.force and (_job_pending() or _cycle_running(session)):
            print("a discovery cycle is already in flight; nothing was queued")
            return 0

    try:
        rq_job_id = enqueue_discovery(
            batch_size=batch_size, chain_ids=args.chain_ids, pages=pages
        )
    except Exception as exc:  # noqa: BLE001 - a queue failure must be reported
        print(f"could not queue a discovery cycle: {exc}", file=sys.stderr)
        return 1

    print(
        f"queued discovery cycle {rq_job_id} "
        f"(batch size {batch_size}, {pages} page(s) per chain)"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())
