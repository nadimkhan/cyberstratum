"""The model ranks the findings; it does not decide them."""

from __future__ import annotations

import pytest

from app.core.config import get_settings
from app.db.enums import Severity
from app.services.ml_ranking import (
    InstalledModel,
    annotate_findings,
    load_installed_model,
    score_bytecode,
)
from app.services.model_manifest import ModelManifest, ModelManifestError
from app.services.rules import RuleFinding


def _finding(detector_id: str = "baseline.tx_origin") -> RuleFinding:
    """One rule finding, before the model has seen it."""
    return RuleFinding(
        detector_id=detector_id,
        category="tx_origin_candidate",
        title="tx.origin is used for authorisation",
        description="",
        severity=Severity.MEDIUM,
        confidence=0.55,
        evidence={"signals": ["tx_origin"]},
    )


class _Adapter:
    """An adapter that always answers the same thing."""

    def __init__(self, scores: dict[str, float]) -> None:
        self.scores = scores

    def predict_proba(self, samples: list[object]) -> list[dict[str, float]]:
        return [dict(self.scores) for _ in samples]


def _model(scores: dict[str, float]) -> InstalledModel:
    manifest = ModelManifest(
        manifest_id="v-test",
        sha256="0" * 64,
        path="/tmp/manifest.json",
        payload={"version": "v-test"},
    )
    return InstalledModel(
        adapter=_Adapter(scores),
        manifest=manifest,
        version="v-test",
        labels=tuple(scores),
    )


def test_no_model_is_installed_is_not_a_failure() -> None:
    """No model is a fact about the installation, not an error."""
    settings = get_settings().model_copy(update={"ml_model_dir": ""})

    assert load_installed_model(settings) is None


def test_a_broken_installation_is_a_failure_not_an_absence(tmp_path) -> None:
    """A manifest without an artifact is a broken installation."""
    (tmp_path / "manifest.json").write_text('{"version": "v1"}', encoding="utf-8")
    settings = get_settings().model_copy(update={"ml_model_dir": str(tmp_path)})

    with pytest.raises(ModelManifestError):
        load_installed_model(settings)


def test_the_score_is_attached_without_changing_the_finding() -> None:
    """The model adds a number and leaves the verdict alone."""
    finding = _finding()
    model = _model({"tx_origin": 0.83})

    scores = score_bytecode(model, b"\x60\x00")
    annotated = annotate_findings([finding], scores)

    assert scores == {"tx_origin": 0.83}
    assert annotated == 1
    assert finding.evidence["ml_score"] == 0.83
    assert finding.evidence["ml_category"] == "tx_origin"
    assert finding.severity is Severity.MEDIUM
    assert finding.confidence == 0.55
    assert finding.category == "tx_origin_candidate"


def test_a_finding_outside_the_vocabulary_is_left_alone() -> None:
    """A detector the model knows nothing about gets no score."""
    finding = _finding("slither.something-else")

    assert annotate_findings([finding], {"tx_origin": 0.5}) == 0
    assert "ml_score" not in finding.evidence


def test_no_scores_annotate_nothing() -> None:
    """A model that says nothing has nothing to add."""
    finding = _finding()

    assert annotate_findings([finding], {}) == 0
    assert "ml_score" not in finding.evidence
