"""Ingesting one upstream dataset, or refusing it.

The rule is simple: a dataset is ingested only when the platform can
account for it. That means a licence that is settled, an upstream
revision that pins the content, and a hash of the content itself. A
dataset that fails any of those is refused with a reason, and the
refusal is an error rather than a warning.

Nothing here decides whether a dataset's terms permit redistribution.
That decision is recorded elsewhere; this module only refuses what
cannot be accounted for.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from .licensing import (
    KNOWN_DATASET_LICENCES,
    DatasetLicense,
    DatasetProvenance,
    IngestRefusalError,
    require_ingestable,
)
from .manifest import DatasetManifest, build_manifest, dataset_content_sha256
from .records import DatasetRecord
from .split import DEFAULT_RATIOS

__all__ = ["ingest_dataset"]


def ingest_dataset(
    records: Iterable[DatasetRecord],
    *,
    dataset: str,
    dataset_license: DatasetLicense | None = None,
    upstream_revision: str | None = None,
    content_sha256: str | None = None,
    corpus_sha256: str | None = None,
    seed: int = 0,
    ratios: Sequence[float] = DEFAULT_RATIOS,
) -> DatasetManifest:
    """Ingest one upstream dataset into an immutable manifest.

    The licence, the pinned revision and the content hash are all
    required. The content hash is always computed from the records
    themselves, and that computed value is what the manifest carries and
    what :func:`~evm_dataset.manifest.verify_manifest` recomputes.

    ``content_sha256`` is an *assertion*: when it is given it must be the
    hash of these records, and a mismatch is a refusal rather than a
    note. ``corpus_sha256`` is the hash of the upstream corpus the
    records were parsed from; it is recorded in the manifest provenance so
    the manifest says which bytes were fetched, not only what came out of
    them.

    Raises:
        IngestRefusalError: when the dataset cannot be accounted for.
    """
    ordered = list(records)

    licence = dataset_license
    if licence is None:
        licence = KNOWN_DATASET_LICENCES.get(dataset)
    if licence is None:
        raise IngestRefusalError(dataset, "no licence is recorded for this dataset")

    for record in ordered:
        if record.source_dataset != dataset:
            raise IngestRefusalError(
                dataset,
                f"record {record.record_id!r} belongs to {record.source_dataset!r}",
            )

    revision = upstream_revision if upstream_revision is not None else licence.upstream_revision
    content_hash = dataset_content_sha256(ordered)
    if content_sha256 is not None and content_sha256 != content_hash:
        raise IngestRefusalError(
            dataset,
            "the recorded content hash does not match the content being ingested",
        )

    require_ingestable(
        dataset=dataset,
        dataset_license=licence,
        upstream_revision=revision,
        content_sha256=content_hash,
    )

    extra: dict[str, Any] = {"content_sha256": content_hash}
    if corpus_sha256 is not None:
        extra["corpus_sha256"] = corpus_sha256

    provenance = [
        DatasetProvenance(
            dataset=dataset,
            license=licence,
            source_ref=dataset,
            upstream_revision=revision,
            source_url=licence.upstream_url,
            extra=extra,
        )
    ]

    return build_manifest(
        ordered,
        provenance,
        seed=seed,
        ratios=ratios,
        content_hashes={dataset: content_hash},
    )
