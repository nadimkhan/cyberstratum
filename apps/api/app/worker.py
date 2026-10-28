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
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from typing import Any

from rq import SimpleWorker, Worker
from rq.worker import BaseWorker

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.db.enums import ScanJobStatus, ScanStatus
from app.db.models.scans import Scan, ScanJob
from app.db.session import session_scope
from app.queue.connection import get_discovery_queue, get_queue, get_redis
from app.services.discovery import DEFAULT_BATCH_SIZE
from app.services.pipeline import run_scan

log = get_logger(__name__)

#: The name the worker registers itself under in Redis.
WORKER_NAME = "cyberstratum-worker"


class WorkerAlreadyRunningError(RuntimeError):
    """Raised when a live worker already holds the worker name."""


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


def process_discovery_job(
    batch_size: int = DEFAULT_BATCH_SIZE,
    chain_ids: list[int] | None = None,
) -> dict[str, object]:
    """Execute one discovery cycle.

    The feed is asynchronous because the Blockscout client is, so the
    async cycle is driven from this synchronous RQ job.

    Args:
        batch_size: How many chains to sweep in this cycle.
        chain_ids: The chains to consider. ``None`` means every chain in
            the registry.

    Returns:
        A summary dict describing the outcome.
    """
    import asyncio

    from app.db.session import session_scope as _session_scope
    from app.services.blockscout import BlockscoutClient
    from app.services.discovery import DiscoveryService

    async def _run() -> dict[str, object]:
        async with BlockscoutClient() as client:
            with _session_scope() as session:
                service = DiscoveryService(session, client)
                outcome = await service.run_cycle(
                    chain_ids=chain_ids, batch_size=batch_size
                )
                return {
                    "run_id": str(outcome.run_id),
                    "status": outcome.status,
                    "chains_covered": outcome.chains_covered,
                    "chains_failed": outcome.chains_failed,
                    "contracts_found": outcome.contracts_found,
                    "contracts_new": outcome.contracts_new,
                    "contracts_updated": outcome.contracts_updated,
                }

    try:
        return asyncio.run(_run())
    except Exception as exc:  # noqa: BLE001 - never kill the worker
        log.exception("discovery_failed", error=str(exc))
        return {"status": "failed", "error": str(exc)[:300]}


def enqueue_discovery(
    batch_size: int = DEFAULT_BATCH_SIZE,
    chain_ids: list[int] | None = None,
) -> str:
    """Enqueue a discovery cycle and return the RQ job id."""
    queue = get_discovery_queue()
    settings = get_settings()
    rq_job = queue.enqueue(
        process_discovery_job,
        batch_size,
        chain_ids,
        job_timeout=settings.scan_job_timeout_seconds,
        result_ttl=3600,
        failure_ttl=3600,
    )
    return rq_job.id


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


def _windows_process_is_alive(pid: int) -> bool:
    """Return whether a Windows process id still names a live process.

    ``os.kill(pid, 0)`` cannot be used on Windows: CPython implements it by
    calling ``TerminateProcess``, so the "probe" would actually kill the
    target. The Win32 API is queried directly instead.
    """
    import ctypes

    process_query_limited_information = 0x1000
    still_active = 259

    # ``ctypes.WinDLL`` only exists on Windows, so it is looked up
    # dynamically: the module must stay importable on POSIX, and the type
    # checker must stay happy when it runs there.
    win_dll = getattr(ctypes, "WinDLL")  # noqa: B009
    kernel32 = win_dll("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.OpenProcess.argtypes = (ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32)
    kernel32.GetExitCodeProcess.restype = ctypes.c_int
    kernel32.GetExitCodeProcess.argtypes = (ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong))
    kernel32.CloseHandle.restype = ctypes.c_int
    kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)

    handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
    if not handle:
        return False
    try:
        exit_code = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return False
        return exit_code.value == still_active
    finally:
        kernel32.CloseHandle(handle)


def _process_is_alive(pid: int | None) -> bool:
    """Return whether *pid* names a process that is still running.

    A pid that cannot be inspected at all is reported as dead: the
    registration it belongs to should not be able to block a restart.
    """
    if pid is None or pid <= 0:
        return False
    if os.name == "nt":
        return _windows_process_is_alive(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # The process exists but belongs to another user.
        return True
    return True


def clear_stale_worker_registrations(
    workers: Iterable[Any] | None = None,
    *,
    name: str = WORKER_NAME,
    is_alive: Callable[[int | None], bool] = _process_is_alive,
) -> list[str]:
    """Clear Redis worker registrations whose process no longer exists.

    RQ keeps a worker's registration in Redis until the worker reports its
    own death. A worker that is killed hard - a console kill, a crash, a
    power cut - never gets that chance, and the next worker then refuses to
    start with *"There exists an active worker named ... already"*. That
    failure is confusing because the worker really is gone.

    Only registrations whose process cannot be found are cleared. A
    registration whose process is still alive is a real conflict and raises
    :class:`WorkerAlreadyRunningError` rather than being silently removed,
    because two workers consuming the same queue is a worse problem than a
    failed restart.

    Args:
        workers: The registrations to consider. Defaults to every worker
            registered in Redis.
        name: The worker name to reconcile.
        is_alive: Predicate deciding whether a process is running.

    Returns:
        The names of the registrations that were cleared.
    """
    if workers is None:
        workers = Worker.all(connection=get_redis())

    cleared: list[str] = []
    for worker in workers:
        if getattr(worker, "name", None) != name:
            continue
        pid = getattr(worker, "pid", None)
        if is_alive(pid):
            raise WorkerAlreadyRunningError(
                f"A worker named {name!r} is already running (pid {pid}). "
                "Stop it before starting another one."
            )
        worker.register_death()
        cleared.append(name)
    return cleared


def build_worker() -> BaseWorker:
    """Create the RQ worker for this platform.

    RQ's default worker forks a work horse per job, which is unavailable on
    Windows. ``SimpleWorker`` runs jobs in-process instead, so the same
    entrypoint works on every platform.
    """
    queues = [get_queue(), get_discovery_queue()]
    connection = get_redis()
    if hasattr(os, "fork"):
        return Worker(queues, connection=connection, name=WORKER_NAME)
    return SimpleWorker(queues, connection=connection, name=WORKER_NAME)


def main() -> int:
    """Run the worker until interrupted."""
    configure_logging()
    queue = get_queue()
    try:
        cleared = clear_stale_worker_registrations()
    except WorkerAlreadyRunningError as exc:
        log.error("worker_already_running", detail=str(exc))
        return 1
    if cleared:
        log.warning("stale_worker_registrations_cleared", count=len(cleared))
    log.info("worker_starting", queue=queue.name)
    worker = build_worker()
    try:
        worker.work(with_scheduler=False)
    except KeyboardInterrupt:  # pragma: no cover - interactive shutdown
        log.info("worker_stopped")
    return 0


if __name__ == "__main__":  # pragma: no cover - process entrypoint
    sys.exit(main())
