"""Run one learning cycle: reviewed labels -> a gated model -> an installed model.

The product collects two kinds of evidence: findings that engines
produced, and the verdicts a person made about those findings. Only the
second kind is training truth. This command joins them:

1. Export the reviewed findings as training labels. Contracts with an
   unreviewed finding in a category are left out, because "nobody has
   looked at this yet" is not the same as "this is not vulnerable".
2. Train a candidate model on that dataset, with the split made at the
   level of the contract family, so one clone cannot sit on both sides
   of the split.
3. Put the candidate through the precision gate. The gate decides, per
   category, whether the model may speak about that category at all.
4. Install the model only if it passed. A model that failed the gate is
   written to disk so it can be inspected, and it is *not* installed:
   the scanner must never pick up a model whose false positives have
   not been measured.

Nothing here turns an unreviewed label into a verdict. The labels come
from human review; the gate decides whether the result is fit to rank
with; and the model that is installed only ever ranks findings.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import shutil
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.session import session_scope
from app.services.label_export import build_records, write_dataset

log = get_logger(__name__)

#: The files a candidate model hands over when it is installed.
MODEL_FILES = ("model.joblib", "manifest.json")


class NoReviewedLabelsError(RuntimeError):
    """There is nothing to learn from yet."""

    def __init__(self, summary: dict[str, Any]) -> None:
        super().__init__("there are no reviewed labels to learn from yet")
        self.summary = summary


@dataclass(frozen=True, slots=True)
class LearningOutcome:
    """What one learning cycle did."""

    dataset_path: str
    records: int
    promotable: bool
    gate_reason: str
    shipped_categories: tuple[str, ...]
    abstained_categories: tuple[str, ...]
    installed: bool
    model_dir: str | None = None
    manifest_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        """A JSON-friendly summary, for the run log."""
        return {
            "dataset": self.dataset_path,
            "records": self.records,
            "promotable": self.promotable,
            "gate_reason": self.gate_reason,
            "shipped_categories": list(self.shipped_categories),
            "abstained_categories": list(self.abstained_categories),
            "installed": self.installed,
            "model_dir": self.model_dir,
            "manifest_id": self.manifest_id,
        }


def install_model(candidate_dir: Path, model_dir: Path) -> None:
    """Put the candidate model in place.

    Every file is written beside its target and then renamed over it, so
    a reader never sees a half-written model.
    """
    model_dir.mkdir(parents=True, exist_ok=True)
    for name in MODEL_FILES:
        source = candidate_dir / name
        if not source.exists():
            raise FileNotFoundError(f"the candidate model does not have {name}")
        temporary = model_dir / f".{name}.new"
        shutil.copyfile(source, temporary)
        temporary.replace(model_dir / name)


def run_learning_cycle(
    *,
    workdir: Path | None = None,
    limit: int | None = None,
    trainer: Callable[..., dict[str, Any]] | None = None,
    install: bool = True,
) -> LearningOutcome:
    """Run one cycle and report exactly what happened.

    Args:
        workdir: Where the dataset and the candidate model are written.
        limit: Stop after this many contracts.
        trainer: The training function. It is a parameter so that the
            behaviour of this command can be tested without training a
            real model.
        install: Whether a model that passed the gate is installed.

    Returns:
        A :class:`LearningOutcome`.

    Raises:
        NoReviewedLabelsError: when there is no reviewed evidence to learn
            from. That is not a failure of the product: it means nobody
            has reviewed anything yet.
    """
    from app.services.model_manifest import model_directory, read_model_manifest
    from evm_ml.train import run_training

    settings = get_settings()
    workdir = workdir or (settings.repo_root / ".learning")
    workdir.mkdir(parents=True, exist_ok=True)

    with session_scope() as session:
        export = build_records(
            session,
            storage_root=settings.object_storage_root,
            limit=limit,
        )

    if not export.records:
        raise NoReviewedLabelsError(export.as_dict())

    dataset_path = workdir / "reviewed-labels.jsonl"
    write_dataset(export, dataset_path)

    candidate_dir = workdir / "candidate"
    train = trainer or run_training
    result = train(dataset_path, candidate_dir)

    promotable = bool(result.get("promotable"))
    shipped = tuple(result.get("shipped_categories") or ())
    abstained = tuple(result.get("abstained_categories") or ())
    gate_reason = str(result.get("gate_reason") or "")

    installed = False
    model_dir: str | None = None
    manifest_id: str | None = None

    if promotable and install:
        target = model_directory(settings)
        if target is None:
            raise RuntimeError(
                "ML_MODEL_DIR is not set, so there is nowhere to install the model."
            )
        install_model(Path(candidate_dir), target)
        installed = True
        model_dir = str(target)
        manifest = read_model_manifest(settings)
        manifest_id = manifest.manifest_id if manifest is not None else None

    outcome = LearningOutcome(
        dataset_path=str(dataset_path),
        records=len(export.records),
        promotable=promotable,
        gate_reason=gate_reason,
        shipped_categories=shipped,
        abstained_categories=abstained,
        installed=installed,
        model_dir=model_dir,
        manifest_id=manifest_id,
    )

    # The verdict is left where the product can read it, so that the
    # learning page can say what the last cycle concluded instead of
    # asking the reader to go and look at a log.
    with contextlib.suppress(OSError):
        (workdir / "last_outcome.json").write_text(
            json.dumps(outcome.as_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    return outcome


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for the command."""
    parser = argparse.ArgumentParser(
        prog="python -m app.cli.learning_cycle",
        description=(
            "Export the reviewed findings as training labels, train a model, "
            "and install it if -- and only if -- it passes the precision gate."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Stop after this many contracts.",
    )
    parser.add_argument(
        "--workdir",
        default=None,
        help="Where the dataset and the candidate model are written.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Train and report, but do not install the model.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run one learning cycle and report what happened."""
    args = build_parser().parse_args(argv)
    workdir = Path(args.workdir) if args.workdir else None

    try:
        outcome = run_learning_cycle(
            workdir=workdir,
            limit=args.limit,
            install=not args.dry_run,
        )
    except NoReviewedLabelsError as exc:
        print("there are no reviewed labels to learn from yet; nothing was trained")
        print(json.dumps(exc.summary, indent=2, sort_keys=True))
        return 1
    except Exception as exc:  # noqa: BLE001 - the failure must be reported
        print(f"the learning cycle failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(outcome.as_dict(), indent=2, sort_keys=True))

    if not outcome.promotable:
        print(
            f"GATE: the model may not be installed: {outcome.gate_reason}",
            file=sys.stderr,
        )
        return 2
    if outcome.installed:
        print(f"installed the model in {outcome.model_dir}")
    else:
        print("the model was not installed (dry run)")
    return 0


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())
