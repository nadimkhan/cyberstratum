"""The weakness taxonomy, and how each detector corresponds to it.

A detector says what pattern was found. A weakness class says what kind
of weakness that is, in a vocabulary other tools and other people also
use. The registry behind the classes is MIT licensed, frozen since 2020,
and says so itself; it is used here as a join key and never as current
guidance, and the severity this product reports for a finding still
comes from its own detectors.

Every correspondence says who is making the claim. Some are named by the
tool's own documentation; some are the identifier itself; the rest are
stated here, with the reason written down next to them. A detector with
no correspondence has no weakness class, and the product says that
rather than inventing one.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - a typing convenience only
    from app.schemas.findings import FindingRead

__all__ = [
    "SwcEntry",
    "correspondence_for",
    "load_correspondence",
    "load_taxonomy",
    "taxonomy",
    "taxonomy_provenance",
    "weakness_for",
]

#: The registry snapshot, kept beside the code that serves it.
SWC_PATH = Path(__file__).resolve().parent.parent / "data" / "swc_registry.json"

#: The detector-to-class correspondence.
CORRESPONDENCE_PATH = Path(__file__).resolve().parent.parent / "data" / "detector_weaknesses.json"


@dataclass(frozen=True)
class SwcEntry:
    """One weakness class from the registry.

    Attributes:
        swc_id: The canonical identifier, such as ``SWC-107``.
        title: The class name the registry gives it.
        severity: The registry's own severity, when it records one.
        cwe_ids: The CWE classes the registry relates it to.
        related_swc_ids: Other registry classes it relates to.
        path: Where the entry came from upstream.
        sha256: The hash of that upstream file, so it can be re-checked.
    """

    swc_id: str
    title: str
    severity: str | None
    cwe_ids: tuple[str, ...]
    related_swc_ids: tuple[str, ...]
    path: str
    sha256: str


@dataclass(frozen=True)
class Correspondence:
    """How one detector corresponds to a weakness class.

    Attributes:
        detector_id: The detector this correspondence is about.
        swc_ids: The classes it corresponds to.
        basis: Why the correspondence is what it is.
        source: Who is making the claim: the tool's documentation, the
            identifier itself, or CyberStratum.
    """

    detector_id: str
    swc_ids: tuple[str, ...]
    basis: str
    source: str


@lru_cache(maxsize=1)
def load_taxonomy() -> dict[str, SwcEntry]:
    """Return the registry's classes, keyed by identifier."""
    payload = json.loads(SWC_PATH.read_text(encoding="utf-8"))
    entries: dict[str, SwcEntry] = {}
    for row in payload.get("entries", []):
        entry = SwcEntry(
            swc_id=str(row.get("swc_id", "")),
            title=str(row.get("title", "")),
            severity=row.get("severity") or None,
            cwe_ids=tuple(row.get("cwe_ids", [])),
            related_swc_ids=tuple(row.get("related_swc_ids", [])),
            path=str(row.get("path", "")),
            sha256=str(row.get("sha256", "")),
        )
        if entry.swc_id:
            entries[entry.swc_id] = entry
    return entries


@lru_cache(maxsize=1)
def load_correspondence() -> dict[str, Correspondence]:
    """Return the detector correspondences, keyed by detector."""
    payload = json.loads(CORRESPONDENCE_PATH.read_text(encoding="utf-8"))
    rows: dict[str, Correspondence] = {}
    for row in payload.get("detectors", []):
        detector_id = str(row.get("detector_id", ""))
        if not detector_id:
            continue
        rows[detector_id] = Correspondence(
            detector_id=detector_id,
            swc_ids=tuple(row.get("swc_ids", [])),
            basis=str(row.get("basis", "")),
            source=str(row.get("source", "")),
        )
    return rows


def correspondence_for(detector_id: str) -> Correspondence | None:
    """Return the correspondence for a detector, or ``None``."""
    return load_correspondence().get(detector_id)


def weakness_for(detector_id: str) -> dict[str, Any] | None:
    """Return the weakness class for a detector, or ``None``.

    A detector that corresponds to several classes returns the first
    one, with the others listed in ``also``. Nothing is invented for a
    detector with no correspondence.
    """
    correspondence = load_correspondence().get(detector_id)
    if correspondence is None:
        return None
    classes = load_taxonomy()
    resolved = [(swc_id, classes[swc_id]) for swc_id in correspondence.swc_ids if swc_id in classes]
    if not resolved:
        return None
    primary_id, primary = resolved[0]
    return {
        "swc_id": primary.swc_id,
        "title": primary.title,
        "severity": primary.severity,
        "cwe_ids": list(primary.cwe_ids),
        "basis": correspondence.basis,
        "source": correspondence.source,
        "also": [
            {
                "swc_id": swc_id,
                "title": entry.title,
                "cwe_ids": list(entry.cwe_ids),
            }
            for swc_id, entry in resolved[1:]
        ],
    }


def taxonomy() -> list[dict[str, Any]]:
    """Every weakness class the registry holds."""
    return [
        {
            "swc_id": entry.swc_id,
            "title": entry.title,
            "severity": entry.severity,
            "cwe_ids": list(entry.cwe_ids),
            "related_swc_ids": list(entry.related_swc_ids),
        }
        for entry in sorted(load_taxonomy().values(), key=lambda item: item.swc_id)
    ]


def taxonomy_provenance() -> dict[str, Any]:
    """Where the taxonomy came from, and what it may be used for."""
    payload = json.loads(SWC_PATH.read_text(encoding="utf-8"))
    return {
        "dataset": payload.get("dataset", "swc_registry"),
        "spdx_id": payload.get("spdx_id", "MIT"),
        "license_url": payload.get("license_url", ""),
        "upstream_url": payload.get("upstream_url", ""),
        "upstream_revision": payload.get("upstream_revision", ""),
        "unmaintained": bool(payload.get("unmaintained", False)),
        "note": payload.get("unmaintained_note", ""),
        "entry_count": len(load_taxonomy()),
    }


def finding_read(row: object) -> FindingRead:
    """Return the API view of a finding, with its weakness class.

    The class is derived from the detector, so it is always the class
    the detector's correspondence says, and never a class stored beside
    the finding that could drift away from it.
    """
    from app.schemas.findings import FindingRead
    from app.schemas.weaknesses import WeaknessRead

    read = FindingRead.model_validate(row)
    weakness = weakness_for(read.detector_id)
    if weakness is None:
        return read
    return read.model_copy(update={"weakness": WeaknessRead.model_validate(weakness)})


def detectors_for_weakness(swc_id: str) -> list[str]:
    """The detectors that correspond to a weakness class.

    A class nobody's detector corresponds to has no detectors, and a
    list of findings for it is empty rather than every finding.
    """
    wanted = swc_id.strip().upper()
    return sorted(
        detector_id
        for detector_id, correspondence in load_correspondence().items()
        if wanted in correspondence.swc_ids
    )
