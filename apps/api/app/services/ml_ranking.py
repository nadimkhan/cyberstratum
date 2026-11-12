"""Let the model rank the findings, and nothing else.

The model is a triage aid. It may say "this contract looks like a
reentrancy case with high confidence", and that is useful: it tells the
reviewer where to look first. What it may not do is decide that a
contract is vulnerable, or turn a heuristic rule's output into a
verdict. A model is trained on reviewed labels, and the label it was
trained to predict is "a person confirmed this", not "this is a
vulnerability".

So the model contributes a number to each finding's evidence and
nothing else. The severity, the confidence and the review status of a
finding are set by the engines and by the reviewer, and this module
does not touch them.

Three states are kept apart, because collapsing them would be a lie:

* **No model is installed** - there is no artifact. That is a fact, and
  it is reported as ``None``. A scan then runs exactly as it did before
  the model existed.
* **A model is installed and readable** - the model is returned, with
  the manifest that says which version it is.
* **A model is installed but broken** - the artifact or the manifest
  cannot be read. That is raised, so a broken installation is reported
  as a failure rather than as the absence of a model.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from app.core.config import Settings, get_settings
from app.services.label_export import DETECTOR_CATEGORIES
from app.services.model_manifest import (
    ModelManifest,
    ModelManifestError,
    model_directory,
    read_model_manifest,
)

__all__ = [
    "InstalledModel",
    "annotate_findings",
    "load_installed_model",
    "score_bytecode",
]


@dataclass(frozen=True, slots=True)
class InstalledModel:
    """The model that is installed, and the manifest that says which."""

    adapter: Any
    manifest: ModelManifest
    version: str
    labels: tuple[str, ...]


def load_installed_model(settings: Settings | None = None) -> InstalledModel | None:
    """The installed model, or ``None`` when there is none.

    Raises:
        ModelManifestError: when a model directory is configured but the
            artifact or the manifest cannot be read. A broken
            installation is a failure, not the absence of a model.
    """
    from evm_ml import load_adapter

    settings = settings or get_settings()
    directory = model_directory(settings)
    if directory is None:
        return None

    manifest = read_model_manifest(settings)
    if manifest is None:
        return None

    adapter = load_adapter(directory)
    if adapter is None:
        raise ModelManifestError(
            f"No model artifact in {directory}. The model directory is "
            "configured but does not hold a model."
        )

    labels = tuple(str(label) for label in getattr(adapter, "labels", ()) or ())
    return InstalledModel(
        adapter=adapter,
        manifest=manifest,
        version=manifest.manifest_id,
        labels=labels,
    )


def score_bytecode(
    model: InstalledModel,
    bytecode: bytes,
    *,
    contract_id: str = "contract",
    chain: str = "unknown",
) -> dict[str, float]:
    """The model's per-category scores for one contract.

    The scores are probabilities over the categories the model was
    trained on. A category the model never saw is simply absent, and an
    absent category is not a zero: it is "the model does not speak
    about this".
    """
    from evm_ml.dataset import Sample

    sample = Sample(
        contract_id=contract_id,
        family="unlabelled",
        bytecode=bytecode,
        labels={},
        chain=chain,
        source="live-scan",
        label_source="model-inference",
        label_confidence="unlabelled",
    )
    predictions = model.adapter.predict_proba([sample])
    if not predictions:
        return {}
    return {str(key): float(value) for key, value in predictions[0].items()}


def annotate_findings(findings: Iterable[Any], scores: dict[str, float]) -> int:
    """Attach the model's score to the findings that have a category.

    The score is a ranking aid. The severity, the confidence and the
    review status are left exactly as they were: the model may reorder
    the review queue, and it may not change what a finding says.

    Returns how many findings were annotated.
    """
    if not scores:
        return 0

    annotated = 0
    for finding in findings:
        detector_id = getattr(finding, "detector_id", None)
        category = DETECTOR_CATEGORIES.get(detector_id or "")
        if category is None:
            continue
        score = scores.get(category)
        if score is None:
            continue
        evidence = getattr(finding, "evidence", None)
        if not isinstance(evidence, dict):
            continue
        evidence["ml_score"] = round(float(score), 4)
        evidence["ml_category"] = category
        annotated += 1
    return annotated
