"""Turn the raw Blockscout probe reports into a committed provenance record.

The probe reports live in ``var/`` because they are run output: they are
big, they are regenerated, and nobody edits them by hand. But the
registry they justify -- which chains this product will scan -- is
hand-maintained code. If the survey is only in runtime space, then
nothing in the repository says *why* a chain is in the registry, or
whether the registry has drifted away from what was actually probed.

This script writes the small, useful half: one line per chain that was
probed, with the outcome, the date and the batch. That file is committed,
and the cross-check below compares it against the registry so a drift
between the two is visible rather than silent.

Usage:
    python scripts/summarise_chain_probe.py --write
    python scripts/summarise_chain_probe.py --check
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
PROBE_DIR = REPO_ROOT / "var" / "chain-probe"
SURVEY_PATH = REPO_ROOT / "docs" / "chain-probe" / "survey.json"


@dataclass(frozen=True, slots=True)
class Probed:
    """One host the survey asked."""

    host: str
    chain_id: int | None
    chain_name: str
    status: str
    http_status: int | None
    detail: str
    batch: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "host": self.host,
            "chain_id": self.chain_id,
            "chain_name": self.chain_name,
            "status": self.status,
            "http_status": self.http_status,
            "detail": self.detail,
            "batch": self.batch,
        }


def _load_batches() -> list[dict[str, Any]]:
    """Every batch report, oldest first."""
    reports = []
    for path in sorted(PROBE_DIR.glob("batch*.json")):
        with path.open(encoding="utf-8") as handle:
            reports.append(json.load(handle))
    return reports


def collect() -> tuple[list[Probed], dict[str, Any]]:
    """The probed hosts, and what the survey as a whole did."""
    probed: dict[str, Probed] = {}
    totals = Counter()
    batches = []

    for report in _load_batches():
        batch = Path(str(report.get("__file__", ""))).stem or "batch"
        for result in report.get("results", []):
            totals[result.get("status", "unknown")] += 1
            host = result.get("host", "")
            if not host:
                continue
            probed[host] = Probed(
                host=host,
                chain_id=result.get("chain_id"),
                chain_name=result.get("chain_name", "") or "",
                status=result.get("status", "unknown"),
                http_status=result.get("http_status"),
                detail=result.get("detail", "") or "",
                batch=batch,
            )
        batches.append(
            {
                "started_at": report.get("started_at"),
                "finished_at": report.get("finished_at"),
                "candidates": report.get("candidates"),
                "probed": report.get("probed"),
            }
        )

    summary = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "method": (
            "Candidate hosts derived from the public chain registries "
            "(chainid.network, Etherscan V2 chainlist) and probed one at a "
            "time with a descriptive User-Agent. No credential was sent."
        ),
        "totals": {
            "probed": sum(totals.values()),
            "by_status": dict(sorted(totals.items())),
        },
        "batches": batches,
        # Only the hosts that carry a decision are listed. The ones
        # that answered 404 are counted above and kept in the raw report
        # under var/; listing four thousand dead hostnames would make
        # the record unreadable and the file large for no gain.
        "chains": [
            entry.as_dict()
            for entry in sorted(probed.values(), key=lambda e: e.host)
            if entry.status != "not_found"
        ],
    }
    return list(probed.values()), summary


def registry_hosts() -> dict[int, str]:
    """The chain id to host map the product actually uses."""
    import sys

    for candidate in (REPO_ROOT / "apps" / "api", REPO_ROOT):
        if str(candidate) not in sys.path:
            sys.path.insert(0, str(candidate))
    from app.services.chains import INSTANCE_HOSTS

    return dict(INSTANCE_HOSTS)


def cross_check(probed: list[Probed]) -> dict[str, Any]:
    """Compare the survey with the registry.

    Two directions matter. A registry entry the survey never saw live is
    a claim the survey does not support. A live host the registry is
    missing is a chain the product is not scanning.
    """
    by_host = {entry.host: entry for entry in probed}
    registry = registry_hosts()

    confirmed: dict[str, Any] = {}
    unsupported: list[dict[str, Any]] = []
    for chain_id, host in registry.items():
        entry = by_host.get(host)
        if entry is None:
            unsupported.append({"chain_id": chain_id, "host": host, "reason": "not probed"})
        elif entry.status == "live":
            confirmed[str(chain_id)] = host
        else:
            unsupported.append(
                {
                    "chain_id": chain_id,
                    "host": host,
                    "reason": f"probed as {entry.status}",
                }
            )

    # A chain is compared by its id, not by its host: two hosts can
    # serve the same chain, and the registry is free to use either. What
    # matters is that no chain the survey found live is missing from the
    # registry, and that no registry entry lacks survey support.
    registry_ids = set(registry)
    found_not_registered = [
        {
            "chain_id": entry.chain_id,
            "host": entry.host,
            "chain_name": entry.chain_name,
        }
        for entry in probed
        if entry.status == "live"
        and entry.chain_id is not None
        and entry.chain_id not in registry_ids
    ]

    alternate_hosts = [
        {
            "chain_id": entry.chain_id,
            "host": entry.host,
            "registry_host": registry.get(entry.chain_id),
            "chain_name": entry.chain_name,
        }
        for entry in probed
        if entry.status == "live"
        and entry.chain_id is not None
        and entry.chain_id in registry_ids
        and registry.get(entry.chain_id) != entry.host
    ]

    return {
        "registry_entries": len(registry),
        "confirmed_live": confirmed,
        "unsupported": unsupported,
        "live_but_not_registered": found_not_registered,
        "alternate_hosts": alternate_hosts,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="write the survey file")
    parser.add_argument("--check", action="store_true", help="report drift and exit non-zero")
    args = parser.parse_args()

    probed, summary = collect()
    check = cross_check(probed)

    if args.write:
        SURVEY_PATH.parent.mkdir(parents=True, exist_ok=True)
        SURVEY_PATH.write_text(
            json.dumps(summary, indent=2, sort_keys=False) + "\n", encoding="utf-8"
        )
        print(f"wrote {SURVEY_PATH.relative_to(REPO_ROOT)}")

    totals = summary["totals"]
    print(f"probed {totals['probed']} hosts: {totals['by_status']}")
    print(f"registry entries: {check['registry_entries']}")
    print(f"confirmed live: {len(check['confirmed_live'])}")
    print(f"unsupported registry entries: {len(check['unsupported'])}")
    for item in check["unsupported"]:
        print(f"  - {item['chain_id']} {item['host']}: {item['reason']}")
    print(f"live chains not registered: {len(check['live_but_not_registered'])}")
    for item in check["live_but_not_registered"]:
        print(f"  - {item['chain_id']} {item['host']} ({item['chain_name']})")
    print(f"alternate live hosts: {len(check['alternate_hosts'])}")
    for item in check["alternate_hosts"]:
        print(f"  - {item['chain_id']} {item['host']} (registry uses {item['registry_host']})")

    if args.check and (check["unsupported"] or check["live_but_not_registered"]):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
