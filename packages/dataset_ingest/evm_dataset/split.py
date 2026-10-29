"""Family-level splitting.

ADR-0015 step 6: "split by family, never by record. A variant of a
training example can never appear in the test set."

The sibling ML baseline (``evm_ml.dataset``) hashes a *family name* into a
split bucket. This module uses the same family-level semantics - the unit
of assignment is a family, so leakage is structurally impossible - but
adds an explicit ratio-driven allocation and a seed, so that a corpus
whose family names do not hash uniformly still gets the split sizes the
caller asked for.

Determinism: the order in which families are considered is derived from
``sha256(seed || family_key)``. The same seed and the same records always
produce the same split, on any machine, in any process.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Final

from .family import assign_family_key
from .records import DatasetRecord

__all__ = [
    "DEFAULT_RATIOS",
    "FamilySplit",
    "SPLIT_NAMES",
    "split_by_family",
    "split_of",
]


#: Canonical split names, in the order they are reported.
SPLIT_NAMES: Final[tuple[str, ...]] = ("train", "validation", "test")

#: Default family ratios: 70/15/15.
DEFAULT_RATIOS: Final[tuple[float, float, float]] = (0.7, 0.15, 0.15)


class SplitError(ValueError):
    """Raised when a split cannot be produced without leaking or losing data."""


@dataclass(frozen=True)
class FamilySplit:
    """The result of a family-level split."""

    train: tuple[DatasetRecord, ...] = ()
    validation: tuple[DatasetRecord, ...] = ()
    test: tuple[DatasetRecord, ...] = ()
    family_to_split: dict[str, str] = field(default_factory=dict)
    seed: int = 0
    ratios: tuple[float, float, float] = DEFAULT_RATIOS

    def by_name(self) -> dict[str, tuple[DatasetRecord, ...]]:
        """Return the three splits keyed by name."""
        return {
            "train": self.train,
            "validation": self.validation,
            "test": self.test,
        }

    def record_ids(self) -> dict[str, tuple[str, ...]]:
        """Return the record ids of each split, keyed by split name."""
        return {
            name: tuple(record.record_id for record in records)
            for name, records in self.by_name().items()
        }

    def split_for_record(self, record_id: str) -> str:
        """Return the split a record landed in.

        Raises:
            KeyError: if the record is not part of this split.
        """
        for name, records in self.by_name().items():
            if any(record.record_id == record_id for record in records):
                return name
        raise KeyError(f"record {record_id!r} is not part of this split")


def split_of(family_to_split: dict[str, str], family_key: str) -> str:
    """Return the split a family was assigned to."""
    try:
        return family_to_split[family_key]
    except KeyError as exc:
        raise KeyError(f"unknown family key: {family_key!r}") from exc


def _family_order_key(seed: int, family_key: str) -> str:
    """A deterministic, seed-dependent ordering key for a family."""
    digest = hashlib.sha256(f"{seed}\x00{family_key}".encode()).hexdigest()
    return digest


def _target_counts(family_count: int, ratios: Sequence[float]) -> list[int]:
    """Split ``family_count`` families across the splits by largest remainder.

    Every split is guaranteed at least one family when there are enough
    families to go round. A corpus of exactly three families cannot
    honour a 70/15/15 ratio *and* keep all three splits non-empty; the
    non-empty guarantee wins, because an empty split is useless and the
    ratios are a target rather than a contract.
    """
    total = sum(ratios)
    if total <= 0:
        raise SplitError("split ratios must sum to a positive number")
    normalised = [ratio / total for ratio in ratios]

    exact = [family_count * ratio for ratio in normalised]
    counts = [int(value) for value in exact]
    remainder = family_count - sum(counts)
    # Largest fractional part first; ties broken by split order so the
    # allocation is deterministic.
    order = sorted(range(len(ratios)), key=lambda index: (-(exact[index] - counts[index]), index))
    for position in range(remainder):
        counts[order[position % len(order)]] += 1

    if family_count >= len(counts):
        for index, count in enumerate(counts):
            if count >= 1:
                continue
            donor = max(range(len(counts)), key=lambda position: (counts[position], -position))
            if counts[donor] > 1:
                counts[donor] -= 1
                counts[index] += 1
    return counts


def split_by_family(
    records: Iterable[DatasetRecord],
    ratios: Sequence[float] = DEFAULT_RATIOS,
    seed: int = 0,
) -> FamilySplit:
    """Split ``records`` by family.

    Every family lands in exactly one split, and therefore no two records
    of the same family can straddle the train/test boundary. The split is
    deterministic for a given seed and record set.

    Raises:
        SplitError: if there are too few families to fill every split, or
            if the ratios are unusable.
    """
    ordered = list(records)
    if len(ratios) != len(SPLIT_NAMES):
        raise SplitError(f"expected {len(SPLIT_NAMES)} ratios, got {len(ratios)}")
    if any(ratio < 0 for ratio in ratios):
        raise SplitError("split ratios must not be negative")

    families: dict[str, list[DatasetRecord]] = {}
    for record in ordered:
        families.setdefault(assign_family_key(record), []).append(record)

    if not families:
        raise SplitError("cannot split an empty record set")
    if len(families) < len(SPLIT_NAMES):
        raise SplitError(
            f"cannot split {len(families)} families into {len(SPLIT_NAMES)} "
            "non-empty splits; a family must never be shared between splits"
        )

    counts = _target_counts(len(families), ratios)
    for name, count in zip(SPLIT_NAMES, counts, strict=True):
        if count < 1:
            raise SplitError(f"split {name!r} would be empty; adjust the ratios")

    ordered_families = sorted(families, key=lambda key: (_family_order_key(seed, key), key))

    # Seed every split with one family so that no split can end up empty,
    # then fill the rest by largest remaining deficit.
    family_to_split: dict[str, str] = {}
    for name in SPLIT_NAMES:
        family_to_split[ordered_families[len(family_to_split)]] = name

    assigned = [1] * len(SPLIT_NAMES)
    for family_key in ordered_families[len(SPLIT_NAMES) :]:
        deficits = [counts[index] - assigned[index] for index in range(len(SPLIT_NAMES))]
        best = max(range(len(SPLIT_NAMES)), key=lambda index: (deficits[index], -index))
        family_to_split[family_key] = SPLIT_NAMES[best]
        assigned[best] += 1

    _assert_no_family_leakage(family_to_split)

    buckets: dict[str, list[DatasetRecord]] = {name: [] for name in SPLIT_NAMES}
    for family_key, family_records in families.items():
        buckets[family_to_split[family_key]].extend(family_records)

    split = FamilySplit(
        train=tuple(buckets["train"]),
        validation=tuple(buckets["validation"]),
        test=tuple(buckets["test"]),
        family_to_split=dict(family_to_split),
        seed=seed,
        ratios=tuple(ratios),  # type: ignore[arg-type]
    )
    _assert_every_record_once(split, ordered)
    return split


def _assert_no_family_leakage(family_to_split: dict[str, str]) -> None:
    """Assert that no family appears in two splits."""
    seen: dict[str, str] = {}
    for family_key, split_name in family_to_split.items():
        previous = seen.setdefault(family_key, split_name)
        assert previous == split_name, (
            f"family {family_key!r} leaked into {split_name!r} and {previous!r}"
        )


def _assert_every_record_once(split: FamilySplit, records: Sequence[DatasetRecord]) -> None:
    """Assert that the split covers every record exactly once."""
    seen: set[str] = set()
    for group in split.by_name().values():
        for record in group:
            assert record.record_id not in seen, (
                f"record {record.record_id!r} appears in more than one split"
            )
            seen.add(record.record_id)
    expected = {record.record_id for record in records}
    assert seen == expected, "split does not cover every record exactly once"
