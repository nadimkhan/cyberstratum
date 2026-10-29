"""CyberStratum dataset ingestion.

Licensing-safe, reproducible ingestion for the CyberStratum smart-contract
security platform, implementing ADR-0015:

* per-dataset licence and provenance records, including the
  per-repository audit case (Web3Bugs);
* explicit label tiers, where an unknown label is ``unlabelled`` and never
  a negative;
* three-tier deduplication (exact, normalised, near-duplicate);
* deterministic family assignment and family-level splits, so no family
  ever straddles the train/test boundary;
* immutable, content-addressed dataset manifests;
* a promotion gate that only lets reviewed labels through.
"""

from __future__ import annotations

__version__ = "0.1.0"

from .dedup import (
    DeduplicationResult,
    DedupTier,
    cluster_near_duplicates,
    deduplicate,
    exact_hash,
    near_duplicate_hash,
    normalise_source,
    normalised_hash,
)
from .family import assign_family_key, family_source_shape
from .labels import (
    LabelTier,
    is_unknown_label,
    label_tier_for,
    may_be_used_as_evaluation_ground_truth,
    may_be_used_as_negative,
    may_be_used_for_exploratory_training,
)
from .licensing import (
    KNOWN_DATASET_LICENCES,
    DatasetLicense,
    DatasetProvenance,
    license_for,
    per_repository_audit_required,
)
from .loader import load_jsonl, parse_record, records_to_jsonl
from .manifest import (
    DatasetManifest,
    ManifestVerification,
    build_manifest,
    canonical_json,
    manifest_content_hash,
    verify_manifest,
)
from .promotion import PromotionDecision, can_promote
from .records import DatasetRecord
from .smoke import smoke_records
from .split import FamilySplit, SplitError, split_by_family

__all__ = [
    "DatasetLicense",
    "DatasetManifest",
    "DatasetProvenance",
    "DatasetRecord",
    "DedupTier",
    "DeduplicationResult",
    "FamilySplit",
    "KNOWN_DATASET_LICENCES",
    "LabelTier",
    "ManifestVerification",
    "PromotionDecision",
    "SplitError",
    "assign_family_key",
    "build_manifest",
    "can_promote",
    "canonical_json",
    "cluster_near_duplicates",
    "deduplicate",
    "exact_hash",
    "family_source_shape",
    "is_unknown_label",
    "label_tier_for",
    "license_for",
    "load_jsonl",
    "manifest_content_hash",
    "may_be_used_as_evaluation_ground_truth",
    "may_be_used_as_negative",
    "may_be_used_for_exploratory_training",
    "near_duplicate_hash",
    "normalise_source",
    "normalised_hash",
    "parse_record",
    "per_repository_audit_required",
    "records_to_jsonl",
    "smoke_records",
    "split_by_family",
    "verify_manifest",
]
