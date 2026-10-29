"""Immutable, content-addressed dataset manifests.

ADR-0015 step 7: "the manifest is content-addressed. Training runs
reference a manifest SHA; the manifest is never edited in place."

The manifest hash is a SHA-256 over a canonical JSON serialisation:
sorted keys, fixed separators, sorted record ids. Nothing that varies
between runs - no wall-clock timestamp, no random value, no absolute
filesystem path - takes part in the hash, so regenerating a manifest from
identical inputs yields a byte-identical hash.

The sibling ML baseline hashes its artifact manifest the same way
(``evm_ml.manifest.ArtifactManifest.fingerprint``); this module follows
that convention rather than inventing a second one.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

from .dedup import DeduplicationResult, deduplicate
from .family import assign_family_key
from .labels import LabelTier
from .licensing import KNOWN_DATASET_LICENCES, DatasetProvenance
from .records import DatasetRecord
from .split import DEFAULT_RATIOS, FamilySplit, split_by_family

__all__ = [
    "MANIFEST_VERSION",
    "DatasetManifest",
    "ManifestVerification",
    "build_manifest",
    "canonical_json",
    "manifest_content_hash",
    "verify_manifest",
]


#: Bump when the manifest layout changes incompatibly.
MANIFEST_VERSION: Final[int] = 1


def canonical_json(payload: Any) -> str:
    """Serialise ``payload`` canonically.

    Sorted keys, no insignificant whitespace, no ASCII escaping. This is
    the exact byte sequence the manifest hash is computed over.
    """
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def manifest_content_hash(payload: Any) -> str:
    """Return the SHA-256 of the canonical serialisation of ``payload``."""
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class DatasetManifest:
    """An immutable description of one ingested dataset snapshot."""

    manifest_version: int = MANIFEST_VERSION
    content_hash: str = ""
    record_count: int = 0
    family_count: int = 0
    split_counts: dict[str, int] = field(default_factory=dict)
    label_tier_counts: dict[str, int] = field(default_factory=dict)
    record_hashes: dict[str, str] = field(default_factory=dict)
    record_normalised_hashes: dict[str, str] = field(default_factory=dict)
    record_near_duplicate_hashes: dict[str, str] = field(default_factory=dict)
    record_clusters: dict[str, str] = field(default_factory=dict)
    family_assignment: dict[str, str] = field(default_factory=dict)
    split_assignment: dict[str, str] = field(default_factory=dict)
    provenance: list[dict[str, Any]] = field(default_factory=list)
    seed: int = 0
    ratios: tuple[float, float, float] = DEFAULT_RATIOS

    def to_dict(self) -> dict[str, Any]:
        """A JSON-serialisable view of the manifest."""
        return {
            "manifest_version": self.manifest_version,
            "content_hash": self.content_hash,
            "record_count": self.record_count,
            "family_count": self.family_count,
            "split_counts": dict(self.split_counts),
            "label_tier_counts": dict(self.label_tier_counts),
            "record_hashes": dict(self.record_hashes),
            "record_normalised_hashes": dict(self.record_normalised_hashes),
            "record_near_duplicate_hashes": dict(self.record_near_duplicate_hashes),
            "record_clusters": dict(self.record_clusters),
            "family_assignment": dict(self.family_assignment),
            "split_assignment": dict(self.split_assignment),
            "provenance": [dict(entry) for entry in self.provenance],
            "seed": self.seed,
            "ratios": list(self.ratios),
        }

    def content_payload(self) -> dict[str, Any]:
        """The payload the content hash is computed over.

        The hash itself is excluded - a manifest cannot contain its own
        hash.
        """
        payload = self.to_dict()
        payload.pop("content_hash")
        return payload


@dataclass(frozen=True)
class ManifestVerification:
    """The outcome of re-checking a manifest against its records."""

    matches: bool
    expected_hash: str
    actual_hash: str
    detail: str
    mismatched_records: tuple[str, ...] = ()

    def __bool__(self) -> bool:
        return self.matches


def _tier_counts(records: Sequence[DatasetRecord]) -> dict[str, int]:
    counts = {tier.value: 0 for tier in LabelTier}
    for record in records:
        counts[record.label_tier.value] += 1
    return counts


def _default_provenance() -> list[DatasetProvenance]:
    """One provenance entry per dataset licence the platform knows about.

    Every manifest carries the licence table, so a manifest read back
    later still states the terms the data was ingested under - and a
    licence that has not been resolved (Web3Bugs) is visible in the
    manifest rather than buried in the ingestion code.
    """
    return [
        DatasetProvenance(
            dataset=licence.dataset,
            license=licence,
            source_ref=licence.dataset,
            upstream_revision=licence.upstream_revision,
            source_url=licence.upstream_url,
        )
        for licence in sorted(KNOWN_DATASET_LICENCES.values(), key=lambda item: item.dataset)
    ]


def build_manifest(
    records: Iterable[DatasetRecord],
    provenance: Sequence[DatasetProvenance] | None = None,
    *,
    seed: int = 0,
    ratios: Sequence[float] = DEFAULT_RATIOS,
) -> DatasetManifest:
    """Build the immutable, content-addressed manifest for ``records``.

    The manifest records, for every record: its exact, normalised and
    near-duplicate hashes, its near-duplicate cluster, its family key and
    its split. It also records the per-dataset licence and provenance,
    the label-tier summary and the counts.

    Two calls with identical inputs produce an identical
    :attr:`DatasetManifest.content_hash`.
    """
    ordered = list(records)
    entries = list(provenance) if provenance is not None else _default_provenance()
    dedup_results: list[DeduplicationResult] = deduplicate(ordered)
    dedup_by_id = {result.record_id: result for result in dedup_results}

    split: FamilySplit = split_by_family(ordered, ratios=ratios, seed=seed)

    family_assignment = {record.record_id: assign_family_key(record) for record in ordered}
    split_assignment = {
        record.record_id: split.split_for_record(record.record_id) for record in ordered
    }

    manifest = DatasetManifest(
        record_count=len(ordered),
        family_count=len(split.family_to_split),
        split_counts={name: len(group) for name, group in split.by_name().items()},
        label_tier_counts=_tier_counts(ordered),
        record_hashes={record.record_id: dedup_by_id[record.record_id].exact for record in ordered},
        record_normalised_hashes={
            record.record_id: dedup_by_id[record.record_id].normalised for record in ordered
        },
        record_near_duplicate_hashes={
            record.record_id: dedup_by_id[record.record_id].near_duplicate for record in ordered
        },
        record_clusters={
            record.record_id: dedup_by_id[record.record_id].cluster_id for record in ordered
        },
        family_assignment=family_assignment,
        split_assignment=split_assignment,
        provenance=[entry.to_dict() for entry in entries],
        seed=seed,
        ratios=tuple(ratios),  # type: ignore[arg-type]
    )

    return DatasetManifest(
        **{
            **manifest.to_dict(),
            "content_hash": manifest_content_hash(manifest.content_payload()),
        }
    )


def verify_manifest(
    manifest: DatasetManifest,
    records: Iterable[DatasetRecord],
    provenance: Sequence[DatasetProvenance] | None = None,
) -> ManifestVerification:
    """Recompute the manifest from ``records`` and report whether it matches.

    A tampered record - a changed source, a changed label, a removed
    record - changes the recomputed hash and is reported here.
    """
    entries = (
        list(provenance)
        if provenance is not None
        else [DatasetProvenance.from_dict(entry) for entry in manifest.provenance]
    )
    recomputed = build_manifest(
        records,
        entries,
        seed=manifest.seed,
        ratios=manifest.ratios,
    )

    if recomputed.content_hash == manifest.content_hash:
        return ManifestVerification(
            matches=True,
            expected_hash=manifest.content_hash,
            actual_hash=recomputed.content_hash,
            detail="manifest matches the records it was built from",
        )

    mismatched: list[str] = []
    for record_id, expected_hash in manifest.record_hashes.items():
        actual_hash = recomputed.record_hashes.get(record_id)
        if actual_hash is None or actual_hash != expected_hash:
            mismatched.append(record_id)
    for record_id in recomputed.record_hashes:
        if record_id not in manifest.record_hashes:
            mismatched.append(record_id)

    detail = (
        f"manifest hash mismatch: expected {manifest.content_hash}, "
        f"recomputed {recomputed.content_hash}"
    )
    if mismatched:
        detail = f"{detail}; affected records: {', '.join(sorted(mismatched))}"

    return ManifestVerification(
        matches=False,
        expected_hash=manifest.content_hash,
        actual_hash=recomputed.content_hash,
        detail=detail,
        mismatched_records=tuple(sorted(mismatched)),
    )
