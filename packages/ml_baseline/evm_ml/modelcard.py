"""The model card.

Design doc section 13.3 requires a model card and an explicit statement of
limitations before any model leaves the experimental stage. This module
renders that card from the manifest and the evaluation report, so the card
can never drift from the numbers it describes.
"""

from __future__ import annotations

from typing import Any

from .evaluate import EvaluationReport
from .manifest import ArtifactManifest

__all__ = ["render_model_card"]


def _fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def render_model_card(
    manifest: ArtifactManifest,
    validation: EvaluationReport | None = None,
    test: EvaluationReport | None = None,
) -> str:
    """Render the model card as Markdown."""
    lines: list[str] = []
    add = lines.append

    add(f"# Model card - {manifest.model_id or 'unnamed model'}")
    add("")
    add(f"- **Model version:** {manifest.model_version or 'unversioned'}")
    add(f"- **Created:** {manifest.created_at or 'unknown'}")
    add(f"- **Adapter:** {manifest.adapter}")
    add(
        "- **Stage:** "
        + ("EXPERIMENTAL - not cleared for production use" if manifest.experimental else "released")
    )
    add(f"- **Manifest fingerprint:** `{manifest.fingerprint()}`")
    add("")

    add("## Purpose")
    add("")
    add(
        manifest.notes
        or (
            "A TF-IDF baseline over opcode n-grams for multi-label vulnerability "
            "triage. It produces candidate findings that require analyst review; "
            "it does not by itself establish the presence of a vulnerability."
        )
    )
    add("")

    add("## Training data")
    add("")
    dataset = manifest.dataset
    add(f"- **Dataset:** {dataset.get('name', 'unknown')}")
    add(f"- **Samples:** {dataset.get('sample_count', 'unknown')}")
    add(f"- **Families:** {dataset.get('family_count', 'unknown')}")
    add(f"- **Fingerprint:** `{dataset.get('fingerprint', 'unknown')}`")
    provenance = dataset.get("provenance", {})
    if provenance:
        add(f"- **Provenance:** {provenance}")
    add("")

    add("## Method")
    add("")
    add(f"- **Features:** {manifest.feature_config.get('description', 'see feature config')}")
    add(f"- **TF-IDF convention:** `{manifest.tfidf_convention}`")
    add(f"- **Hyperparameters:** `{manifest.hyperparameters}`")
    add(f"- **Labels:** {', '.join(manifest.labels) or 'none'}")
    add("")

    add("## Split")
    add("")
    split = manifest.split
    add(f"- **Strategy:** {split.get('strategy', 'unknown')}")
    add(f"- **Fingerprint:** `{split.get('fingerprint', 'unknown')}`")
    for name in ("train", "val", "test"):
        if name in split:
            add(f"- **{name}:** {split[name]}")
    add("")

    for title, report in (("Validation metrics", validation), ("Test metrics", test)):
        add(f"## {title}")
        add("")
        if report is None:
            add("_not available_")
            add("")
            continue
        add("| category | support | precision | recall | F1 | PR-AUC | ROC-AUC | Brier | FP/100 |")
        add("|---|---|---|---|---|---|---|---|---|")
        for metric in report.categories:
            add(
                f"| {metric.category} | {metric.support} | {_fmt(metric.precision)} "
                f"| {_fmt(metric.recall)} | {_fmt(metric.f1)} | {_fmt(metric.pr_auc)} "
                f"| {_fmt(metric.roc_auc)} | {_fmt(metric.brier)} "
                f"| {_fmt(report.false_positives_per_100_contracts.get(metric.category))} |"
            )
        add("")
        add(
            f"- **Recall at a "
            f"{report.review_budget_fraction:.0%} analyst review budget:** "
            f"{ {k: _fmt(v) for k, v in report.recall_at_review_budget.items()} }"
        )
        if report.latency:
            add(f"- **Latency:** `{report.latency}`")
        add("")

    add("## Limitations")
    add("")
    for limitation in manifest.limitations:
        add(f"- {limitation}")
    if not manifest.limitations:
        add("- No limitations were recorded for this artifact.")
    add("")

    add("## Promotion gate")
    add("")
    gate = manifest.gate
    if not gate:
        add(
            "No promotion gate was recorded for this artifact. That is not the "
            "same as passing one: nothing has been measured, so nothing may "
            "be claimed."
        )
    else:
        add(f"- **Promotable:** {'yes' if gate.get('promotable') else 'no'}")
        add(f"- **Reason:** {gate.get('reason', 'unknown')}")
        shipped = gate.get("shipped_categories") or []
        abstained = gate.get("abstained_categories") or []
        add(f"- **May speak about:** {', '.join(shipped) if shipped else 'no category'}")
        add(f"- **Must stay quiet about:** {', '.join(abstained) if abstained else 'no category'}")
        add("")
        add("| Category | Decision | Precision | Recall | Support | Why |")
        add("|---|---|---|---|---|---|")
        for decision in gate.get("decisions", []):
            add(
                f"| {decision.get('category', '')} "
                f"| {decision.get('status', '')} "
                f"| {decision.get('precision', 0):.2f} "
                f"| {decision.get('recall', 0):.2f} "
                f"| {decision.get('support', 0)} "
                f"| {decision.get('reason', '')} |"
            )
    add("")

    add("## Release gate status")
    add("")
    add(
        "This artifact is **experimental**. Design doc section 13.3 requires a "
        "dataset and label review, a reproducible split, a baseline rule "
        "comparison, holdout evaluation at family level, a model card, a "
        "security review of artifact loading, shadow deployment and a "
        "human-reviewed rollout before results are treated as authoritative."
    )
    add("")

    return "\n".join(lines)
