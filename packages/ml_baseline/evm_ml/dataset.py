"""Dataset loading, provenance and family-level splitting.

Design doc section 13.1 requires every sample to carry its source,
licence/permission, contract/project family, chain, compiler metadata,
label source and label confidence. Section 6.2 additionally requires the
train/test split to be made at contract/project/family level rather than
by shuffling bytecode fragments, so that a single project's contracts
cannot appear on both sides of a split.

The split implemented here is deterministic: a family is assigned to a
split by hashing the family name. That makes the split reproducible
without depending on a random seed, and it makes leakage structurally
impossible - a family lands in exactly one split, always.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Literal

__all__ = [
    "Dataset",
    "Split",
    "Sample",
    "assign_split",
    "load_dataset",
    "split_dataset",
]

Split = Literal["train", "val", "test"]

#: Split boundaries, in percent of families. The remainder goes to test.
_TRAIN_PERCENT: Final[int] = 70
_VAL_PERCENT: Final[int] = 85

#: Canonical label categories. A contract may carry several labels.
LABEL_CATEGORIES: Final[tuple[str, ...]] = (
    "reentrancy",
    "access_control",
    "unchecked_call",
    "selfdestruct",
    "tx_origin",
    "uninitialized_storage",
)


@dataclass(frozen=True)
class Sample:
    """A single labelled contract."""

    contract_id: str
    family: str
    bytecode: bytes
    labels: dict[str, bool]
    chain: str = "unknown"
    compiler: str | None = None
    source: str = "unknown"
    license: str = "unknown"
    label_source: str = "unknown"
    label_confidence: str = "unknown"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        """A JSON-serialisable record, used for the dataset manifest."""
        return {
            "contract_id": self.contract_id,
            "family": self.family,
            "chain": self.chain,
            "compiler": self.compiler,
            "source": self.source,
            "license": self.license,
            "label_source": self.label_source,
            "label_confidence": self.label_confidence,
            "labels": dict(self.labels),
            "code_sha256": hashlib.sha256(self.bytecode).hexdigest(),
            "code_size": len(self.bytecode),
            "metadata": dict(self.metadata),
        }


@dataclass
class Dataset:
    """A collection of samples plus its provenance."""

    samples: list[Sample]
    name: str = "unnamed"
    description: str = ""
    provenance: dict[str, Any] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.samples)

    def __iter__(self) -> Iterable[Sample]:
        return iter(self.samples)

    def manifest(self) -> dict[str, Any]:
        """The dataset manifest required by design doc section 13.1."""
        families = sorted({sample.family for sample in self.samples})
        return {
            "name": self.name,
            "description": self.description,
            "sample_count": len(self.samples),
            "family_count": len(families),
            "families": families,
            "chains": sorted({sample.chain for sample in self.samples}),
            "compilers": sorted(
                {s.compiler for s in self.samples if s.compiler is not None}
            ),
            "sources": sorted({sample.source for sample in self.samples}),
            "licenses": sorted({sample.license for sample in self.samples}),
            "label_sources": sorted({sample.label_source for sample in self.samples}),
            "label_confidences": sorted({sample.label_confidence for sample in self.samples}),
            "label_categories": list(LABEL_CATEGORIES),
            "samples": [sample.to_record() for sample in self.samples],
            "provenance": dict(self.provenance),
        }

    def fingerprint(self) -> str:
        """A stable hash of the dataset content.

        Used in the model artifact manifest so that a model can be tied to
        the exact data it was trained on.
        """
        digest = hashlib.sha256()
        for sample in sorted(self.samples, key=lambda s: s.contract_id):
            digest.update(sample.contract_id.encode("utf-8"))
            digest.update(b"\x00")
            digest.update(sample.family.encode("utf-8"))
            digest.update(b"\x00")
            digest.update(hashlib.sha256(sample.bytecode).digest())
            digest.update(b"\x00")
            for key in sorted(sample.labels):
                digest.update(key.encode("utf-8"))
                digest.update(b"1" if sample.labels[key] else b"0")
        return digest.hexdigest()


def assign_split(family: str) -> Split:
    """Assign a family to a split deterministically.

    The family name is hashed and the resulting byte is mapped onto the
    train/validation/test ranges. Because the input is the family and not
    the individual contract, every contract of a family always lands in the
    same split.
    """
    digest = hashlib.sha256(family.encode("utf-8")).digest()
    bucket = digest[0] % 100
    if bucket < _TRAIN_PERCENT:
        return "train"
    if bucket < _VAL_PERCENT:
        return "val"
    return "test"


def split_dataset(dataset: Dataset) -> dict[Split, list[Sample]]:
    """Split the dataset by family."""
    splits: dict[Split, list[Sample]] = {"train": [], "val": [], "test": []}
    for sample in dataset.samples:
        splits[assign_split(sample.family)].append(sample)
    return splits


def _parse_labels(raw: object) -> dict[str, bool]:
    if not isinstance(raw, dict):
        raise ValueError(f"labels must be an object, got {type(raw).__name__}")
    labels: dict[str, bool] = {}
    for key, value in raw.items():
        if not isinstance(value, bool):
            raise ValueError(f"label {key!r} must be a boolean, got {value!r}")
        labels[str(key)] = value
    return labels


def load_dataset(path: str | Path) -> Dataset:
    """Load a dataset from a JSON Lines file.

    Each line is a JSON object with at least ``contract_id``, ``family``
    and ``bytecode`` (hex, with or without a ``0x`` prefix). Labels are a
    flat object of category to boolean.

    The file may start with a header line holding dataset-level
    provenance under a ``__dataset__`` key.
    """
    path = Path(path)
    samples: list[Sample] = []
    provenance: dict[str, Any] = {}
    name = path.stem
    description = ""

    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: invalid JSON: {exc}") from exc

            if record.get("__dataset__") is not None:
                header = record["__dataset__"]
                provenance = dict(header.get("provenance", {}))
                name = str(header.get("name", name))
                description = str(header.get("description", description))
                continue

            for required in ("contract_id", "family", "bytecode"):
                if required not in record:
                    raise ValueError(f"{path}:{line_number}: missing {required!r}")

            bytecode_hex = str(record["bytecode"])
            if bytecode_hex.startswith(("0x", "0X")):
                bytecode_hex = bytecode_hex[2:]
            try:
                bytecode = bytes.fromhex(bytecode_hex)
            except ValueError as exc:
                raise ValueError(
                    f"{path}:{line_number}: bytecode is not valid hex: {exc}"
                ) from exc

            samples.append(
                Sample(
                    contract_id=str(record["contract_id"]),
                    family=str(record["family"]),
                    bytecode=bytecode,
                    labels=_parse_labels(record.get("labels", {})),
                    chain=str(record.get("chain", "unknown")),
                    compiler=record.get("compiler"),
                    source=str(record.get("source", "unknown")),
                    license=str(record.get("license", "unknown")),
                    label_source=str(record.get("label_source", "unknown")),
                    label_confidence=str(record.get("label_confidence", "unknown")),
                    metadata=dict(record.get("metadata", {})),
                )
            )

    return Dataset(
        samples=samples,
        name=name,
        description=description,
        provenance=provenance,
    )
