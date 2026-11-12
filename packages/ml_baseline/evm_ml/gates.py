"""The gate a trained model must pass before it may be promoted.

Why a gate at all
-----------------

A classifier trained on reviewed labels will report precision for every
category, and a report is not a decision. The dangerous failure is a
category whose detector is noisy: the model says "reentrancy" on a
thousand contracts and a reviewer finds a real one in three. Shipping
that category does not just waste the reviewer's time -- it teaches
them to ignore the product, and the one true finding in the noise goes
with it.

So the categories are judged one at a time, on the validation split:

* **ship** -- the precision is at or above the floor and there is enough
  evidence to believe it.
* **abstain** -- the category is too noisy at the precision floor. The
  model may still carry the weights, but it must not emit findings for
  this category, and the manifest says so.
* **insufficient_data** -- there is not enough evidence to judge. This
  is not the same as abstaining: it means nobody knows yet, and the
  honest response is to say so rather than to guess.

A model is promotable when at least one category ships. The categories
that do not ship are not a reason to throw away the ones that do; they
are a reason to keep them quiet.

Per-category thresholds
-----------------------

One global threshold is a compromise between categories that behave
differently. The gate therefore also *chooses* a threshold per
category: the most conservative one that still reaches the precision
floor, and the one that recovers the most recall within it. A category
that cannot reach the floor at any threshold abstains, because there is
no setting of the dial that makes it safe.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from evm_ml.dataset import Sample
from evm_ml.evaluate import EvaluationReport

__all__ = [
    "CategoryDecision",
    "GateConfig",
    "GateReport",
    "gate_categories",
    "select_thresholds",
]

#: The thresholds the gate tries, from permissive to strict.
THRESHOLD_GRID: tuple[float, ...] = (
    0.05,
    0.10,
    0.15,
    0.20,
    0.25,
    0.30,
    0.35,
    0.40,
    0.45,
    0.50,
    0.55,
    0.60,
    0.65,
    0.70,
    0.75,
    0.80,
    0.85,
    0.90,
    0.95,
)

STATUS_SHIP = "ship"
STATUS_ABSTAIN = "abstain"
STATUS_INSUFFICIENT = "insufficient_data"


@dataclass(frozen=True)
class GateConfig:
    """What the gate demands.

    Attributes:
        min_precision: The precision a category must reach to ship.
        min_positive_support: How many positive examples the validation
            split must hold for the measurement to mean anything.
        min_recall: The recall a category must reach. Zero by default:
            precision is the false-positive control, and demanding
            recall as well would empty the model on a small corpus.
        allowed_abstained: How many categories may abstain without the
            model being blocked outright. The model still ships the
            categories that passed.
    """

    min_precision: float = 0.80
    min_positive_support: int = 5
    min_recall: float = 0.0
    allowed_abstained: int = 1


@dataclass(frozen=True)
class CategoryDecision:
    """What the gate decided about one category.

    Attributes:
        category: The label category.
        status: ``ship``, ``abstain`` or ``insufficient_data``.
        precision: The precision measured on the validation split.
        recall: The recall measured on the validation split.
        support: How many positive examples the validation split held.
        threshold: The threshold the gate recommends for this category.
        reason: Why, in one sentence.
    """

    category: str
    status: str
    precision: float
    recall: float
    support: int
    threshold: float
    reason: str

    def as_dict(self) -> dict[str, Any]:
        """A JSON-friendly view, for the manifest and the model card."""
        return {
            "category": self.category,
            "status": self.status,
            "precision": self.precision,
            "recall": self.recall,
            "support": self.support,
            "threshold": self.threshold,
            "reason": self.reason,
        }


@dataclass
class GateReport:
    """The gate's verdict on a model.

    Attributes:
        decisions: One decision per category.
        promotable: Whether the model may be promoted at all.
        shipped_categories: The categories the model may speak about.
        abstained_categories: The categories the model must stay quiet
            about.
        reason: Why the model is or is not promotable.
    """

    decisions: list[CategoryDecision] = field(default_factory=list)
    promotable: bool = False
    shipped_categories: list[str] = field(default_factory=list)
    abstained_categories: list[str] = field(default_factory=list)
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        """A JSON-friendly view, for the manifest and the model card."""
        return {
            "promotable": self.promotable,
            "shipped_categories": list(self.shipped_categories),
            "abstained_categories": list(self.abstained_categories),
            "reason": self.reason,
            "decisions": [d.as_dict() for d in self.decisions],
        }


def _precision_recall(
    scores: np.ndarray, truth: np.ndarray, threshold: float
) -> tuple[float, float]:
    """Precision and recall of one threshold."""
    predicted = scores >= threshold
    positives = truth.sum()
    if positives == 0:
        return (1.0, 0.0)
    hits = int((predicted & truth).sum())
    flagged = int(predicted.sum())
    precision = hits / flagged if flagged else 0.0
    recall = hits / int(positives)
    return (precision, recall)


def select_thresholds(
    samples: Sequence[Sample],
    probabilities: Sequence[dict[str, float]],
    labels: Sequence[str],
    *,
    min_precision: float = 0.80,
    default: float = 0.5,
) -> dict[str, float]:
    """Choose a threshold per category on the validation split.

    The chosen threshold is the most conservative one that still reaches
    the precision floor, because the most conservative threshold that
    meets the floor is the one that recovers the most recall within it
    while promising the fewest false positives.

    Args:
        samples: The validation samples.
        probabilities: The model's per-sample probabilities.
        labels: The categories to choose a threshold for.
        min_precision: The precision floor.
        default: The threshold used when no candidate meets the floor.

    Returns:
        The threshold per category.
    """
    chosen: dict[str, float] = {}
    for label in labels:
        scores = np.array(
            [float(probabilities[index].get(label, 0.0)) for index in range(len(samples))]
        )
        truth = np.array(
            [bool(sample.labels.get(label, False)) for sample in samples],
            dtype=bool,
        )
        if truth.sum() == 0 or len(scores) == 0:
            chosen[label] = default
            continue

        best: tuple[float, float] | None = None
        for threshold in THRESHOLD_GRID:
            precision, recall = _precision_recall(scores, truth, threshold)
            # Keep the highest threshold that qualifies: it flags fewer
            # contracts for the same guarantee.
            if precision >= min_precision and (best is None or threshold > best[0]):
                best = (threshold, recall)
        chosen[label] = best[0] if best is not None else default
    return chosen


def gate_categories(
    report: EvaluationReport,
    *,
    config: GateConfig = GateConfig(),
    samples: Sequence[Sample] | None = None,
    probabilities: Sequence[dict[str, float]] | None = None,
    labels: Sequence[str] | None = None,
) -> GateReport:
    """Decide, per category, whether the model may speak about it.

    Args:
        report: The evaluation report for the validation split.
        config: What the gate demands.
        samples: The validation samples, used to re-measure precision at
            the chosen per-category threshold.
        probabilities: The model's per-sample probabilities, for the
            same purpose.
        labels: The categories to judge. Defaults to the categories in
            the report.

    Returns:
        A :class:`GateReport`.
    """
    categories = list(labels) if labels is not None else [c.category for c in report.categories]
    metrics = {c.category: c for c in report.categories}

    thresholds: dict[str, float] = {}
    if samples is not None and probabilities is not None:
        thresholds = select_thresholds(
            samples,
            probabilities,
            categories,
            min_precision=config.min_precision,
        )

    gate = GateReport()
    for category in categories:
        metric = metrics.get(category)
        if metric is None:
            gate.decisions.append(
                CategoryDecision(
                    category=category,
                    status=STATUS_INSUFFICIENT,
                    precision=0.0,
                    recall=0.0,
                    support=0,
                    threshold=thresholds.get(category, 0.5),
                    reason="the category was not evaluated, so nothing is known about it",
                )
            )
            continue

        threshold = thresholds.get(category, metric.threshold)
        precision = metric.precision
        recall = metric.recall

        # Re-measure at the chosen threshold when the predictions are
        # available: the report was computed at a single global
        # threshold, and the gate's verdict is about the threshold the
        # model will actually use.
        if samples is not None and probabilities is not None and len(samples):
            scores = np.array(
                [float(probabilities[index].get(category, 0.0)) for index in range(len(samples))]
            )
            truth = np.array(
                [bool(sample.labels.get(category, False)) for sample in samples],
                dtype=bool,
            )
            precision, recall = _precision_recall(scores, truth, threshold)

        support = int(metric.support)
        if support < config.min_positive_support:
            status = STATUS_INSUFFICIENT
            reason = (
                f"only {support} positive example(s) in the validation split; "
                f"at least {config.min_positive_support} are needed to measure it"
            )
        elif precision < config.min_precision:
            status = STATUS_ABSTAIN
            reason = (
                f"precision {precision:.2f} is below the floor "
                f"{config.min_precision:.2f}; the model stays quiet about this category"
            )
        elif recall < config.min_recall:
            status = STATUS_ABSTAIN
            reason = f"recall {recall:.2f} is below the floor {config.min_recall:.2f}"
        else:
            status = STATUS_SHIP
            reason = (
                f"precision {precision:.2f} at threshold {threshold:.2f} "
                f"with {support} positive example(s)"
            )

        gate.decisions.append(
            CategoryDecision(
                category=category,
                status=status,
                precision=precision,
                recall=recall,
                support=support,
                threshold=threshold,
                reason=reason,
            )
        )

    gate.shipped_categories = [d.category for d in gate.decisions if d.status == STATUS_SHIP]
    gate.abstained_categories = [d.category for d in gate.decisions if d.status != STATUS_SHIP]
    blocked = len(gate.abstained_categories)
    gate.promotable = bool(gate.shipped_categories) and blocked <= config.allowed_abstained
    if gate.shipped_categories:
        gate.reason = f"{len(gate.shipped_categories)} categor(ies) may ship; {blocked} stay quiet"
    else:
        gate.reason = "no category reached the precision floor, so the model may not be promoted"
    return gate
