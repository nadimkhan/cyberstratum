"""Evaluation metrics for the vulnerability classifiers.

Design doc section 13.2 requires, at minimum:

* precision and recall per vulnerability category;
* F1 and PR-AUC for imbalanced classes;
* false positives per 100 contracts or per scan;
* recall at a practical analyst review budget;
* calibration (reliability curve / Brier score);
* performance by chain, compiler, family and bytecode size;
* inference latency and memory use.

Accuracy is explicitly called out as insufficient, so it is reported only
as a secondary figure.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    precision_recall_fscore_support,
    roc_auc_score,
)

from .dataset import Sample

__all__ = [
    "CategoryMetrics",
    "EvaluationReport",
    "evaluate",
    "latency_profile",
]


@dataclass
class CategoryMetrics:
    """Metrics for one vulnerability category."""

    category: str
    support: int
    true_positives: int
    false_positives: int
    false_negatives: int
    true_negatives: int
    precision: float
    recall: float
    f1: float
    pr_auc: float | None
    roc_auc: float | None
    brier: float
    threshold: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "support": self.support,
            "true_positives": self.true_positives,
            "false_positives": self.false_positives,
            "false_negatives": self.false_negatives,
            "true_negatives": self.true_negatives,
            "precision": self.precision,
            "recall": self.recall,
            "f1": self.f1,
            "pr_auc": self.pr_auc,
            "roc_auc": self.roc_auc,
            "brier": self.brier,
            "threshold": self.threshold,
        }


@dataclass
class EvaluationReport:
    """The full evaluation report for one model on one split."""

    categories: list[CategoryMetrics] = field(default_factory=list)
    false_positives_per_100_contracts: dict[str, float] = field(default_factory=dict)
    recall_at_review_budget: dict[str, float] = field(default_factory=dict)
    review_budget_fraction: float = 0.05
    breakdown: dict[str, dict[str, Any]] = field(default_factory=dict)
    latency: dict[str, float] = field(default_factory=dict)
    contract_count: int = 0
    positive_rate: dict[str, float] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "contract_count": self.contract_count,
            "categories": [c.as_dict() for c in self.categories],
            "false_positives_per_100_contracts": self.false_positives_per_100_contracts,
            "recall_at_review_budget": self.recall_at_review_budget,
            "review_budget_fraction": self.review_budget_fraction,
            "breakdown": self.breakdown,
            "latency": self.latency,
            "positive_rate": self.positive_rate,
        }


def _safe(value: float) -> float:
    """Round for stable, comparable output."""
    return float(round(float(value), 6))


def _recall_at_budget(
    scores: np.ndarray, truth: np.ndarray, budget: int
) -> float:
    """Recall when only the top ``budget`` scored contracts are reviewed."""
    positives = int(truth.sum())
    if positives == 0:
        return 0.0
    if budget <= 0:
        return 0.0
    order = np.argsort(-scores, kind="stable")
    reviewed = truth[order[:budget]]
    return float(reviewed.sum()) / positives


def _breakdown(
    samples: Sequence[Sample],
    scores: np.ndarray,
    truth: np.ndarray,
    key: str,
) -> dict[str, Any]:
    """Performance grouped by a sample attribute."""
    groups: dict[str, list[int]] = {}
    for index, sample in enumerate(samples):
        value = getattr(sample, key, None) or "unknown"
        groups.setdefault(str(value), []).append(index)

    result: dict[str, Any] = {}
    for name, indices in sorted(groups.items()):
        group_scores = scores[indices]
        group_truth = truth[indices]
        positives = int(group_truth.sum())
        if positives == 0:
            result[name] = {
                "contracts": len(indices),
                "positives": 0,
                "recall": None,
                "note": "no positive examples in this group",
            }
            continue
        predictions = (group_scores >= 0.5).astype(int)
        found = int(((predictions == 1) & (group_truth == 1)).sum())
        result[name] = {
            "contracts": len(indices),
            "positives": positives,
            "recall": _safe(found / positives),
            "precision": _safe(
                found / predictions.sum() if predictions.sum() else 0.0
            ),
        }
    return result


def _size_breakdown(
    samples: Sequence[Sample], scores: np.ndarray, truth: np.ndarray
) -> dict[str, Any]:
    """Performance grouped by bytecode size bucket."""
    buckets = [(0, 5_000), (5_000, 20_000), (20_000, 100_000), (100_000, 1 << 62)]
    result: dict[str, Any] = {}
    for low, high in buckets:
        indices = [
            index
            for index, sample in enumerate(samples)
            if low <= len(sample.bytecode) < high
        ]
        if not indices:
            continue
        group_truth = truth[indices]
        positives = int(group_truth.sum())
        name = f"{low}-{high if high < (1 << 62) else 'inf'}"
        if positives == 0:
            result[name] = {
                "contracts": len(indices),
                "positives": 0,
                "recall": None,
            }
            continue
        predictions = (scores[indices] >= 0.5).astype(int)
        found = int(((predictions == 1) & (group_truth == 1)).sum())
        result[name] = {
            "contracts": len(indices),
            "positives": positives,
            "recall": _safe(found / positives),
            "precision": _safe(found / predictions.sum() if predictions.sum() else 0.0),
        }
    return result


def latency_profile(
    predict: Any, samples: Sequence[Sample], repeats: int = 3
) -> dict[str, float]:
    """Measure inference latency and peak memory for the prediction path."""
    import tracemalloc

    if not samples:
        return {"mean_seconds": 0.0, "p50_seconds": 0.0, "p95_seconds": 0.0, "peak_bytes": 0}

    timings: list[float] = []
    tracemalloc.start()
    try:
        for _ in range(repeats):
            start = time.perf_counter()
            predict(list(samples))
            timings.append(time.perf_counter() - start)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    timings.sort()
    p50 = timings[len(timings) // 2]
    p95 = timings[min(len(timings) - 1, int(len(timings) * 0.95))]
    return {
        "mean_seconds": _safe(sum(timings) / len(timings)),
        "p50_seconds": _safe(p50),
        "p95_seconds": _safe(p95),
        "peak_bytes": int(peak),
        "contracts": len(samples),
    }


def evaluate(
    samples: Sequence[Sample],
    probabilities: Sequence[dict[str, float]],
    labels: Sequence[str],
    *,
    threshold: float = 0.5,
    review_budget_fraction: float = 0.05,
) -> EvaluationReport:
    """Compute the full evaluation report.

    ``probabilities`` is the per-sample mapping of category to probability
    returned by a model adapter.
    """
    report = EvaluationReport(
        contract_count=len(samples),
        review_budget_fraction=review_budget_fraction,
    )

    if not samples:
        return report

    budget = max(1, int(len(samples) * review_budget_fraction))

    for label in labels:
        scores = np.array(
            [float(probabilities[index].get(label, 0.0)) for index in range(len(samples))]
        )
        truth = np.array(
            [1 if sample.labels.get(label, False) else 0 for sample in samples],
            dtype=np.int64,
        )
        predictions = (scores >= threshold).astype(np.int64)

        precision, recall, f1, _ = precision_recall_fscore_support(
            truth, predictions, average="binary", zero_division=0
        )
        pr_auc: float | None = None
        roc_auc: float | None = None
        if truth.sum() > 0 and (1 - truth).sum() > 0:
            pr_auc = _safe(average_precision_score(truth, scores))
            roc_auc = _safe(roc_auc_score(truth, scores))
        brier = _safe(brier_score_loss(truth, scores))

        tp = int(((predictions == 1) & (truth == 1)).sum())
        fp = int(((predictions == 1) & (truth == 0)).sum())
        fn = int(((predictions == 0) & (truth == 1)).sum())
        tn = int(((predictions == 0) & (truth == 0)).sum())

        report.categories.append(
            CategoryMetrics(
                category=label,
                support=int(truth.sum()),
                true_positives=tp,
                false_positives=fp,
                false_negatives=fn,
                true_negatives=tn,
                precision=_safe(precision),
                recall=_safe(recall),
                f1=_safe(f1),
                pr_auc=pr_auc,
                roc_auc=roc_auc,
                brier=brier,
                threshold=threshold,
            )
        )

        contract_count = max(1, len(samples))
        report.false_positives_per_100_contracts[label] = _safe(fp * 100.0 / contract_count)
        report.recall_at_review_budget[label] = _safe(
            _recall_at_budget(scores, truth, budget)
        )
        report.positive_rate[label] = _safe(truth.sum() / contract_count)

        report.breakdown.setdefault("by_chain", {}).update(
            _breakdown(samples, scores, truth, "chain")
        )
        report.breakdown.setdefault("by_compiler", {}).update(
            _breakdown(samples, scores, truth, "compiler")
        )
        report.breakdown.setdefault("by_family", {}).update(
            _breakdown(samples, scores, truth, "family")
        )
        report.breakdown.setdefault("by_code_size", {}).update(
            _size_breakdown(samples, scores, truth)
        )

    return report
