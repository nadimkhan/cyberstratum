"""The model promotion gate.

ADR-0015: "a candidate model becomes the served model only when it beats
the current model on the held-out family-split evaluation set..." and,
from the label-provenance section, a model trained on unreviewed or
heuristic labels must never be promoted - that is the self-poisoning
failure mode.

The gate therefore answers one question: *may a model trained on this
dataset snapshot be promoted to the served model?* It returns a
structured decision rather than a bare boolean, because a promotion
pipeline needs the reason and the counts for its audit trail, and
because a boolean cannot say "not yet, because 4 records are still
heuristic".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .labels import LabelTier
from .manifest import DatasetManifest

__all__ = ["PromotionDecision", "can_promote"]


@dataclass(frozen=True)
class PromotionDecision:
    """The outcome of the promotion gate."""

    allowed: bool
    reason: str
    reviewed_count: int = 0
    heuristic_count: int = 0
    unlabelled_count: int = 0
    total_count: int = 0
    blocking_tiers: tuple[str, ...] = ()
    details: dict[str, Any] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return self.allowed

    def to_dict(self) -> dict[str, Any]:
        """A JSON-serialisable view, used in the CLI output and audit logs."""
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "reviewed_count": self.reviewed_count,
            "heuristic_count": self.heuristic_count,
            "unlabelled_count": self.unlabelled_count,
            "total_count": self.total_count,
            "blocking_tiers": list(self.blocking_tiers),
            "details": dict(self.details),
        }


def can_promote(
    manifest: DatasetManifest,
    *,
    required_reviewed_records: int = 1,
    require_reproducible_split: bool = True,
) -> PromotionDecision:
    """Decide whether a model trained on ``manifest`` may be promoted.

    Promotion is permitted only from ``reviewed`` labels. A manifest
    containing heuristic or unlabelled records is refused, with the
    counts that caused the refusal.

    This does not stop heuristic data from being used for exploratory
    training - it only stops that model from being served.

    Raises:
        ValueError: if ``required_reviewed_records`` is negative.
    """
    if required_reviewed_records < 0:
        raise ValueError("required_reviewed_records must not be negative")

    counts = manifest.label_tier_counts
    reviewed = int(counts.get(LabelTier.REVIEWED.value, 0))
    heuristic = int(counts.get(LabelTier.HEURISTIC.value, 0))
    unlabelled = int(counts.get(LabelTier.UNLABELLED.value, 0))
    total = int(manifest.record_count)

    blocking: list[str] = []
    if heuristic:
        blocking.append(LabelTier.HEURISTIC.value)
    if unlabelled:
        blocking.append(LabelTier.UNLABELLED.value)

    details: dict[str, Any] = {
        "manifest_hash": manifest.content_hash,
        "split_counts": dict(manifest.split_counts),
        "family_count": manifest.family_count,
    }

    if blocking:
        return PromotionDecision(
            allowed=False,
            reason=(
                "promotion refused: the dataset contains labels that are not "
                f"human-reviewed ({', '.join(blocking)}); promotion is only "
                "permitted from reviewed labels"
            ),
            reviewed_count=reviewed,
            heuristic_count=heuristic,
            unlabelled_count=unlabelled,
            total_count=total,
            blocking_tiers=tuple(blocking),
            details=details,
        )

    if reviewed < required_reviewed_records:
        return PromotionDecision(
            allowed=False,
            reason=(
                f"promotion refused: only {reviewed} reviewed record(s) available, "
                f"{required_reviewed_records} required"
            ),
            reviewed_count=reviewed,
            heuristic_count=heuristic,
            unlabelled_count=unlabelled,
            total_count=total,
            details=details,
        )

    if require_reproducible_split and not manifest.content_hash:
        return PromotionDecision(
            allowed=False,
            reason=(
                "promotion refused: the manifest has no content hash, so the "
                "training run is not reproducible from the manifest"
            ),
            reviewed_count=reviewed,
            heuristic_count=heuristic,
            unlabelled_count=unlabelled,
            total_count=total,
            details=details,
        )

    return PromotionDecision(
        allowed=True,
        reason=(
            f"promotion permitted: {reviewed} reviewed record(s) across "
            f"{manifest.family_count} famil(y/ies); all labels are human-reviewed"
        ),
        reviewed_count=reviewed,
        heuristic_count=heuristic,
        unlabelled_count=unlabelled,
        total_count=total,
        blocking_tiers=(),
        details=details,
    )
