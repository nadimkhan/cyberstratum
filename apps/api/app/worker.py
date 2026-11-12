"""RQ worker for scan jobs.

Run with::

    .venv/Scripts/python.exe -m app.worker

The worker consumes the ``cyberstratum:scans`` queue and executes the scan
pipeline for each job. Failures are recorded on the scan and job rows rather
than crashing the worker.

The Mythril queue is served by a *separate* worker, started with::

    python -m app.worker --queues mythril --name cyberstratum-worker-mythril

It is deliberately not served by the ordinary worker: a symbolic-execution
run can take minutes, and it must never delay an ordinary scan.
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, datetime
from typing import Any

from rq import SimpleWorker, Worker
from rq.worker import BaseWorker
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.db.enums import CorrespondenceStatus, ScanJobStatus, ScanStatus
from app.db.models.scans import CorrespondenceProof, Scan, ScanArtifact, ScanJob
from app.db.session import session_scope
from app.queue.connection import (
    get_correspondence_queue,
    get_discovery_queue,
    get_mythril_queue,
    get_queue,
    get_redis,
)
from app.services import storage
from app.services.correspondence import CorrespondenceOutcome, CorrespondenceProver
from app.services.discovery import DEFAULT_BATCH_SIZE, DEFAULT_PAGES_PER_CHAIN
from app.services.mythril import MythrilRunner, to_rule_findings
from app.services.pipeline import persist_findings, run_scan

log = get_logger(__name__)

#: The name the worker registers itself under in Redis.
WORKER_NAME = "cyberstratum-worker"

#: The name the dedicated Mythril worker registers itself under in Redis.
MYTHRIL_WORKER_NAME = "cyberstratum-worker-mythril"

#: The name the dedicated correspondence worker registers itself under.
CORRESPONDENCE_WORKER_NAME = "cyberstratum-worker-correspondence"

#: The logical queues this platform knows about, and how to resolve them.
QUEUE_RESOLVERS = {
    "scans": get_queue,
    "discovery": get_discovery_queue,
    "mythril": get_mythril_queue,
    "correspondence": get_correspondence_queue,
}


class WorkerAlreadyRunningError(RuntimeError):
    """Raised when a live worker already holds the worker name."""


def _now() -> datetime:
    return datetime.now(UTC)


def _missing_scan(
    session: Session,
    job: ScanJob | None,
    scan_id: str,
    event: str,
) -> dict[str, object]:
    """Record a job whose scan no longer exists.

    This is the expected result of a cascade delete -- a workspace
    removed while its scans were queued -- and not an error. It is also
    not a success: the work never happened, so the job row says so.
    Marking it failed stops the audit trail from claiming a scan that was
    never performed.

    The function returns normally rather than raising, because a missing
    scan will not appear on a retry, and RQ's retries would spend three
    attempts discovering that.
    """
    log.info(event, scan_id=scan_id, reason="the scan no longer exists")
    if job is not None:
        job.status = ScanJobStatus.FAILED
        job.finished_at = _now()
        job.resource_usage = {
            **(job.resource_usage or {}),
            "error": "the scan no longer exists",
        }
        session.flush()
    return {"scan_id": scan_id, "status": "not_found", "finding_count": 0}


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
        job: ScanJob | None = None
        if parsed_job_id is not None:
            job = session.get(ScanJob, parsed_job_id)

        scan = session.get(Scan, parsed_scan_id)
        if scan is None:
            return _missing_scan(session, job, scan_id, "scan_not_found")

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
    pages: int = DEFAULT_PAGES_PER_CHAIN,
) -> dict[str, object]:
    """Execute one discovery cycle.

    The feed is asynchronous because the Blockscout client is, so the
    async cycle is driven from this synchronous RQ job.

    Args:
        batch_size: How many chains to sweep in this cycle.
        chain_ids: The chains to consider. ``None`` means every chain in
            the registry.
        pages: How many pages of the feed each chain reads. More than
            one page walks into the history of the chain.

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
                    chain_ids=chain_ids, batch_size=batch_size, pages=pages
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
    pages: int = DEFAULT_PAGES_PER_CHAIN,
) -> str:
    """Enqueue a discovery cycle and return the RQ job id."""
    queue = get_discovery_queue()
    settings = get_settings()
    rq_job = queue.enqueue(
        process_discovery_job,
        batch_size,
        chain_ids,
        pages,
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


def _load_runtime_bytecode(session: Any, scan: Scan) -> bytes | None:
    """Read back the runtime bytecode the scan actually analysed.

    The stored bytecode artifact is the single source of truth here. Reading
    it back - rather than re-fetching from a chain or re-deriving it - is
    what guarantees Mythril sees the same runtime the bytecode engine saw.
    In particular it guarantees Mythril is never handed creation code, which
    would produce a silent false clean.

    Args:
        session: The open database session.
        scan: The scan whose bytecode should be loaded.

    Returns:
        The runtime bytecode, or ``None`` when it is not stored or cannot
        be read.
    """
    artifact = session.scalars(
        select(ScanArtifact)
        .where(ScanArtifact.scan_id == scan.id, ScanArtifact.kind == "bytecode")
        .order_by(ScanArtifact.created_at.desc())
    ).first()
    if artifact is None:
        return None
    try:
        return storage.get_bytes(artifact.object_key)
    except Exception as exc:  # noqa: BLE001 - a missing artifact is a skip
        log.warning(
            "mythril_bytecode_artifact_unreadable",
            object_key=artifact.object_key,
            error=str(exc),
        )
        return None


def process_mythril_job(scan_id: str, job_id: str | None = None) -> dict[str, object]:
    """Execute one on-demand Mythril deep analysis.

    Mythril is manual-only: this job is queued only by an explicit human
    action, on its own queue, with its own budget. It never runs as part of
    a standard scan.

    Three facts are recorded separately, because collapsing them is how a
    security product starts to lie:

    * whether Mythril produced a verdict at all,
    * why it did not, when it did not,
    * what it found, when it did.

    A Mythril run that learned nothing leaves ``mythril_ran`` false and a
    reason in ``mythril_skipped``. It is never recorded as a clean contract.

    Args:
        scan_id: The UUID of the scan to analyse, as a string.
        job_id: The UUID of the ``scan_jobs`` row to update, as a string.

    Returns:
        A summary dict describing the outcome.
    """
    parsed_scan_id = uuid.UUID(scan_id)
    parsed_job_id = uuid.UUID(job_id) if job_id else None

    with session_scope() as session:
        job: ScanJob | None = None
        if parsed_job_id is not None:
            job = session.get(ScanJob, parsed_job_id)

        scan = session.get(Scan, parsed_scan_id)
        if scan is None:
            return _missing_scan(session, job, scan_id, "mythril_scan_not_found")

        if job is not None:
            job.status = ScanJobStatus.STARTED
            job.started_at = _now()
            job.attempt += 1
            session.flush()

        bytecode = _load_runtime_bytecode(session, scan)
        if bytecode is None:
            scan.mythril_ran = False
            scan.mythril_skipped = "bytecode_artifact_missing"
            if job is not None:
                job.status = ScanJobStatus.FINISHED
                job.finished_at = _now()
                job.duration_ms = _elapsed_ms(job.started_at)
            session.flush()
            log.warning("mythril_skipped_no_bytecode", scan_id=scan_id)
            return {
                "scan_id": scan_id,
                "status": "no_verdict",
                "skipped": "bytecode_artifact_missing",
                "finding_count": 0,
            }

        target = scan.target
        contract_name = ""
        if target is not None:
            contract_name = target.label or target.address or ""

        settings = get_settings()
        runner = MythrilRunner(
            executable=settings.mythril_bin,
            timeout=settings.mythril_timeout_seconds,
            solver_timeout_ms=settings.mythril_solver_timeout_ms,
        )

        try:
            result = runner.run(bytecode, contract_name=contract_name)
        except Exception as exc:  # noqa: BLE001 - never kill the worker
            log.exception("mythril_failed", scan_id=scan_id, error=str(exc))
            scan.mythril_ran = False
            scan.mythril_skipped = "engine_error"
            if job is not None:
                job.status = ScanJobStatus.FAILED
                job.finished_at = _now()
                job.duration_ms = _elapsed_ms(job.started_at)
            session.flush()
            return {
                "scan_id": scan_id,
                "status": "failed",
                "skipped": "engine_error",
                "finding_count": 0,
            }

        # A verdict means the engine produced an envelope it could stand
        # behind. Anything else - no output, a crash, an unusable envelope -
        # is recorded as "no verdict", never as a clean result.
        produced_verdict = result.ran and result.skipped is None
        scan.mythril_ran = produced_verdict
        scan.mythril_skipped = result.skipped

        finding_count = 0
        if result.findings:
            try:
                persist_findings(
                    session,
                    scan,
                    to_rule_findings(result.findings),
                    source="mythril",
                )
                finding_count = len(result.findings)
            except Exception as exc:  # noqa: BLE001 - never kill the worker
                # The engine produced a real verdict and the storage layer
                # refused it. Discarding the verdict silently would be the
                # worst possible outcome: the contract would look exactly
                # like one Mythril never examined. The scan is therefore
                # marked as having produced no verdict, with the reason
                # spelled out, and the failure is logged with the number of
                # findings that were lost.
                log.exception(
                    "mythril_findings_not_persisted",
                    scan_id=scan_id,
                    error=str(exc),
                    lost_findings=len(result.findings),
                )
                scan.mythril_ran = False
                scan.mythril_skipped = "findings_persist_failed"
                if job is not None:
                    job.status = ScanJobStatus.FAILED
                    job.finished_at = _now()
                    job.duration_ms = _elapsed_ms(job.started_at)
                session.flush()
                return {
                    "scan_id": scan_id,
                    "status": "failed",
                    "skipped": "findings_persist_failed",
                    "finding_count": 0,
                }

        if job is not None:
            job.status = ScanJobStatus.FINISHED
            job.finished_at = _now()
            job.duration_ms = _elapsed_ms(job.started_at)
        session.flush()

        log.info(
            "mythril_finished",
            scan_id=scan_id,
            verdict=produced_verdict,
            skipped=result.skipped,
            findings=finding_count,
        )
        return {
            "scan_id": scan_id,
            "status": "completed" if produced_verdict else "no_verdict",
            "skipped": result.skipped,
            "finding_count": finding_count,
        }


def _record_correspondence_proof(
    session: Any,
    scan: Scan,
    outcome: Any,
) -> None:
    """Store a correspondence outcome against its scan.

    The proof is stored rather than computed on demand, because the report
    must be reproducible: a reader has to be able to see the proof that was
    in force when the report was issued.

    Args:
        session: The open database session.
        scan: The scan the proof belongs to.
        outcome: The :class:`CorrespondenceOutcome` to store.
    """
    evidence = outcome.to_evidence()
    session.add(
        CorrespondenceProof(
            scan_id=scan.id,
            status=outcome.status,
            skipped=outcome.skipped,
            compiler_version=outcome.compiler_version,
            source_path=outcome.source_path,
            runtime_sha256=outcome.runtime_sha256,
            executable_sha256=outcome.executable_sha256,
            metadata_sha256=outcome.metadata_sha256,
            runtime_byte_size=outcome.runtime_byte_size,
            executable_byte_size=outcome.executable_byte_size,
            instruction_count=outcome.instruction_count,
            mapped_instruction_count=outcome.mapped_instruction_count,
            proof_json=evidence,
        )
    )
    session.flush()


def process_correspondence_job(scan_id: str, job_id: str | None = None) -> dict[str, object]:
    """Execute one on-demand source-to-bytecode correspondence proof.

    The proof is manual-only, like Mythril: it runs a compiler, so it is
    queued by an explicit human action and never joins a default scan.

    The outcome is always stored, including the outcomes that prove nothing.
    A proof that could not be performed is recorded as *unavailable*, which
    is a tooling fact and never an accusation against the contract.

    Args:
        scan_id: The UUID of the scan to prove, as a string.
        job_id: The UUID of the ``scan_jobs`` row to update, as a string.

    Returns:
        A summary dict describing the outcome.
    """
    parsed_scan_id = uuid.UUID(scan_id)
    parsed_job_id = uuid.UUID(job_id) if job_id else None

    with session_scope() as session:
        job: ScanJob | None = None
        if parsed_job_id is not None:
            job = session.get(ScanJob, parsed_job_id)

        scan = session.get(Scan, parsed_scan_id)
        if scan is None:
            return _missing_scan(session, job, scan_id, "correspondence_scan_not_found")

        if job is not None:
            job.status = ScanJobStatus.STARTED
            job.started_at = _now()
            job.attempt += 1
            session.flush()

        target = scan.target
        address = target.address if target is not None else None
        chain_id = target.chain.chain_id if target is not None else None

        bytecode = _load_runtime_bytecode(session, scan)
        if bytecode is None or not address or chain_id is None:
            reason = "bytecode_artifact_missing" if bytecode is None else "contract_target_unknown"
            outcome = CorrespondenceOutcome(
                status=CorrespondenceStatus.SKIPPED,
                skipped=reason,
                detail="The proof could not run because the runtime or the target is unknown.",
            )
            _record_correspondence_proof(session, scan, outcome)
            if job is not None:
                job.status = ScanJobStatus.FINISHED
                job.finished_at = _now()
                job.duration_ms = _elapsed_ms(job.started_at)
            session.flush()
            log.warning("correspondence_skipped", scan_id=scan_id, reason=reason)
            return {"scan_id": scan_id, "status": outcome.status.value, "skipped": reason}

        settings = get_settings()
        prover = CorrespondenceProver(
            timeout_seconds=settings.correspondence_http_timeout_seconds,
            compile_timeout_seconds=settings.correspondence_compile_timeout_seconds,
            artifacts_dir=settings.solc_artifacts_dir or None,
            fork=settings.default_evm_fork,
        )

        try:
            outcome = prover.prove(address, str(chain_id), bytecode)
        except Exception as exc:  # noqa: BLE001 - never kill the worker
            log.exception("correspondence_failed", scan_id=scan_id, error=str(exc))
            outcome = CorrespondenceOutcome(
                status=CorrespondenceStatus.UNAVAILABLE,
                skipped="prover_error",
                detail=f"The proof could not be performed: {exc}"[:300],
            )

        _record_correspondence_proof(session, scan, outcome)

        if job is not None:
            job.status = ScanJobStatus.FINISHED
            job.finished_at = _now()
            job.duration_ms = _elapsed_ms(job.started_at)
        session.flush()

        log.info(
            "correspondence_finished",
            scan_id=scan_id,
            status=outcome.status.value,
            skipped=outcome.skipped,
        )
        return {
            "scan_id": scan_id,
            "status": outcome.status.value,
            "skipped": outcome.skipped,
        }


def enqueue_correspondence(scan_id: uuid.UUID, job_id: uuid.UUID | None = None) -> str:
    """Enqueue an on-demand correspondence proof on its own queue.

    The proof recompiles the contract's verified source, which is a compiler
    run rather than a bytecode scan. It therefore gets a queue and a budget
    of its own, so a slow recompilation can never delay an ordinary scan.

    Args:
        scan_id: The scan to prove.
        job_id: The ``scan_jobs`` row to update when the job runs.

    Returns:
        The RQ job id.
    """
    queue = get_correspondence_queue()
    settings = get_settings()
    rq_job = queue.enqueue(
        process_correspondence_job,
        str(scan_id),
        str(job_id) if job_id is not None else None,
        job_timeout=settings.correspondence_timeout_seconds + 60,
        result_ttl=3600,
        failure_ttl=3600,
    )
    return rq_job.id


def enqueue_mythril(scan_id: uuid.UUID, job_id: uuid.UUID | None = None) -> str:
    """Enqueue an on-demand Mythril run on the dedicated Mythril queue.

    The Mythril queue is separate from the scan queue on purpose. A
    symbolic-execution run is expensive, and it must not delay the ordinary
    scan path or consume the scan worker's budget.

    Args:
        scan_id: The scan to analyse.
        job_id: The ``scan_jobs`` row to update when the job runs.

    Returns:
        The RQ job id.
    """
    queue = get_mythril_queue()
    settings = get_settings()
    rq_job = queue.enqueue(
        process_mythril_job,
        str(scan_id),
        str(job_id) if job_id is not None else None,
        job_timeout=settings.mythril_timeout_seconds + 60,
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


def build_worker(
    queue_names: Sequence[str] | None = None,
    name: str = WORKER_NAME,
) -> BaseWorker:
    """Create the RQ worker for this platform.

    RQ's default worker forks a work horse per job, which is unavailable on
    Windows. ``SimpleWorker`` runs jobs in-process instead, so the same
    entrypoint works on every platform.

    Args:
        queue_names: The logical queues to listen on. Defaults to the
            ordinary scan and discovery queues. The Mythril queue is *not*
            included by default: it gets its own worker so a deep analysis
            cannot delay an ordinary scan.
        name: The name the worker registers itself under in Redis.

    Returns:
        The worker.

    Raises:
        ValueError: If an unknown logical queue name is given.
    """
    if queue_names is None:
        queue_names = ("scans", "discovery")
    queues = []
    for queue_name in queue_names:
        resolver = QUEUE_RESOLVERS.get(queue_name)
        if resolver is None:
            raise ValueError(
                f"unknown queue {queue_name!r}; expected one of {sorted(QUEUE_RESOLVERS)}"
            )
        queues.append(resolver())
    connection = get_redis()
    if hasattr(os, "fork"):
        return Worker(queues, connection=connection, name=name)
    return SimpleWorker(queues, connection=connection, name=name)


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse the worker's command line."""
    parser = argparse.ArgumentParser(description="CyberStratum RQ worker.")
    parser.add_argument(
        "--queues",
        default="scans,discovery",
        help=("Comma-separated logical queues to listen on. One of: scans, discovery, mythril."),
    )
    parser.add_argument(
        "--name",
        default=WORKER_NAME,
        help="The name the worker registers itself under in Redis.",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main() -> int:
    """Run the worker until interrupted."""
    configure_logging()
    args = _parse_args()
    queue_names = [part.strip() for part in str(args.queues).split(",") if part.strip()]
    if not queue_names:
        log.error("worker_no_queues")
        return 2
    worker_name = str(args.name)
    try:
        cleared = clear_stale_worker_registrations(name=worker_name)
    except WorkerAlreadyRunningError as exc:
        log.error("worker_already_running", detail=str(exc))
        return 1
    if cleared:
        log.warning("stale_worker_registrations_cleared", count=len(cleared))
    try:
        worker = build_worker(queue_names, name=worker_name)
    except ValueError as exc:
        log.error("worker_bad_queue", detail=str(exc))
        return 2
    log.info(
        "worker_starting",
        queues=[queue.name for queue in worker.queues],
        name=worker_name,
    )
    try:
        worker.work(with_scheduler=False)
    except KeyboardInterrupt:  # pragma: no cover - interactive shutdown
        log.info("worker_stopped")
    return 0


if __name__ == "__main__":  # pragma: no cover - process entrypoint
    sys.exit(main())
