"""Label tiers and the rule that an unknown label is never a negative.

ADR-0015 splits labels into three tiers. The tier that matters most for
this package is the one that says "we do not know". Web3Bugs ships rows
whose label is ``not-yet-determined``; SmartBugs-derived heuristics carry
no human confirmation at all. Treating either of those as a *negative*
label tells the model "this contract is fine", which is exactly the
poisoning failure ADR-0015 is written to prevent.

So the rule enforced here is deliberately blunt: a label that is missing,
empty, ``unknown`` or ``not-yet-determined`` maps to
:data:`LabelTier.UNLABELLED`, and no tier other than ``reviewed`` may be
used as a supervised negative.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final

__all__ = [
    "LabelTier",
    "UNKNOWN_LABEL_TOKENS",
    "is_unknown_label",
    "label_tier_for",
    "may_be_used_as_negative",
    "may_be_used_as_evaluation_ground_truth",
    "may_be_used_for_exploratory_training",
]


class LabelTier(StrEnum):
    """How much trust a label carries.

    The tiers are ordered by trust, not by usefulness for a benchmark:
    ``unlabelled`` is the safest label to hold and the least useful one.
    """

    HEURISTIC = "heuristic"
    REVIEWED = "reviewed"
    UNLABELLED = "unlabelled"


#: Raw label spellings that mean "no verdict has been reached".
#:
#: These are matched case-insensitively after stripping surrounding
#: whitespace and collapsing internal runs of whitespace.
UNKNOWN_LABEL_TOKENS: Final[frozenset[str]] = frozenset(
    {
        "",
        "-",
        "--",
        "?",
        "n/a",
        "na",
        "none",
        "null",
        "nil",
        "unknown",
        "undecided",
        "undetermined",
        "unreviewed",
        "unlabelled",
        "unlabeled",
        "not yet determined",
        "not yet known",
        "not-yet-determined",
        "not_yet_determined",
        "pending",
        "tbd",
        "to be determined",
        "to be reviewed",
    }
)

#: Provenance spellings that mean "a human confirmed this".
_REVIEWED_PROVENANCE: Final[frozenset[str]] = frozenset(
    {
        "reviewed",
        "human",
        "human reviewed",
        "human-reviewed",
        "manual",
        "analyst",
        "confirmed",
        "expert",
    }
)

#: Provenance spellings that mean "a transparent rule produced this".
_HEURISTIC_PROVENANCE: Final[frozenset[str]] = frozenset(
    {
        "heuristic",
        "rule",
        "rules",
        "rule based",
        "rule-based",
        "heuristic-rule",
        "heuristic rule",
        "pattern",
        "static analysis",
        "static-analysis",
        "pattern match",
    }
)

#: Provenance spellings that mean "nobody has looked at this yet".
#:
#: Model- and tool-generated findings are quarantined by ADR-0015. They are
#: mapped to ``unlabelled`` rather than to ``heuristic`` because a
#: heuristic label is at least backed by a recorded, auditable rule.
_QUARANTINED_PROVENANCE: Final[frozenset[str]] = frozenset(
    {
        "model",
        "llm",
        "tool",
        "automatic",
        "auto",
        "unreviewed",
        "quarantine",
        "quarantined",
        "self reported",
        "self-reported",
    }
)


def _normalise_token(value: object) -> str:
    """Lower-case, strip and collapse whitespace so spellings compare equal."""
    return " ".join(str(value).strip().lower().split())


def _provenance_head(provenance: str) -> str:
    """The leading token of a provenance string.

    Provenance is often recorded as ``"heuristic-rule:unchecked-lowlevel-call"``
    - a tier followed by the rule that produced the label. The tier is
    the head; the rule is recorded alongside it, not parsed out of it.
    """
    return _normalise_token(provenance).split(":", 1)[0].strip()


def is_unknown_label(raw_label: object) -> bool:
    """Return ``True`` when the raw label carries no verdict.

    ``None``, a non-string scalar that is not a recognised boolean, an
    empty string and any of :data:`UNKNOWN_LABEL_TOKENS` are unknown.
    """
    if raw_label is None:
        return True
    if isinstance(raw_label, bool):
        return False
    if isinstance(raw_label, (int, float)):
        # A bare number is not a verdict we understand.
        return True
    return _normalise_token(raw_label) in UNKNOWN_LABEL_TOKENS


def label_tier_for(
    raw_label: object,
    *,
    label_provenance: str | None = None,
) -> LabelTier:
    """Map a raw label plus its provenance onto a :class:`LabelTier`.

    The unknown-label rule wins over everything else: if the label itself
    is unknown, the result is ``unlabelled`` even when the provenance
    claims a human reviewed it. A reviewer cannot have confirmed a
    verdict that does not exist.

    When the label *is* known, the provenance decides the tier. A missing
    provenance never yields ``reviewed`` - it yields ``heuristic``, which
    is usable for exploratory training but never for promotion.
    """
    if is_unknown_label(raw_label):
        return LabelTier.UNLABELLED

    provenance = _provenance_head(label_provenance) if label_provenance else ""
    if provenance in _REVIEWED_PROVENANCE:
        return LabelTier.REVIEWED
    if provenance in _HEURISTIC_PROVENANCE:
        return LabelTier.HEURISTIC
    if provenance in _QUARANTINED_PROVENANCE:
        return LabelTier.UNLABELLED
    return LabelTier.HEURISTIC


def may_be_used_as_negative(tier: LabelTier) -> bool:
    """Return ``True`` only if the tier may act as a supervised negative.

    Only ``reviewed`` labels may. A heuristic label is a guess and an
    unlabelled record is an absence of information; using either as a
    negative is the poisoning failure ADR-0015 forbids.
    """
    return tier is LabelTier.REVIEWED


def may_be_used_for_exploratory_training(tier: LabelTier) -> bool:
    """Return ``True`` if the tier may be used to train an exploratory model.

    Heuristic labels are allowed here (with their rule recorded), which is
    exactly the tier the synthetic smoke dataset lives in.
    """
    return tier in (LabelTier.REVIEWED, LabelTier.HEURISTIC)


def may_be_used_as_evaluation_ground_truth(tier: LabelTier) -> bool:
    """Return ``True`` if the tier may be used as benchmark ground truth."""
    return tier is LabelTier.REVIEWED
