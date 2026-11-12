"""The learning cycle installs a model only when the gate says it may."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.cli import learning_cycle
from app.services.label_export import LabelExport


def _export(records: int = 1) -> LabelExport:
    """An export with reviewed contracts in it."""
    return LabelExport(
        records=[
            {
                "contract_id": f"c{index}",
                "family": "code:abc",
                "bytecode": "6000",
                "labels": {"tx_origin": True},
            }
            for index in range(records)
        ],
        chains={"1"},
    )


def _trainer(promotable: bool):
    """A trainer that writes a candidate model and reports a gate verdict."""

    def train(dataset_path: str | Path, candidate_dir: str | Path) -> dict[str, Any]:
        candidate = Path(candidate_dir)
        candidate.mkdir(parents=True, exist_ok=True)
        (candidate / "model.joblib").write_bytes(b"model")
        (candidate / "manifest.json").write_text(
            json.dumps({"version": "v-test"}), encoding="utf-8"
        )
        return {
            "promotable": promotable,
            "gate_reason": "ok" if promotable else "precision 0.42 is below 0.80",
            "shipped_categories": ["tx_origin"] if promotable else [],
            "abstained_categories": [] if promotable else ["tx_origin"],
        }

    return train


def test_a_cycle_without_reviewed_labels_refuses_to_train(monkeypatch, tmp_path) -> None:
    """Nothing reviewed means nothing to learn from."""
    monkeypatch.setattr(learning_cycle, "build_records", lambda *a, **k: LabelExport())

    with pytest.raises(learning_cycle.NoReviewedLabelsError):
        learning_cycle.run_learning_cycle(workdir=tmp_path)


def test_a_model_that_fails_the_gate_is_not_installed(monkeypatch, tmp_path) -> None:
    """A model whose false positives were not measured stays on the shelf."""
    model_dir = tmp_path / "model"
    monkeypatch.setattr(learning_cycle, "build_records", lambda *a, **k: _export())
    monkeypatch.setattr(
        "app.services.model_manifest.model_directory", lambda settings=None: model_dir
    )

    outcome = learning_cycle.run_learning_cycle(
        workdir=tmp_path / "work", trainer=_trainer(False)
    )

    assert outcome.promotable is False
    assert outcome.installed is False
    assert outcome.shipped_categories == ()
    assert "precision" in outcome.gate_reason
    assert not (model_dir / "model.joblib").exists()


def test_a_model_that_passes_the_gate_is_installed(monkeypatch, tmp_path) -> None:
    """A model that passed the gate becomes the model the scanner uses."""
    model_dir = tmp_path / "model"
    monkeypatch.setattr(learning_cycle, "build_records", lambda *a, **k: _export())
    monkeypatch.setattr(
        "app.services.model_manifest.model_directory", lambda settings=None: model_dir
    )

    outcome = learning_cycle.run_learning_cycle(
        workdir=tmp_path / "work", trainer=_trainer(True)
    )

    assert outcome.promotable is True
    assert outcome.installed is True
    assert outcome.model_dir == str(model_dir)
    assert outcome.manifest_id == "v-test"
    assert outcome.shipped_categories == ("tx_origin",)
    assert (model_dir / "model.joblib").exists()
    assert (model_dir / "manifest.json").exists()


def test_the_cycle_writes_the_dataset_it_trained_on(monkeypatch, tmp_path) -> None:
    """The dataset says where its labels came from."""
    monkeypatch.setattr(learning_cycle, "build_records", lambda *a, **k: _export())
    monkeypatch.setattr(
        "app.services.model_manifest.model_directory",
        lambda settings=None: tmp_path / "model",
    )

    outcome = learning_cycle.run_learning_cycle(
        workdir=tmp_path / "work", trainer=_trainer(False)
    )

    dataset = Path(outcome.dataset_path)
    assert dataset.exists()
    header = json.loads(dataset.read_text(encoding="utf-8").splitlines()[0])
    assert header["__dataset__"]["provenance"]["label_source"] == "human-review"
    assert header["__dataset__"]["records"] == 1
