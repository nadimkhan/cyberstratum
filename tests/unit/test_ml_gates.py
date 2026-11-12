"""Tests for the promotion gate.

The gate is what stops a noisy category from being shipped, so these
tests are about the decisions rather than about the arithmetic: a
category that cannot be measured is not judged, a category that is too
noisy is silenced, and a category that passes is allowed to speak.
"""

from __future__ import annotations

import numpy as np
import pytest

from evm_ml.dataset import Sample
from evm_ml.evaluate import evaluate
from evm_ml.gates import (
    STATUS_ABSTAIN,
    STATUS_INSUFFICIENT,
    STATUS_SHIP,
    GateConfig,
    gate_categories,
    select_thresholds,
)


def _sample(contract_id: str, labels: dict[str, bool]) -> Sample:
    return Sample(
        contract_id=contract_id,
        family=f"family-{contract_id}",
        bytecode=b"\x60\x00",
        labels=dict(labels),
    )


def _dataset(
    positives: int, negatives: int, category: str = "unchecked_call"
) -> tuple[list[Sample], list[dict[str, float]]]:
    """A split with a known number of positives and negatives."""
    samples: list[Sample] = []
    probabilities: list[dict[str, float]] = []
    for index in range(positives):
        samples.append(_sample(f"p{index}", {category: True}))
        probabilities.append({category: 0.9})
    for index in range(negatives):
        samples.append(_sample(f"n{index}", {category: False}))
        # The negatives look exactly like the positives to the model: the
        # worst case for precision, and the case the gate exists for.
        probabilities.append({category: 0.9})
    return samples, probabilities


def test_a_noisy_category_is_silenced() -> None:
    samples, probabilities = _dataset(positives=10, negatives=90)
    report = evaluate(samples, probabilities, ["unchecked_call"])

    gate = gate_categories(
        report,
        config=GateConfig(min_precision=0.80, min_positive_support=5),
        samples=samples,
        probabilities=probabilities,
    )

    decision = gate.decisions[0]
    assert decision.status == STATUS_ABSTAIN
    assert "below the floor" in decision.reason
    assert gate.shipped_categories == []
    assert gate.promotable is False


def test_a_clean_category_ships() -> None:
    samples: list[Sample] = []
    probabilities: list[dict[str, float]] = []
    for index in range(10):
        samples.append(_sample(f"p{index}", {"unchecked_call": True}))
        probabilities.append({"unchecked_call": 0.9})
    for index in range(90):
        samples.append(_sample(f"n{index}", {"unchecked_call": False}))
        probabilities.append({"unchecked_call": 0.01})

    report = evaluate(samples, probabilities, ["unchecked_call"])
    gate = gate_categories(
        report,
        config=GateConfig(min_precision=0.80, min_positive_support=5),
        samples=samples,
        probabilities=probabilities,
    )

    assert gate.decisions[0].status == STATUS_SHIP
    assert gate.shipped_categories == ["unchecked_call"]
    assert gate.promotable is True


def test_too_little_data_is_not_a_judgement() -> None:
    """Three examples cannot measure a precision."""
    samples, probabilities = _dataset(positives=3, negatives=30)
    report = evaluate(samples, probabilities, ["unchecked_call"])

    gate = gate_categories(
        report,
        config=GateConfig(min_precision=0.80, min_positive_support=5),
        samples=samples,
        probabilities=probabilities,
    )

    decision = gate.decisions[0]
    assert decision.status == STATUS_INSUFFICIENT
    assert "positive example" in decision.reason
    assert gate.promotable is False


def test_the_threshold_is_the_most_conservative_one_that_meets_the_floor() -> None:
    """The strictest threshold that still reaches the floor."""
    samples: list[Sample] = []
    probabilities: list[dict[str, float]] = []
    # Five true positives scored 0.6, one true positive scored 0.95, and
    # one false positive scored 0.7. A threshold of 0.95 flags only the
    # clean positive; 0.6 would flag the false positive too.
    for index in range(5):
        samples.append(_sample(f"p{index}", {"unchecked_call": True}))
        probabilities.append({"unchecked_call": 0.6})
    samples.append(_sample("p-high", {"unchecked_call": True}))
    probabilities.append({"unchecked_call": 0.95})
    samples.append(_sample("n-high", {"unchecked_call": False}))
    probabilities.append({"unchecked_call": 0.7})

    thresholds = select_thresholds(
        samples, probabilities, ["unchecked_call"], min_precision=0.80
    )

    # At 0.8 the false positive is not flagged, so precision is 1.0.
    assert thresholds["unchecked_call"] >= 0.8


def test_a_category_with_no_positives_gets_the_default_threshold() -> None:
    samples = [_sample(f"n{index}", {"unchecked_call": False}) for index in range(10)]
    probabilities = [{"unchecked_call": 0.1} for _ in samples]

    thresholds = select_thresholds(
        samples, probabilities, ["unchecked_call"], min_precision=0.80
    )

    assert thresholds["unchecked_call"] == 0.5


def test_the_gate_reports_every_category() -> None:
    samples, probabilities = _dataset(positives=10, negatives=90)
    report = evaluate(samples, probabilities, ["unchecked_call", "reentrancy"])

    gate = gate_categories(
        report,
        config=GateConfig(min_precision=0.80, min_positive_support=5),
        samples=samples,
        probabilities=probabilities,
        labels=["unchecked_call", "reentrancy"],
    )

    assert {d.category for d in gate.decisions} == {"unchecked_call", "reentrancy"}
    assert all(isinstance(d.reason, str) and d.reason for d in gate.decisions)


def test_the_gate_serialises_for_the_manifest() -> None:
    samples, probabilities = _dataset(positives=10, negatives=90)
    report = evaluate(samples, probabilities, ["unchecked_call"])

    gate = gate_categories(
        report,
        config=GateConfig(min_precision=0.80, min_positive_support=5),
        samples=samples,
        probabilities=probabilities,
    )

    payload = gate.as_dict()
    assert payload["promotable"] is False
    assert payload["decisions"][0]["status"] == STATUS_ABSTAIN
    assert payload["reason"]


def test_a_model_with_no_evaluation_is_not_promoted() -> None:
    from evm_ml.evaluate import EvaluationReport

    gate = gate_categories(EvaluationReport(), labels=["unchecked_call"])

    assert gate.promotable is False
    assert gate.decisions[0].status == STATUS_INSUFFICIENT
    assert np is not None  # the import is used by the module under test
