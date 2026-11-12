"""Tests for the promotion gate inside a training run.

The gate is only worth having if it is wired into the pipeline: a
training run that produces a model nobody may ship is a model that will
be shipped by accident. These tests check the wiring, not the
arithmetic -- the arithmetic is covered in ``test_ml_gates.py``.
"""

from __future__ import annotations

import json
from pathlib import Path

from evm_ml.gates import GateConfig
from evm_ml.train import run_training

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "dataset_smoke.jsonl"

LABELS = ["has_delegatecall", "has_selfdestruct", "has_origin", "large_control_flow"]


def _write_dataset(path: Path, families: int = 40) -> Path:
    """A dataset with enough distinct families for a validation split."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps({"__dataset__": {"name": "gate-test"}}) + "\n")
        for index in range(families):
            positive = index % 2 == 0
            labels = {
                label: (positive if label == "has_delegatecall" else False) for label in LABELS
            }
            # The positives carry a DELEGATECALL; the negatives do not.
            code = "f4" if positive else "00"
            record = {
                "contract_id": f"contract-{index}",
                "family": f"family-{index}",
                "chain": "ethereum",
                "source": "test",
                "license": "unknown",
                "label_source": "human-review",
                "label_confidence": "reviewed",
                "bytecode": code,
                "labels": labels,
            }
            handle.write(json.dumps(record) + "\n")
    return path


def test_a_training_run_records_the_gate(tmp_path: Path) -> None:
    dataset = _write_dataset(tmp_path / "dataset.jsonl")

    result = run_training(
        dataset,
        tmp_path / "model",
        labels=LABELS,
        gate_config=GateConfig(min_precision=0.80, min_positive_support=2),
    )

    manifest = json.loads(Path(result["manifest"]).read_text(encoding="utf-8"))
    assert manifest["gate"] is not None
    assert "decisions" in manifest["gate"]
    assert "promotable" in manifest["gate"]
    assert isinstance(result["promotable"], bool)
    assert isinstance(result["shipped_categories"], list)


def test_a_model_that_fails_the_gate_is_not_promotable(tmp_path: Path) -> None:
    """A precision floor nobody can reach must block the model.

    The floor is set above 1.0, so no category can pass it. The model
    is still written, so it can be inspected, but the run says it may
    not be promoted.
    """
    dataset = _write_dataset(tmp_path / "dataset.jsonl")

    result = run_training(
        dataset,
        tmp_path / "model",
        labels=LABELS,
        gate_config=GateConfig(min_precision=1.5, min_positive_support=2),
    )

    assert result["promotable"] is False
    assert result["shipped_categories"] == []
    manifest = json.loads(Path(result["manifest"]).read_text(encoding="utf-8"))
    assert manifest["gate"]["promotable"] is False


def test_the_evaluation_file_records_the_gate(tmp_path: Path) -> None:
    dataset = _write_dataset(tmp_path / "dataset.jsonl")

    result = run_training(
        dataset,
        tmp_path / "model",
        labels=LABELS,
        gate_config=GateConfig(min_precision=0.80, min_positive_support=2),
    )

    manifest = json.loads(Path(result["manifest"]).read_text(encoding="utf-8"))
    gate = manifest["gate"]
    # Every category is judged, and every judgement says why.
    assert {decision["category"] for decision in gate["decisions"]} == set(LABELS)
    assert all(decision["reason"] for decision in gate["decisions"])
