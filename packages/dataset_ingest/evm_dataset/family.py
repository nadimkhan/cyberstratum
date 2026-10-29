"""Family assignment.

ADR-0015 step 5 requires every record to carry a ``family_key`` that
groups "exploits that are variants of the same root cause (same bug class
in the same protocol family, forks of one another)". Family grouping
happens *before* splitting, so that a fork of a training contract cannot
end up in the test set.

The key is derived from the record's identity - its protocol/project and
its bug class - and from the normalised source only when the upstream
data does not provide a bug class. The source text is deliberately
excluded whenever a bug class is known: a renamed variable or an added
comment must not split one exploit family into two, or the family split
quietly degrades into a record split and the test score becomes
meaningless.

The key is a pure function of the record: same record, same key, on every
machine and in every process.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Final

from .dedup import shape_tokens
from .records import DatasetRecord

__all__ = ["FAMILY_KEY_VERSION", "assign_family_key", "family_source_shape"]


#: Bump when the derivation changes, so old manifests stay interpretable.
FAMILY_KEY_VERSION: Final[str] = "family-key-v1"

_PROJECT_SUFFIX_RE: Final[re.Pattern[str]] = re.compile(
    r"(?:^|[-_/])(?:v?\d+(?:\.\d+)*|release|final|master|main|dev)$"
)


def _canonical(value: str) -> str:
    """Lower-case, strip, and drop a trailing version-ish suffix."""
    lowered = value.strip().lower()
    stripped = _PROJECT_SUFFIX_RE.sub("", lowered)
    return stripped or lowered


def family_source_shape(record: DatasetRecord) -> str:
    """A coarse, renaming-invariant shape of the record's source.

    Used as the family discriminator when the upstream data carries no
    bug class. Identifiers collapse to a single placeholder, so a renamed
    copy of a contract has the same shape.
    """
    return " ".join(shape_tokens(record.code))


def assign_family_key(record: DatasetRecord) -> str:
    """Return the deterministic family key for ``record``.

    The identity used, in order of preference:

    1. ``project`` plus the bug class (``swc_id``, then ``cwe_id``) -
       the protocol family plus the root cause;
    2. ``project`` plus the normalised source shape - used when the
       upstream data has no bug class;
    3. the normalised source shape alone - used when there is no project
       identity either, so that two unrelated records never collide.
    """
    project = _canonical(record.project)
    contract = _canonical(record.contract_name)
    bug_class = _canonical(record.swc_id or "") or _canonical(record.cwe_id or "")

    if project and bug_class:
        payload = {"version": FAMILY_KEY_VERSION, "project": project, "bug": bug_class}
    elif project:
        payload = {
            "version": FAMILY_KEY_VERSION,
            "project": project,
            "shape": family_source_shape(record),
        }
    else:
        payload = {
            "version": FAMILY_KEY_VERSION,
            "project": contract,
            "shape": family_source_shape(record),
        }

    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]
