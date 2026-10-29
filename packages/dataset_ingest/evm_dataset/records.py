"""The canonical record type every ingested dataset is parsed into.

ADR-0015 fixes one schema for all sources so that a record from
SmartBugs and a record from Web3Bugs can be deduplicated, grouped into
families and split against each other. This module holds that schema and
nothing else; the ingestion-specific parsing lives in :mod:`loader`.

The record keeps the *raw* label exactly as the upstream dataset spelled
it, alongside the label's provenance. The tier is derived from those two
via :func:`evm_dataset.labels.label_tier_for` rather than being stored,
so a record can never claim a tier its content does not support.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .labels import LabelTier, label_tier_for

__all__ = ["DatasetRecord", "SplitName"]


#: The three dataset splits. Named as in ADR-0015 step 6.
SplitName = str


@dataclass(frozen=True)
class DatasetRecord:
    """One contract (or one contract variant) from one upstream dataset.

    ``code`` is the Solidity source when available. Bytecode-only records
    are still valid; the deduplication tiers then operate on whatever text
    is present.
    """

    record_id: str
    source_dataset: str
    source_ref: str
    code: str = ""
    project: str = ""
    contract_name: str = ""
    chain: str = "unknown"
    compiler_version: str | None = None
    swc_id: str | None = None
    cwe_id: str | None = None
    label: str | None = None
    label_provenance: str | None = None
    severity: str | None = None
    license: str | None = None
    upstream_revision: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def label_tier(self) -> LabelTier:
        """The tier this record's label falls into.

        Derived, never stored: a record whose raw label is
        ``not-yet-determined`` is ``unlabelled`` no matter what any
        upstream field claims.
        """
        return label_tier_for(self.label, label_provenance=self.label_provenance)

    @property
    def is_vulnerable(self) -> bool | None:
        """Return the boolean verdict, or ``None`` when it is unknown.

        ``None`` means "no verdict". It is deliberately not ``False``:
        an unknown label is not a negative label.
        """
        if self.label_tier is LabelTier.UNLABELLED:
            return None
        normalised = (self.label or "").strip().lower()
        if normalised in {"true", "vulnerable", "vuln", "yes", "1"}:
            return True
        if normalised in {"false", "benign", "safe", "no", "0"}:
            return False
        return None

    def to_dict(self) -> dict[str, Any]:
        """A JSON-serialisable view of the record."""
        return {
            "record_id": self.record_id,
            "source_dataset": self.source_dataset,
            "source_ref": self.source_ref,
            "code": self.code,
            "project": self.project,
            "contract_name": self.contract_name,
            "chain": self.chain,
            "compiler_version": self.compiler_version,
            "swc_id": self.swc_id,
            "cwe_id": self.cwe_id,
            "label": self.label,
            "label_provenance": self.label_provenance,
            "severity": self.severity,
            "license": self.license,
            "upstream_revision": self.upstream_revision,
            "label_tier": self.label_tier.value,
            "metadata": dict(self.metadata),
        }
