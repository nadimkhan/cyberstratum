"""Per-dataset licence and provenance records.

Every dataset the platform ingests carries its own licence, and the
licences are not interchangeable: SmartBugs Curated and DeFiHackLabs are
Apache-2.0, the SWC Registry is MIT, and Web3Bugs is a per-repository
mixed bag that cannot be treated as one licence at all.

The licences live in a table (:data:`KNOWN_DATASET_LICENCES`) rather than
being hardcoded at the call sites, so that a new dataset is added by
editing data and so that "which licences does the platform know about?"
has a single, enumerable answer.

Web3Bugs is deliberately represented with a placeholder SPDX identifier
and ``per_repository_audit_required = True``: any code path that tries to
use it as a single licence is expected to refuse rather than silently
apply the wrong terms.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final

__all__ = [
    "DATASET_LICENCES",
    "DatasetLicense",
    "DatasetProvenance",
    "IngestRefusalError",
    "KNOWN_DATASET_LICENCES",
    "is_pinned_revision",
    "license_for",
    "per_repository_audit_required",
    "require_ingestable",
]


@dataclass(frozen=True)
class DatasetLicense:
    """The licence under which one upstream dataset is distributed.

    ``spdx_id`` is an SPDX-like identifier. For the per-repository audit
    case it is the explicit sentinel
    :data:`PER_REPOSITORY_AUDIT_SPDX` rather than a real licence, so
    that a consumer who forgets to check the audit flag still cannot
    resolve it to a concrete licence.
    """

    dataset: str
    spdx_id: str
    license_url: str
    upstream_url: str
    upstream_revision: str | None = None
    redistribution: str = "unspecified"
    derived_artifacts_may_be_redistributed: bool = False
    note: str = ""
    per_repository_audit_required: bool = False

    def __post_init__(self) -> None:
        if not self.note.strip():
            raise ValueError(f"licence record for {self.dataset!r} requires a human-readable note")

    @property
    def is_resolved(self) -> bool:
        """Return ``True`` when a single concrete licence covers the dataset."""
        return not self.per_repository_audit_required

    def to_dict(self) -> dict[str, object]:
        """A JSON-serialisable view, used inside the dataset manifest."""
        return {
            "dataset": self.dataset,
            "spdx_id": self.spdx_id,
            "license_url": self.license_url,
            "upstream_url": self.upstream_url,
            "upstream_revision": self.upstream_revision,
            "redistribution": self.redistribution,
            "derived_artifacts_may_be_redistributed": self.derived_artifacts_may_be_redistributed,
            "note": self.note,
            "per_repository_audit_required": self.per_repository_audit_required,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> DatasetLicense:
        """Rebuild a licence record from its serialised form.

        Used to re-verify a manifest that was loaded back from disk.
        """
        return cls(
            dataset=str(payload["dataset"]),
            spdx_id=str(payload["spdx_id"]),
            license_url=str(payload["license_url"]),
            upstream_url=str(payload["upstream_url"]),
            upstream_revision=(
                str(payload["upstream_revision"]) if payload.get("upstream_revision") else None
            ),
            redistribution=str(payload.get("redistribution", "unspecified")),
            derived_artifacts_may_be_redistributed=bool(
                payload.get("derived_artifacts_may_be_redistributed", False)
            ),
            note=str(payload.get("note", "")),
            per_repository_audit_required=bool(payload.get("per_repository_audit_required", False)),
        )


@dataclass(frozen=True)
class DatasetProvenance:
    """Where one ingested record came from, and under which licence.

    ADR-0015 requires the upstream repo, a pinned revision and the
    licence to be recorded per source file. A revision that is not pinned
    (a branch name, ``latest``, ``None``) is not reproducible, so
    ``upstream_revision`` is only meaningful when it is a tag or commit.
    """

    dataset: str
    license: DatasetLicense
    source_ref: str
    upstream_revision: str | None = None
    source_url: str | None = None
    extra: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.license.dataset != self.dataset:
            raise ValueError(
                f"provenance dataset {self.dataset!r} does not match licence "
                f"dataset {self.license.dataset!r}"
            )
        if not self.source_ref.strip():
            raise ValueError("provenance requires a non-empty source_ref")

    @property
    def is_usable(self) -> bool:
        """Return ``True`` when the licence terms are settled for this source."""
        return self.license.is_resolved

    def to_dict(self) -> dict[str, object]:
        """A JSON-serialisable view, used inside the dataset manifest."""
        return {
            "dataset": self.dataset,
            "source_ref": self.source_ref,
            "upstream_revision": self.upstream_revision,
            "source_url": self.source_url,
            "license": self.license.to_dict(),
            "extra": dict(self.extra),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> DatasetProvenance:
        """Rebuild a provenance record from its serialised form."""
        licence_payload = payload.get("license")
        if not isinstance(licence_payload, dict):
            raise ValueError("provenance payload is missing its licence record")
        extra_payload = payload.get("extra")
        extra = (
            {str(key): str(value) for key, value in extra_payload.items()}
            if isinstance(extra_payload, dict)
            else {}
        )
        return cls(
            dataset=str(payload["dataset"]),
            license=DatasetLicense.from_dict({str(k): v for k, v in licence_payload.items()}),
            source_ref=str(payload["source_ref"]),
            upstream_revision=(
                str(payload["upstream_revision"]) if payload.get("upstream_revision") else None
            ),
            source_url=str(payload["source_url"]) if payload.get("source_url") else None,
            extra=extra,
        )


#: The sentinel SPDX identifier used when a dataset has no single licence.
PER_REPOSITORY_AUDIT_SPDX: Final[str] = "LicenseRef-per-repository-audit-required"


_SMARTBUGS = DatasetLicense(
    dataset="smartbugs_curated",
    spdx_id="Apache-2.0",
    license_url="https://www.apache.org/licenses/LICENSE-2.0",
    upstream_url="https://github.com/smartbugs/smartbugs-curated",
    upstream_revision="230e649123477eff332742a59a1c7cc6dc286cab",
    redistribution="allowed-with-attribution",
    derived_artifacts_may_be_redistributed=True,
    note=(
        "Primary evaluation corpus. Pre-labelled with SWC and CWE identifiers. "
        "Apache-2.0 permits redistribution of derived artifacts with attribution. "
        "The revision is pinned to the commit the corpus was read from, so the "
        "corpus can be fetched, hashed and ingested."
    ),
)

_DEFIHACKLABS = DatasetLicense(
    dataset="defihacklabs",
    spdx_id="Apache-2.0",
    license_url="https://www.apache.org/licenses/LICENSE-2.0",
    upstream_url="https://github.com/SunWeb3Sec/DeFiHackLabs",
    upstream_revision=None,
    redistribution="allowed-with-attribution",
    derived_artifacts_may_be_redistributed=True,
    note=(
        "Real-world exploit proof-of-concepts. Used as a target corpus for recall "
        "measurement, not as a naively labelled training set. Apache-2.0. "
        "The upstream revision is not pinned yet, so an ingest of this dataset is "
        "refused until somebody pins it."
    ),
)

_SWC_REGISTRY = DatasetLicense(
    dataset="swc_registry",
    spdx_id="MIT",
    license_url="https://opensource.org/license/mit",
    upstream_url="https://github.com/SmartContractSecurity/SWC-registry",
    upstream_revision="1b6227074ecd180b374e4844153afdda0332f979",
    redistribution="allowed-with-attribution",
    derived_artifacts_may_be_redistributed=True,
    note=(
        "Weakness taxonomy and canonical identifiers, used as a join key rather "
        "than as a training set. MIT."
    ),
)

_WEB3BUGS = DatasetLicense(
    dataset="web3bugs",
    spdx_id=PER_REPOSITORY_AUDIT_SPDX,
    license_url="https://github.com/smarrara/Web3Bugs",
    upstream_url="https://github.com/smarrara/Web3Bugs",
    upstream_revision=None,
    redistribution="per-repository",
    note=(
        "Findings are true/false/not-yet-determined and licences vary per "
        "repository. Ingestion is only allowed after a per-repository licence "
        "and label-quality audit; until then this dataset has no single licence."
    ),
    per_repository_audit_required=True,
)

#: Every licence the platform knows about, keyed by dataset name.
KNOWN_DATASET_LICENCES: Final[dict[str, DatasetLicense]] = {
    license.dataset: license for license in (_SMARTBUGS, _DEFIHACKLABS, _SWC_REGISTRY, _WEB3BUGS)
}

#: Backwards-friendly alias.
DATASET_LICENCES: Final[dict[str, DatasetLicense]] = KNOWN_DATASET_LICENCES


def license_for(dataset: str) -> DatasetLicense:
    """Return the known licence record for ``dataset``.

    Raises:
        KeyError: if the dataset is not one the platform knows about. An
            unknown dataset must never silently inherit some other
            dataset's terms.
    """
    try:
        return KNOWN_DATASET_LICENCES[dataset]
    except KeyError as exc:
        raise KeyError(f"unknown dataset licence: {dataset!r}") from exc


def per_repository_audit_required(dataset: str) -> bool:
    """Return ``True`` when the dataset needs a per-repository audit."""
    return not license_for(dataset).is_resolved


#: Revision names that move over time, so they cannot pin a dataset.
MOVING_REVISIONS: Final[frozenset[str]] = frozenset(
    {"main", "master", "latest", "head", "trunk", "develop"}
)


class IngestRefusalError(ValueError):
    """Raised when an ingest cannot be accounted for.

    A dataset whose terms are not settled, whose upstream revision does
    not pin the content, or whose content has no hash is **refused**. It
    is not ingested with a warning, and it is never treated as
    permissive.
    """

    def __init__(self, dataset: str, reason: str) -> None:
        super().__init__(f"{dataset}: {reason}")
        self.dataset = dataset
        self.reason = reason


def is_pinned_revision(revision: str | None) -> bool:
    """Return ``True`` when the revision pins the content.

    A branch name such as ``main`` moves, so a corpus fetched from it
    cannot be reproduced and cannot be hashed meaningfully. A commit or a
    tag can.
    """
    if revision is None:
        return False
    text = revision.strip()
    if not text:
        return False
    return text.lower() not in MOVING_REVISIONS


def _is_sha256(value: str | None) -> bool:
    """Return ``True`` when the value is a SHA-256 in hex."""
    if not value:
        return False
    text = value.strip().lower()
    if len(text) != 64:
        return False
    return all(character in "0123456789abcdef" for character in text)


def require_ingestable(
    *,
    dataset: str,
    dataset_license: DatasetLicense | None = None,
    upstream_revision: str | None = None,
    content_sha256: str | None = None,
) -> DatasetLicense:
    """Refuse an ingest that cannot be accounted for.

    Returns the licence record when the ingest may proceed, and raises
    :class:`IngestRefusalError` with a reason when it may not.
    """
    if dataset_license is None:
        raise IngestRefusalError(dataset, "no licence is recorded for this dataset")
    if dataset_license.dataset != dataset:
        raise IngestRefusalError(
            dataset, f"the licence record belongs to {dataset_license.dataset!r}"
        )
    if not dataset_license.is_resolved:
        raise IngestRefusalError(
            dataset,
            "the licence is not settled: a per-repository audit is required",
        )
    if not is_pinned_revision(upstream_revision):
        raise IngestRefusalError(dataset, "the upstream revision is not pinned")
    if not _is_sha256(content_sha256):
        raise IngestRefusalError(dataset, "no content hash is recorded")
    return dataset_license
