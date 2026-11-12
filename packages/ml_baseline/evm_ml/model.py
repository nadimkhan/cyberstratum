"""The model adapter interface and the scikit-learn TF-IDF implementation.

Design doc section 23.2 requires a model adapter interface so that
scikit-learn and a future GNN can be swapped without changing the API
contracts, and requires that the scanner still runs with ML disabled.

:func:`load_adapter` therefore returns ``None`` when no artifact is
available, and callers must treat ML as strictly optional.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.multiclass import OneVsRestClassifier

from .dataset import Sample
from .features import FeatureBuilder, FeatureConfig
from .manifest import ArtifactManifest, library_versions

__all__ = [
    "ModelAdapter",
    "SklearnTfidfAdapter",
    "load_adapter",
    "save_adapter",
]


@runtime_checkable
class ModelAdapter(Protocol):
    """The interface every model implementation must satisfy."""

    name: str
    version: str

    def predict_proba(self, samples: list[Sample]) -> list[dict[str, float]]:
        """Return per-category probabilities for each sample.

        The result is a list with one dictionary per input sample, keyed by
        label category. A category that the model was not trained on is
        omitted rather than reported as zero, so that a caller cannot
        mistake "not modelled" for "modelled and found clean".
        """
        ...


@dataclass
class SklearnTfidfAdapter:
    """The TF-IDF baseline: one linear model per vulnerability category.

    The design doc requires multiple independent labels per contract, so
    the categories are modelled one-vs-rest rather than as a single
    multiclass target.
    """

    builder: FeatureBuilder
    classifier: OneVsRestClassifier
    labels: list[str]
    manifest: ArtifactManifest
    name: str = "sklearn-tfidf"
    version: str = "0.1.0"

    def predict_proba(self, samples: list[Sample]) -> list[dict[str, float]]:
        if not samples:
            return []
        matrix = self.builder.transform(samples)
        probabilities = self.classifier.predict_proba(matrix)
        results: list[dict[str, float]] = []
        for row in probabilities:
            results.append({label: float(row[index]) for index, label in enumerate(self.labels)})
        return results

    def predict_proba_matrix(self, samples: list[Sample]) -> np.ndarray:
        """The raw probability matrix, in ``self.labels`` order."""
        matrix = self.builder.transform(samples)
        probabilities: np.ndarray = self.classifier.predict_proba(matrix)
        return probabilities


def train_adapter(
    builder: FeatureBuilder,
    train_samples: list[Sample],
    labels: list[str],
    *,
    hyperparameters: dict[str, Any] | None = None,
) -> SklearnTfidfAdapter:
    """Fit the one-vs-rest classifier over the training corpus."""
    matrix = builder.fit(train_samples)
    y = np.array(
        [
            [1 if sample.labels.get(label, False) else 0 for label in labels]
            for sample in train_samples
        ],
        dtype=np.int64,
    )

    params: dict[str, Any] = {
        "estimator": LogisticRegression(
            max_iter=2000,
            class_weight="balanced",
            solver="liblinear",
            random_state=0,
        ),
        "n_jobs": 1,
    }
    params.update(hyperparameters or {})

    classifier = OneVsRestClassifier(**params)
    classifier.fit(matrix, y)

    return SklearnTfidfAdapter(
        builder=builder,
        classifier=classifier,
        labels=list(labels),
        manifest=ArtifactManifest(
            adapter="sklearn-tfidf",
            library_versions=library_versions(),
        ),
    )


def save_adapter(directory: str | Path, adapter: SklearnTfidfAdapter) -> dict[str, str]:
    """Write the model artifact and its manifest to a directory.

    The artifact holds the fitted vectorizers, the classifier and the
    manifest, so that inference never has to re-fit anything.
    """
    import joblib

    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)

    model_path = directory / "model.joblib"
    joblib.dump(
        {
            "builder": adapter.builder,
            "classifier": adapter.classifier,
            "labels": adapter.labels,
            "manifest": adapter.manifest.to_dict(),
            "name": adapter.name,
            "version": adapter.version,
        },
        model_path,
        compress=3,
    )

    manifest_path = directory / "manifest.json"
    adapter.manifest.write(manifest_path)

    return {
        "model": str(model_path),
        "manifest": str(manifest_path),
    }


def load_adapter(directory: str | Path) -> SklearnTfidfAdapter | None:
    """Load a saved adapter, or ``None`` when no artifact is present.

    Returning ``None`` is what keeps the scanner runnable with ML
    disabled: a missing artifact is not an error.
    """
    import joblib

    directory = Path(directory)
    model_path = directory / "model.joblib"
    manifest_path = directory / "manifest.json"

    if not model_path.exists() or not manifest_path.exists():
        return None

    payload = joblib.load(model_path)
    manifest = ArtifactManifest.from_dict(payload.get("manifest", {}))
    if manifest_path.exists():
        # Prefer the on-disk manifest: it is the auditable copy.
        manifest = ArtifactManifest.read(manifest_path)

    builder = payload["builder"]
    if not isinstance(builder, FeatureBuilder):
        builder = FeatureBuilder(FeatureConfig(**manifest.feature_config.get("config", {})))

    return SklearnTfidfAdapter(
        builder=builder,
        classifier=payload["classifier"],
        labels=list(payload["labels"]),
        manifest=manifest,
        name=payload.get("name", "sklearn-tfidf"),
        version=payload.get("version", "0.1.0"),
    )


def describe_manifest(manifest: ArtifactManifest) -> str:
    """A short human-readable summary of a manifest."""
    payload = json.dumps(manifest.to_dict(), indent=2, sort_keys=True)
    return payload
