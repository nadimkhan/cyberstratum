"""Export reviewed findings as training labels.

Where the labels come from
--------------------------

A machine learning model needs labels, and the only labels this product
trusts are the ones a person made: a finding was reviewed, the reviewer
said *confirmed* or *false positive*, and the reason was written down.
Everything else -- the smoke fixture's structural heuristics, a detector
that merely fired -- is not ground truth and does not belong in a
training set.

The rules
---------

* **A sample is a contract, not a finding.** A contract's labels are its
  categories; a category is about the contract, not about one detector
  firing.
* **A category is true when a finding in it was confirmed.**
* **A category is false only when every finding in it was reviewed as a
  false positive.** A finding nobody has reviewed makes the category
  *unknown*, and an unknown category keeps the contract out of the
  training set. Treating "not yet looked at" as "not vulnerable" is the
  mistake this whole product exists to avoid, and it would be absurd to
  make it in the training data.
* **A category with no finding at all is false.** The detector ran on
  this contract and did not report that category, which is evidence about
  *that detector*, and nothing more. The manifest says so in as many
  words: these labels record what the review concluded about a detector's
  finding, not the presence or absence of the vulnerability itself.
* **A detector outside the vocabulary is ignored, not disqualifying.**
  Some detectors report things that are not vulnerability classes at all
  -- a stack-depth anomaly, an unresolved jump. They have no category, so
  they cannot carry a label, and a reviewer who settled one of them has
  still said nothing about the categories. Letting them disqualify a
  contract would empty the dataset for no gain.
* **The family is the bytecode hash.** Exact clones group together, so
  one clone cannot sit on both sides of the split. Near clones -- the
  same project deployed with different bytecode -- do not group yet, and
  the manifest says that too, because a manifest that hides its own
  weakness is worse than no manifest.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.enums import FindingStatus
from app.db.models.scans import Finding, Scan, ScanArtifact

__all__ = [
    "DETECTOR_CATEGORIES",
    "LabelExport",
    "build_records",
    "write_dataset",
]

#: Which detector speaks for which label category.
#:
#: A detector with no entry here cannot contribute a label: the review
#: of its finding is still recorded in the database, but the export
#: cannot say which category it belongs to, and guessing would put a
#: wrong label into a training set.
DETECTOR_CATEGORIES: dict[str, str] = {
    "baseline.call_before_state_write": "reentrancy",
    "baseline.delegatecall": "unchecked_call",
    "baseline.selfdestruct": "selfdestruct",
    "baseline.tx_origin": "tx_origin",
}

#: The label categories the model is trained over.
LABEL_CATEGORIES: tuple[str, ...] = (
    "reentrancy",
    "access_control",
    "unchecked_call",
    "selfdestruct",
    "tx_origin",
    "uninitialized_storage",
)


@dataclass
class LabelExport:
    """What the export produced.

    Attributes:
        records: The dataset records, one per contract.
        skipped_unsettled: Contracts excluded because a category had an
            unreviewed finding.
        ignored_unmapped: Findings from detectors outside the label
            vocabulary. They carry no category, so they say nothing about
            the labels and do not disqualify the contract.
        skipped_no_bytecode: Contracts excluded because their bytecode
            could not be read back.
        chains: The chains the samples came from.
    """

    records: list[dict[str, Any]] = field(default_factory=list)
    skipped_unsettled: int = 0
    ignored_unmapped: int = 0
    skipped_no_bytecode: int = 0
    chains: set[str] = field(default_factory=set)

    def as_dict(self) -> dict[str, Any]:
        """A JSON-friendly summary, for the run log."""
        return {
            "records": len(self.records),
            "skipped_unsettled": self.skipped_unsettled,
            "ignored_unmapped": self.ignored_unmapped,
            "skipped_no_bytecode": self.skipped_no_bytecode,
            "chains": sorted(self.chains),
        }


def _family(bytecode: bytes) -> str:
    """The family a contract belongs to.

    Exact clones share their runtime bytecode, so its digest groups them.
    """
    return "code:" + hashlib.sha256(bytecode).hexdigest()[:16]


def _read_bytecode(session: Session, scan_id: Any, root: Path) -> bytes | None:
    """Read the runtime bytecode a scan stored."""
    artifact = session.execute(
        select(ScanArtifact).where(
            ScanArtifact.scan_id == scan_id,
            ScanArtifact.kind == "bytecode",
        )
    ).scalar_one_or_none()
    if artifact is None:
        return None
    path = root / artifact.object_key
    try:
        return path.read_bytes()
    except OSError:
        return None


def build_records(
    session: Session,
    *,
    storage_root: Path,
    limit: int | None = None,
) -> LabelExport:
    """Build the dataset records from the reviewed findings.

    Args:
        session: The database session.
        storage_root: Where scan artifacts are stored.
        limit: Stop after this many records.

    Returns:
        A :class:`LabelExport`.
    """
    export = LabelExport()

    scans = session.execute(
        select(Scan)
        .join(Finding, Finding.scan_id == Scan.id)
        .where(
            Finding.status.in_(
                [FindingStatus.CONFIRMED, FindingStatus.FALSE_POSITIVE]
            )
        )
        .distinct()
        .order_by(Scan.created_at.desc())
    ).scalars().all()

    for scan in scans:
        if limit is not None and len(export.records) >= limit:
            break

        findings = session.execute(
            select(Finding).where(Finding.scan_id == scan.id)
        ).scalars().all()
        if not findings:
            continue

        # What the review settled, and what it did not.
        settled: dict[str, bool] = {}
        unknown: set[str] = set()

        for finding in findings:
            category = DETECTOR_CATEGORIES.get(finding.detector_id)
            if category is None:
                # Outside the label vocabulary: it cannot carry a label
                # and it says nothing about the categories.
                export.ignored_unmapped += 1
                continue
            if finding.status is FindingStatus.CONFIRMED:
                settled[category] = True
            elif finding.status is FindingStatus.FALSE_POSITIVE:
                settled.setdefault(category, False)
            else:
                # Neither confirmed nor false positive: the category is
                # not settled, so it cannot be labelled.
                unknown.add(category)

        if unknown & set(settled):
            # A category has both a confirmed finding and an unsettled
            # one. The confirmed finding is enough to call it true.
            unknown -= set(settled)
        if unknown:
            export.skipped_unsettled += 1
            continue

        bytecode = _read_bytecode(session, scan.id, storage_root)
        if bytecode is None:
            export.skipped_no_bytecode += 1
            continue

        target = scan.target
        chain_name = target.chain.name if target and target.chain else "unknown"
        export.chains.add(chain_name)

        labels = {category: settled.get(category, False) for category in LABEL_CATEGORIES}
        export.records.append(
            {
                "contract_id": f"{chain_name}:{target.address}" if target else str(scan.id),
                "family": _family(bytecode),
                "chain": chain_name,
                "source": "cyberstratum-review",
                "license": "unknown (deployed contract code)",
                "label_source": "human-review",
                "label_confidence": "reviewed",
                "bytecode": bytecode.hex(),
                "labels": labels,
                "metadata": {
                    "scan_id": str(scan.id),
                    "reviewed_categories": sorted(settled),
                    "review_note_count": sum(
                        1 for f in findings if f.review_note
                    ),
                },
            }
        )

    return export


def write_dataset(export: LabelExport, path: Path, *, name: str = "reviewed-labels") -> Path:
    """Write the export as a JSON Lines dataset with a provenance header.

    The header is the first line, under ``__dataset__``, and says what
    the labels mean and what they do not. A dataset that cannot be
    audited is a dataset that cannot be trusted.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    header = {
        "__dataset__": {
            "name": name,
            "description": (
                "Contracts whose findings were reviewed by a person. A category "
                "is true when a finding in it was confirmed and false when the "
                "findings in it were reviewed as false positives. A category "
                "with no finding is false because the detector did not report "
                "it -- these labels describe the review of a detector's "
                "findings, not the presence or absence of a vulnerability."
            ),
            "provenance": {
                "source": "CyberStratum review queue",
                "license": "unknown (deployed contract code)",
                "label_policy": "human review with a recorded reason",
                "label_source": "human-review",
                "label_confidence": "reviewed",
                "family_policy": (
                    "the runtime bytecode digest, so exact clones group "
                    "together; near clones of one project do not group yet"
                ),
                "excluded": (
                    "contracts with an unreviewed finding in a category; "
                    "findings from detectors outside the label vocabulary "
                    "are ignored, because they carry no category"
                ),
            },
            "exported_at": datetime.now(UTC).isoformat(),
            **export.as_dict(),
        }
    }

    with path.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(header, sort_keys=True) + "\n")
        for record in export.records:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
    return path
