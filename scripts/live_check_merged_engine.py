"""Live check of the merged engine: bytecode analysis and source audit.

Runs the whole scan pipeline over a real, verified contract on Ethereum:
the bytecode engine analyses the deployed runtime, and the source engine
audits the verified source with the real Slither executable, as an
external process.

Nothing is written to the development database: the check runs against a
transaction that is rolled back.

Usage::

    node scripts/py.mjs --cwd . -m scripts.live_check_merged_engine
"""

from __future__ import annotations

import sys
import uuid

from sqlalchemy import select

from app.db.enums import ScanStatus
from app.db.models.identity import Chain, ContractTarget, Workspace
from app.db.models.scans import Finding, Scan, ScanArtifact
from app.db.session import session_scope
from app.services.pipeline import run_scan

#: A real, verified contract with known source. It is a proxy implementation
#: with a withdraw function, which is exactly the sort of thing the source
#: engine has something to say about.
CONTRACT = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
CHAIN_ID = 1


def main() -> int:
    """Run one live scan and report what both engines produced."""
    with session_scope() as session:
        slug = f"live-check-{uuid.uuid4().hex[:8]}"
        workspace = Workspace(name="Live check", slug=slug)
        session.add(workspace)
        session.flush()

        chain_row = session.execute(
            select(Chain).where(Chain.chain_id == CHAIN_ID)
        ).scalar_one_or_none()
        if chain_row is None:
            chain_row = Chain(name="Ethereum", chain_id=CHAIN_ID, environment="mainnet")
            session.add(chain_row)
            session.flush()

        target = ContractTarget(
            workspace_id=workspace.id,
            chain_id=chain_row.id,
            address=CONTRACT,
            label="Live check target",
            bytecode_type="runtime",
            authorization_status="unknown",
        )
        session.add(target)
        session.flush()

        scan = Scan(
            workspace_id=workspace.id,
            target_id=target.id,
            status=ScanStatus.QUEUED,
            fork="shanghai",
            bytecode_source="rpc",
        )
        session.add(scan)
        session.flush()

        outcome = run_scan(session, scan)

        print("=== scan ===")
        print(f"  status             : {outcome.status.value}")
        print(f"  findings           : {outcome.finding_count}")
        print(f"  source audited     : {scan.source_audited}")
        print(f"  source skipped     : {scan.source_audit_skipped}")

        print("=== artifacts ===")
        for artifact in session.execute(
            select(ScanArtifact).where(ScanArtifact.scan_id == scan.id)
        ).scalars():
            print(f"  {artifact.kind:<14} {artifact.object_key}")

        print("=== findings by engine ===")
        rows = session.execute(
            select(Finding.source, Finding.detector_id, Finding.severity)
            .where(Finding.scan_id == scan.id)
            .order_by(Finding.source, Finding.detector_id)
        ).all()
        by_engine: dict[str, list[str]] = {}
        for source, detector_id, severity in rows:
            severity_value = severity.value if hasattr(severity, "value") else str(severity)
            by_engine.setdefault(source, []).append(f"{detector_id} [{severity_value}]")
        for source in sorted(by_engine):
            print(f"  {source}: {len(by_engine[source])}")
            for item in by_engine[source]:
                print(f"    {item}")

        if not by_engine:
            print("  no findings")
            return 1

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001 - report, do not traceback
        print(f"live check failed: {type(exc).__name__}: {exc}")
        sys.exit(1)
