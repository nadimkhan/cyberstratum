"""The model artifact manifest.

Design doc section 23.2 requires that parser, ruleset, feature-schema and
model versions are pinned and recorded for every scan, and section 6.2
requires the exact TF-IDF convention and library version to be recorded in
the model artifact manifest.

This module defines that manifest as a plain, versioned JSON document. It
carries no secrets and no bytecode - only hashes, versions and metrics - so
it can be committed and audited.
"""

from __future__ import annotations

import hashlib
import json
import platform
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

__all__ = ["ArtifactManifest", "MANIFEST_VERSION", "library_versions"]


#: Bump when the manifest layout changes incompatibly.
MANIFEST_VERSION = 1


def library_versions() -> dict[str, str]:
    """The versions of the libraries that affect the model's behaviour."""
    import numpy
    import scipy
    import sklearn

    return {
        "python": platform.python_version(),
        "scikit-learn": sklearn.__version__,
        "numpy": numpy.__version__,
        "scipy": scipy.__version__,
    }


@dataclass
class ArtifactManifest:
    """The manifest stored alongside a trained model."""

    manifest_version: int = MANIFEST_VERSION
    model_id: str = ""
    model_version: str = ""
    created_at: str = ""
    adapter: str = ""
    experimental: bool = True
    library_versions: dict[str, str] = field(default_factory=dict)
    tfidf_convention: dict[str, Any] = field(default_factory=dict)
    feature_config: dict[str, Any] = field(default_factory=dict)
    vocabulary: dict[str, Any] = field(default_factory=dict)
    dataset: dict[str, Any] = field(default_factory=dict)
    split: dict[str, Any] = field(default_factory=dict)
    labels: list[str] = field(default_factory=list)
    hyperparameters: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    limitations: list[str] = field(default_factory=list)
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ArtifactManifest:
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in payload.items() if k in known})

    def fingerprint(self) -> str:
        """A stable hash of the manifest content, excluding the timestamp."""
        payload = self.to_dict()
        payload.pop("created_at", None)
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def write(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return path

    @classmethod
    def read(cls, path: str | Path) -> ArtifactManifest:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls.from_dict(payload)


def now_iso() -> str:
    """The current UTC time in ISO-8601 form."""
    return datetime.now(UTC).isoformat(timespec="seconds")
