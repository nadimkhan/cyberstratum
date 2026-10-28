"""Train the TF-IDF vulnerability baseline.

Usage::

    python -m evm_ml.train --dataset data/dataset.jsonl --output artifacts/model-v1

The training run is reproducible: the split is derived from a hash of the
project family, the vectorizers are fitted on the training corpus only,
and every version, hash and metric is written into the model manifest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from .dataset import LABEL_CATEGORIES, Dataset, Sample, load_dataset, split_dataset
from .evaluate import evaluate, latency_profile
from .features import FeatureBuilder, FeatureConfig
from .manifest import ArtifactManifest, library_versions, now_iso
from .model import save_adapter, train_adapter
from .modelcard import render_model_card

__all__ = ["main", "run_training"]


#: The exact TF-IDF convention, recorded in the manifest as required by
#: design doc section 6.2.
TFIDF_CONVENTION: dict[str, Any] = {
    "library": "scikit-learn TfidfVectorizer",
    "term_frequency": "raw count, normalised by the L2 norm of the document vector",
    "inverse_document_frequency": "smooth_idf=True: log((1 + |D|) / (1 + df)) + 1",
    "sublinear_tf": False,
    "norm": "l2",
    "smooth_idf": True,
    "lowercase": False,
    "analyzer": "word",
    "token_pattern": "space-delimited opcode n-grams",
    "dtype": "float64",
    "applied_to": "two independent vocabularies: raw tokens and normalised tokens",
}


def _split_fingerprint(dataset: Dataset) -> str:
    digest = hashlib.sha256()
    for split, samples in sorted(split_dataset(dataset).items()):
        digest.update(split.encode("utf-8"))
        for sample in sorted(samples, key=lambda s: s.contract_id):
            digest.update(sample.contract_id.encode("utf-8"))
            digest.update(b"\x00")
    return digest.hexdigest()


def _predict(adapter: Any, samples: list[Sample]) -> list[dict[str, float]]:
    probabilities: list[dict[str, float]] = adapter.predict_proba(samples)
    return probabilities


def run_training(
    dataset_path: str | Path,
    output_dir: str | Path,
    *,
    fork: str = "cancun",
    ngram_min: int = 1,
    ngram_max: int = 3,
    labels: list[str] | None = None,
    threshold: float = 0.5,
) -> dict[str, Any]:
    """Run a full training run and write the artifact, manifest and card."""
    dataset = load_dataset(dataset_path)
    if not dataset.samples:
        raise ValueError("the dataset is empty")

    category_list = labels or list(LABEL_CATEGORIES)
    splits = split_dataset(dataset)

    train_samples = splits["train"]
    val_samples = splits["val"]
    test_samples = splits["test"]

    if not train_samples:
        raise ValueError(
            "the training split is empty; the dataset needs at least a few distinct families"
        )

    config = FeatureConfig(fork=fork, ngram_min=ngram_min, ngram_max=ngram_max)
    builder = FeatureBuilder(config)
    adapter = train_adapter(builder, train_samples, category_list)

    validation_report = (
        evaluate(
            val_samples,
            _predict(adapter, val_samples),
            category_list,
            threshold=threshold,
        )
        if val_samples
        else None
    )
    test_report = (
        evaluate(
            test_samples,
            _predict(adapter, test_samples),
            category_list,
            threshold=threshold,
        )
        if test_samples
        else None
    )

    if test_samples and test_report is not None:
        test_report.latency = latency_profile(
            lambda batch: _predict(adapter, batch), test_samples
        )

    vocabulary = builder.vocabulary_summary()
    # The term lists can be very large; the manifest records the size and a
    # hash, and the full vocabulary lives inside the fitted artifact.
    vocabulary_hash = hashlib.sha256(
        "\n".join(vocabulary["raw_terms"] + vocabulary["normalized_terms"]).encode("utf-8")
    ).hexdigest()
    vocabulary_manifest = {
        "raw_vocabulary_size": vocabulary["raw_vocabulary_size"],
        "normalized_vocabulary_size": vocabulary["normalized_vocabulary_size"],
        "terms_sha256": vocabulary_hash,
    }

    manifest = ArtifactManifest(
        model_id=dataset.name,
        model_version="0.1.0",
        created_at=now_iso(),
        adapter="sklearn-tfidf",
        experimental=True,
        library_versions=library_versions(),
        tfidf_convention=TFIDF_CONVENTION,
        feature_config={
            **config.as_dict(),
            "description": (
                "opcode n-grams over decoded instructions (raw and normalised "
                "views, fitted separately) plus deterministic control-flow-graph "
                "features"
            ),
        },
        vocabulary=vocabulary_manifest,
        dataset={
            "name": dataset.name,
            "description": dataset.description,
            "sample_count": len(dataset.samples),
            "family_count": len({s.family for s in dataset.samples}),
            "fingerprint": dataset.fingerprint(),
            "provenance": dataset.provenance,
        },
        split={
            "strategy": (
                "deterministic hash of the project family name; a family is "
                "never split across train/validation/test"
            ),
            "fingerprint": _split_fingerprint(dataset),
            "train": {
                "contracts": len(train_samples),
                "families": len({s.family for s in train_samples}),
            },
            "val": {
                "contracts": len(val_samples),
                "families": len({s.family for s in val_samples}),
            },
            "test": {
                "contracts": len(test_samples),
                "families": len({s.family for s in test_samples}),
            },
        },
        labels=category_list,
        hyperparameters={
            "classifier": "OneVsRestClassifier(LogisticRegression)",
            "solver": "liblinear",
            "class_weight": "balanced",
            "max_iter": 2000,
            "random_state": 0,
            "decision_threshold": threshold,
        },
        metrics={
            "validation": validation_report.as_dict() if validation_report else None,
            "test": test_report.as_dict() if test_report else None,
        },
        limitations=[
            "The baseline reads only the bytecode; it has no notion of source "
            "code, storage layout, or contract semantics.",
            "Opcode n-grams are a proxy for program structure; they can be "
            "evaded by compiler version changes or by minor source edits.",
            "The split is deterministic but small, so the confidence intervals "
            "around these metrics are wide.",
            "A positive prediction is a triage candidate, not a confirmed "
            "vulnerability, and every finding requires manual validation.",
            "Contracts from projects or compiler families absent from the "
            "training corpus are out of distribution.",
        ],
        notes=(
            "TF-IDF baseline over opcode n-grams with multi-label one-vs-rest "
            "linear models, plus deterministic control-flow-graph features."
        ),
    )

    output = Path(output_dir)
    paths = save_adapter(output, adapter)

    manifest_path = Path(paths["manifest"])
    manifest.write(manifest_path)

    card = render_model_card(manifest, validation_report, test_report)
    card_path = output / "MODEL_CARD.md"
    card_path.write_text(card, encoding="utf-8")

    report_path = output / "evaluation.json"
    report_path.write_text(
        json.dumps(
            {
                "validation": validation_report.as_dict() if validation_report else None,
                "test": test_report.as_dict() if test_report else None,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    return {
        "model": paths["model"],
        "manifest": str(manifest_path),
        "model_card": str(card_path),
        "evaluation": str(report_path),
        "split": manifest.split,
        "manifest_fingerprint": manifest.fingerprint(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="evm_ml.train", description="Train the CyberStratum TF-IDF baseline."
    )
    parser.add_argument("--dataset", required=True, help="Path to the dataset JSONL file.")
    parser.add_argument("--output", required=True, help="Directory for the model artifact.")
    parser.add_argument("--fork", default="cancun", help="EVM fork used for disassembly.")
    parser.add_argument("--ngram-min", type=int, default=1)
    parser.add_argument("--ngram-max", type=int, default=3)
    parser.add_argument(
        "--labels",
        default="",
        help="Comma-separated label categories. Defaults to the canonical set.",
    )
    parser.add_argument("--threshold", type=float, default=0.5)
    args = parser.parse_args(argv)

    labels = [item.strip() for item in args.labels.split(",") if item.strip()]

    result = run_training(
        args.dataset,
        args.output,
        fork=args.fork,
        ngram_min=args.ngram_min,
        ngram_max=args.ngram_max,
        labels=labels or None,
        threshold=args.threshold,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
