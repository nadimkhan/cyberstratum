"""End-to-end tests for the ML baseline pipeline.

These tests assert *pipeline mechanics* only. The smoke fixture carries
structural heuristic labels on real bytecode and is far too small for its
metrics to mean anything, so no test here asserts a quality threshold.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from evm_ml import (
    ArtifactManifest,
    FeatureBuilder,
    FeatureConfig,
    load_adapter,
    load_dataset,
)
from evm_ml.evaluate import evaluate
from evm_ml.model import train_adapter
from evm_ml.train import run_training

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "dataset_smoke.jsonl"

LABELS = ["has_delegatecall", "has_selfdestruct", "has_origin", "large_control_flow"]


def test_transform_before_fit_is_refused():
    builder = FeatureBuilder(FeatureConfig())
    with pytest.raises(RuntimeError, match="must be fitted"):
        builder.transform([])


def test_the_builder_produces_a_feature_matrix():
    dataset = load_dataset(FIXTURE)
    samples = dataset.samples[:4]
    builder = FeatureBuilder(FeatureConfig())
    matrix = builder.fit(samples)
    assert matrix.shape[0] == len(samples)
    assert matrix.shape[1] > 0


def test_the_vocabulary_is_fitted_on_the_training_corpus_only():
    from evm_ml import Sample

    # The training contract contains only ADD (0x01); the held-out contract
    # contains only SUB (0x03). SUB must not appear in the fitted
    # vocabulary, because it was never seen while fitting.
    train = [Sample("train-1", "family-a", bytes.fromhex("01"), {})]
    held_out = [Sample("held-1", "family-b", bytes.fromhex("03"), {})]

    builder = FeatureBuilder(FeatureConfig())
    builder.fit(train)

    raw_terms = set(builder.vocabulary_summary()["raw_terms"])
    assert "ADD" in raw_terms
    assert "SUB" not in raw_terms

    # The held-out contract still transforms, using only known terms.
    matrix = builder.transform(held_out)
    assert matrix.shape[0] == 1


def test_transforming_an_unseen_contract_does_not_change_the_vocabulary():
    from evm_ml import Sample

    builder = FeatureBuilder(FeatureConfig())
    builder.fit([Sample("train-1", "family-a", bytes.fromhex("01"), {})])
    before = builder.vocabulary_summary()["raw_vocabulary_size"]

    builder.transform([Sample("held-1", "family-b", bytes.fromhex("030405"), {})])
    after = builder.vocabulary_summary()["raw_vocabulary_size"]
    assert before == after


def test_training_produces_probabilities_for_every_sample():
    dataset = load_dataset(FIXTURE)
    samples = dataset.samples
    builder = FeatureBuilder(FeatureConfig())
    adapter = train_adapter(builder, samples, LABELS)

    probabilities = adapter.predict_proba(samples)
    assert len(probabilities) == len(samples)
    for row in probabilities:
        assert set(row) == set(LABELS)
        for value in row.values():
            assert 0.0 <= value <= 1.0


def test_evaluation_reports_every_required_metric():
    dataset = load_dataset(FIXTURE)
    samples = dataset.samples
    builder = FeatureBuilder(FeatureConfig())
    adapter = train_adapter(builder, samples, LABELS)

    report = evaluate(samples, adapter.predict_proba(samples), LABELS)
    payload = report.as_dict()

    assert len(payload["categories"]) == len(LABELS)
    for metric in payload["categories"]:
        assert metric["precision"] is not None
        assert metric["recall"] is not None
        assert metric["f1"] is not None
        assert metric["brier"] is not None

    assert set(payload["false_positives_per_100_contracts"]) == set(LABELS)
    assert set(payload["recall_at_review_budget"]) == set(LABELS)
    assert "by_chain" in payload["breakdown"]
    assert "by_compiler" in payload["breakdown"]
    assert "by_family" in payload["breakdown"]
    assert "by_code_size" in payload["breakdown"]


def test_a_full_training_run_writes_the_artifact_and_the_manifest(tmp_path: Path):
    result = run_training(
        FIXTURE,
        tmp_path / "model",
        labels=LABELS,
    )

    manifest_path = Path(result["manifest"])
    assert manifest_path.exists()
    assert Path(result["model"]).exists()
    assert Path(result["model_card"]).exists()
    assert Path(result["evaluation"]).exists()

    manifest = ArtifactManifest.read(manifest_path)
    assert manifest.experimental is True
    assert manifest.adapter == "sklearn-tfidf"
    assert manifest.library_versions["scikit-learn"]
    assert manifest.tfidf_convention["smooth_idf"] is True
    assert manifest.vocabulary["raw_vocabulary_size"] > 0
    assert manifest.dataset["sample_count"] > 0
    assert manifest.split["strategy"]
    assert manifest.limitations

    card = Path(result["model_card"]).read_text(encoding="utf-8")
    assert "EXPERIMENTAL" in card
    assert "Limitations" in card


def test_the_manifest_records_the_split_fingerprint(tmp_path: Path):
    result = run_training(FIXTURE, tmp_path / "model", labels=LABELS)
    manifest = ArtifactManifest.read(result["manifest"])
    assert manifest.split["fingerprint"]
    assert manifest.split["train"]["contracts"] > 0


def test_a_missing_artifact_loads_as_none(tmp_path: Path):
    assert load_adapter(tmp_path / "does-not-exist") is None


def test_a_saved_adapter_round_trips(tmp_path: Path):
    result = run_training(FIXTURE, tmp_path / "model", labels=LABELS)
    adapter = load_adapter(Path(result["model"]).parent)
    assert adapter is not None

    dataset = load_dataset(FIXTURE)
    samples = dataset.samples[:3]
    probabilities = adapter.predict_proba(samples)
    assert len(probabilities) == 3


def test_the_evaluation_file_is_valid_json(tmp_path: Path):
    result = run_training(FIXTURE, tmp_path / "model", labels=LABELS)
    payload = json.loads(Path(result["evaluation"]).read_text(encoding="utf-8"))
    assert "validation" in payload
    assert "test" in payload
