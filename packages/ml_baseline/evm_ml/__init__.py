"""CyberStratum ML baseline.

A scikit-learn TF-IDF baseline over decoded opcode n-grams, with
deterministic control-flow-graph features, multi-label one-vs-rest linear
classifiers, and a versioned model artifact manifest.

Design doc section 23.2 requires a model adapter interface so that a
future GNN can be swapped in without changing the API contracts, and
requires that the scanner still runs with ML disabled.
"""

from __future__ import annotations

__version__ = "0.1.0"

from .dataset import (
    LABEL_CATEGORIES,
    Dataset,
    Sample,
    assign_split,
    load_dataset,
    split_dataset,
)
from .evaluate import CategoryMetrics, EvaluationReport, evaluate, latency_profile
from .features import FeatureBuilder, FeatureConfig, GraphFeature
from .manifest import ArtifactManifest
from .model import (
    ModelAdapter,
    SklearnTfidfAdapter,
    load_adapter,
    save_adapter,
    train_adapter,
)
from .modelcard import render_model_card
from .tokenize import Normalization, TokenStream, build_ngrams, tokenize

__all__ = [
    "ArtifactManifest",
    "CategoryMetrics",
    "Dataset",
    "EvaluationReport",
    "FeatureBuilder",
    "FeatureConfig",
    "GraphFeature",
    "LABEL_CATEGORIES",
    "ModelAdapter",
    "Normalization",
    "Sample",
    "SklearnTfidfAdapter",
    "TokenStream",
    "assign_split",
    "build_ngrams",
    "evaluate",
    "latency_profile",
    "load_adapter",
    "load_dataset",
    "render_model_card",
    "save_adapter",
    "split_dataset",
    "tokenize",
    "train_adapter",
]
