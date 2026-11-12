"""Measure the gap between the detectors and the advice.

The catalogue is what the analysis engine can emit; the guidance is what
a reviewer acts on. A detector in the catalogue with no guidance is a
detector that can produce a finding nobody has been told how to read,
so the gap is measured rather than remembered.

The report also names the guidance entries that name no catalogue
detector -- a typo in a detector id would otherwise sit in the seed
looking like advice for something.

Run with::

    python -m app.cli.guidance_audit
    python -m app.cli.guidance_audit --strict
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from app.core.logging import get_logger
from app.services.knowledge import load_seed

logger = get_logger(__name__)

#: The versioned snapshot of the detectors the engine can emit.
CATALOGUE_PATH = Path(__file__).resolve().parent.parent / "data" / "slither_detectors.json"


def load_catalogue() -> list[dict[str, Any]]:
    """The detectors the engine can emit, as the snapshot records them."""
    if not CATALOGUE_PATH.exists():
        return []
    raw = json.loads(CATALOGUE_PATH.read_text(encoding="utf-8"))
    detectors = raw.get("detectors") if isinstance(raw, dict) else raw
    if not isinstance(detectors, list):
        raise ValueError(f"{CATALOGUE_PATH} does not hold a list of detectors")
    return [d for d in detectors if isinstance(d, dict)]


def build_report() -> dict[str, Any]:
    """The coverage of the catalogue, and the names that do not add up.

    Returns:
        A report with the catalogue size, how many of its detectors have
        guidance, the ones that do not, and the guidance entries that
        name no known detector.
    """
    catalogue = load_catalogue()
    known = {str(d.get("detector_id") or "") for d in catalogue}
    known.discard("")
    seed = load_seed()

    missing = sorted(known - set(seed))
    unknown = sorted(
        detector_id
        for detector_id in seed
        if detector_id.startswith("slither.") and detector_id not in known
    )
    with_guidance = len(known & set(seed))
    return {
        "catalogue": len(known),
        "with_guidance": with_guidance,
        "coverage": f"{with_guidance}/{len(known)}",
        "missing": missing,
        "unknown": unknown,
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Print the report.

    Args:
        argv: The arguments; `None` reads the process arguments.

    Returns:
        `1` in strict mode when the catalogue is not fully covered,
        `0` otherwise.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero when a catalogue detector has no guidance.",
    )
    args = parser.parse_args(argv)

    report = build_report()
    print(json.dumps(report, indent=2))
    if args.strict and (report["missing"] or report["unknown"]):
        logger.warning("guidance_audit_incomplete", extra={"report": report})
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - the entry point
    sys.exit(main())
