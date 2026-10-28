"""RQ worker for scan jobs.

Run with::

    .venv/Scripts/python.exe -m app.worker

The worker consumes the ``cyberstratum:scans`` queue and executes the scan
pipeline for each job. Failures are recorded on the scan and job rows rather
than crashing the worker.
"""

from __future__ import annotations

import os
import sys
import uuid
from datetime import UTC, datetime

from rq import SimpleWorker, Worker
from rq.worker import BaseWorker

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.db.enums import ScanJobStatus, ScanStatus
from app.db.models.scans import Scan, ScanJob
from app.db.session import session_scope
from app.queue.connection import get_queue, get_redis
from app.services.pipeline import run_scan

log = get_logger(__name__)


def _now() -> datetime:
    return datetime.now(UTC)


def process_scan_job(scan_id: str, job_id: str | None = None) -> dict[str, object]:
    """Execute one scan job.

    Args:
        scan_id: The UUID of the scan to process, as a string.
        job_id: The UUID of the ``scan_jobs`` row to update, as a string.

    Returns:
        A summary dict describing the outcome.
    """
    parsed_scan_id = uuid.UUID(scan_id)
    parsed_job_id = uuid.UUID(job_id) if job_id else None

    with session_scope() as session:
        scan = session.get(Scan, parsed_scan_id)
        if scan is None:
            log.error("scan_not_found", scan_id=scan_id)
            return {"scan_id": scan_id, "status": "not_found", "finding_count": 0}

        job: ScanJob | None = None
        if parsed_job_id is not None:
            job = session.get(ScanJob, parsed_job_id)
            if job is not None:
                job.status = ScanJobStatus.STARTED
                job.started_at = _now()
                job.attempt += 1
                session.flush()

        scan.status = ScanStatus.QUEUED
        scan.queued_at = scan.queued_at or _now()
        session.flush()

        try:
            outcome = run_scan(session, scan)
        except Exception as exc:  # noqa: BLE001 - never kill the worker
            log.exception("scan_failed", scan_id=scan_id, error=str(exc))
            scan.status = ScanStatus.FAILED
            scan.error_code = "internal_error"
            scan.error_message_redacted = "The scan failed with an internal error."
            scan.completed_at = _now()
            if job is not None:
                job.status = ScanJobStatus.FAILED
                job.finished_at = _now()
                job.duration_ms = _elapsed_ms(job.started_at)
            session.flush()
            return {
                "scan_id": scan_id,
                "status": ScanStatus.FAILED.value,
                "error_code": "internal_error",
                "finding_count": 0,
            }

        if job is not None:
            job.status = ScanJobStatus.FINISHED
            job.finished_at = _now()
            job.duration_ms = _elapsed_ms(job.started_at)
        session.flush()

        return {
            "scan_id": scan_id,
            "status": outcome.status.value,
            "error_code": outcome.error_code,
            "finding_count": outcome.finding_count,
        }


def _elapsed_ms(started_at: datetime | None) -> int | None:
    if started_at is None:
        return None
    delta = _now() - started_at
    return int(delta.total_seconds() * 1000)


def enqueue_scan(scan_id: uuid.UUID, job_id: uuid.UUID | None = None) -> str:
    """Enqueue a scan job on the RQ scan queue and return the RQ job id."""
    queue = get_queue()
    settings = get_settings()
    rq_job = queue.enqueue(
        process_scan_job,
        str(scan_id),
        str(job_id) if job_id is not None else None,
        job_timeout=settings.scan_job_timeout_seconds,
        result_ttl=3600,
        failure_ttl=3600,
    )
    return rq_job.id


def build_worker() -> BaseWorker:
    """Create the RQ worker for this platform.

    RQ's default worker forks a work horse per job, which is unavailable on
    Windows. ``SimpleWorker`` runs jobs in-process instead, so the same
    entrypoint works on every platform.
    """
    queue = get_queue()
    connection = get_redis()
    if hasattr(os, "fork"):
        return Worker([queue], connection=connection, name="cyberstratum-worker")
    return SimpleWorker([queue], connection=connection, name="cyberstratum-worker")


def main() -> int:
    """Run the worker until interrupted."""
    configure_logging()
    queue = get_queue()
    log.info("worker_starting", queue=queue.name)
    worker = build_worker()
    try:
        worker.work(with_scheduler=False)
    except KeyboardInterrupt:  # pragma: no cover - interactive shutdown
        log.info("worker_stopped")
    return 0


if __name__ == "__main__":  # pragma: no cover - process entrypoint
    sys.exit(main())
