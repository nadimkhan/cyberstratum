"""the guidance that says what to do about a finding

A detector reports a pattern. A reviewer needs to know what the pattern
means, why it matters, and what to change. A model can rank findings; it
cannot tell a developer how to fix a contract, and it must not pretend
to.

So the guidance is its own thing, stored per detector, and served
alongside the finding it explains. It is content, not code: the text
lives in a data file, and the table below is where it is served from.

The false-positive half matters as much as the fix half. ``delegatecall``
and ``tx.origin`` are patterns, not bugs; most occurrences of both are
fine. Recording *when* the pattern is not a problem is what lets a
reviewer decide quickly, and what lets the product say "this is
expected here" instead of crying wolf.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

__all__ = [
    "Guidance",
    "guidance_for",
    "load_seed",
]

#: The seed content, kept beside the code that serves it.
SEED_PATH = Path(__file__).resolve().parent.parent / "data" / "detector_guidance.json"


@dataclass(frozen=True)
class Guidance:
    """What a detector's finding means and what to do about it.

    Attributes:
        detector_id: The detector this guidance explains.
        title: A short name for the issue.
        what_it_means: What the pattern actually is.
        why_it_matters: The risk, and the conditions under which it is
            a risk.
        how_to_fix: What to change.
        false_positive_patterns: When the pattern is expected and the
            finding is not a problem.
        references: Where to read more.
        default_severity: The severity the detector reports by default.
        version: The guidance's own version, so a review can be traced
            to the advice that was in force when it was made.
    """

    detector_id: str
    title: str
    what_it_means: str
    why_it_matters: str
    how_to_fix: str
    false_positive_patterns: str
    references: str
    default_severity: str = "medium"
    version: str = "1"

    def as_dict(self) -> dict[str, Any]:
        """A JSON-friendly view."""
        return {
            "detector_id": self.detector_id,
            "title": self.title,
            "what_it_means": self.what_it_means,
            "why_it_matters": self.why_it_matters,
            "how_to_fix": self.how_to_fix,
            "false_positive_patterns": self.false_positive_patterns,
            "references": self.references,
            "default_severity": self.default_severity,
            "version": self.version,
        }


@lru_cache(maxsize=1)
def load_seed() -> dict[str, Guidance]:
    """Read the seed content.

    A malformed seed is a hard error: guidance that is half-read is
    worse than none, because it looks like advice.
    """
    if not SEED_PATH.exists():
        return {}
    raw = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    entries = raw.get("detectors") if isinstance(raw, dict) else raw
    if not isinstance(entries, list):
        raise ValueError(f"{SEED_PATH} does not hold a list of detectors")

    guidance: dict[str, Guidance] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError(f"{SEED_PATH} holds a non-object entry")
        detector_id = str(entry.get("detector_id") or "").strip()
        if not detector_id:
            raise ValueError(f"{SEED_PATH} holds an entry with no detector_id")
        guidance[detector_id] = Guidance(
            detector_id=detector_id,
            title=str(entry.get("title") or detector_id),
            what_it_means=str(entry.get("what_it_means") or ""),
            why_it_matters=str(entry.get("why_it_matters") or ""),
            how_to_fix=str(entry.get("how_to_fix") or ""),
            false_positive_patterns=str(entry.get("false_positive_patterns") or ""),
            references=str(entry.get("references") or ""),
            default_severity=str(entry.get("default_severity") or "medium"),
            version=str(entry.get("version") or "1"),
        )
    return guidance


def guidance_for(detector_id: str) -> Guidance | None:
    """The guidance for one detector, if there is any."""
    return load_seed().get(detector_id)
