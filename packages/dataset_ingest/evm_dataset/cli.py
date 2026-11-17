"""Command-line entry point for the dataset ingestion pipeline.

Runs the synthetic smoke dataset through the full pipeline - deduplication,
family grouping, family-level splitting, manifest building and the
promotion gate - and prints the result.

The command runs entirely offline: no network access, no dataset fetch,
no model training. The data it prints is the *synthetic smoke dataset*,
whose labels are heuristic and are not benchmark ground truth.
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence

from .dedup import deduplicate
from .family import assign_family_key
from .ingest import ingest_dataset
from .licensing import KNOWN_DATASET_LICENCES, IngestRefusalError
from .loader import load_jsonl
from .manifest import build_manifest, verify_manifest
from .promotion import can_promote
from .smartbugs import SMARTBUGS_DATASET, SMARTBUGS_REVISION, ingest_smartbugs
from .smoke import smoke_records
from .split import split_by_family

__all__ = ["main"]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="evm-dataset",
        description=(
            "Run the synthetic smoke dataset through the CyberStratum dataset "
            "ingestion pipeline. Offline only."
        ),
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=0,
        help="Seed for the family-level split (default: 0).",
    )
    parser.add_argument(
        "--ratios",
        type=float,
        nargs=3,
        default=(0.7, 0.15, 0.15),
        metavar=("TRAIN", "VALIDATION", "TEST"),
        help="Family ratios for the split (default: 0.7 0.15 0.15).",
    )
    parser.add_argument(
        "--ingest",
        metavar="FILE",
        help=(
            "Ingest a JSONL corpus instead of the smoke dataset. The corpus is "
            "refused unless its licence is settled, its upstream revision is "
            "pinned, and its content can be hashed."
        ),
    )
    parser.add_argument(
        "--smartbugs",
        action="store_true",
        help=(
            "Ingest the SmartBugs Curated corpus at its pinned revision. "
            "The corpus is fetched once, hashed, and ingested through the "
            "ordinary door."
        ),
    )
    parser.add_argument(
        "--dataset",
        help="The dataset the corpus belongs to (used with --ingest).",
    )
    parser.add_argument(
        "--revision",
        help="The pinned upstream revision of the corpus (used with --ingest).",
    )
    parser.add_argument(
        "--corpus-sha256",
        help=(
            "The SHA-256 of the fetched corpus; recorded in the manifest "
            "provenance so the manifest says which bytes were fetched."
        ),
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging.",
    )
    return parser


def _run_smartbugs(args: argparse.Namespace) -> int:
    """Ingest the SmartBugs Curated corpus at its pinned revision.

    A refusal is an error: the corpus is not ingested and no manifest is
    written.
    """
    try:
        manifest = ingest_smartbugs(
            revision=SMARTBUGS_REVISION,
            seed=args.seed,
            ratios=tuple(args.ratios),
        )
    except IngestRefusalError as error:
        print(f"ingest refused: {error.dataset}: {error.reason}")
        return 2

    print("=" * 72)
    print(f"CyberStratum dataset ingestion - {SMARTBUGS_DATASET}")
    print("=" * 72)
    print(f"  revision: {SMARTBUGS_REVISION}")
    print(f"  records: {manifest.record_count}  families: {manifest.family_count}")
    print(f"  splits: {manifest.split_counts}")
    print(f"  manifest hash: {manifest.content_hash}")
    provenance = manifest.provenance[0]
    print(f"  licence: {provenance['license']['spdx_id']}")
    print(f"  corpus hash: {provenance['extra'].get('corpus_sha256')}")
    return 0


def _run_ingest(args: argparse.Namespace) -> int:
    """Ingest a corpus, or refuse it and say why.

    A refusal is an error, not a warning: the corpus is not ingested and
    no manifest is written.
    """
    if not args.dataset:
        print("ingest refused: no dataset was named")
        return 2

    records = load_jsonl(args.ingest)
    if not records:
        print(f"ingest refused: {args.dataset}: the corpus is empty")
        return 2

    try:
        manifest = ingest_dataset(
            records,
            dataset=args.dataset,
            upstream_revision=args.revision,
            corpus_sha256=args.corpus_sha256,
            seed=args.seed,
            ratios=tuple(args.ratios),
        )
    except IngestRefusalError as error:
        print(f"ingest refused: {error.dataset}: {error.reason}")
        return 2

    print("=" * 72)
    print(f"CyberStratum dataset ingestion - {args.dataset}")
    print("=" * 72)
    print(f"  records: {manifest.record_count}  families: {manifest.family_count}")
    print(f"  manifest hash: {manifest.content_hash}")
    for dataset, content_hash in sorted(manifest.content_hashes.items()):
        print(f"  content hash: {dataset} {content_hash}")
    for entry in manifest.provenance:
        licence = entry["license"]
        print(f"  licence: {licence['spdx_id']}  revision: {entry['upstream_revision']}")
    verification = verify_manifest(manifest, records)
    print(f"  self-verification: {'ok' if verification.matches else 'FAILED'}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run the smoke pipeline and print the outcome. Returns an exit code."""
    args = _build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    if args.ingest:
        return _run_ingest(args)
    if args.smartbugs:
        return _run_smartbugs(args)

    records = smoke_records()
    ratios = tuple(args.ratios)

    print("=" * 72)
    print("CyberStratum dataset ingestion - synthetic smoke dataset")
    print(
        "NOTE: these records are synthetic and their labels are heuristic. "
        "They are NOT benchmark ground truth."
    )
    print("=" * 72)

    print(f"\nrecords: {len(records)}")

    print("\n-- deduplication --")
    dedup_results = deduplicate(records)
    for result in dedup_results:
        print(
            f"  {result.record_id}: tier={result.matched_tier.value} "
            f"exact={result.exact[:12]} normalised={result.normalised[:12]} "
            f"near={result.near_duplicate[:12]} cluster={result.cluster_id[:12]}"
        )

    print("\n-- family grouping --")
    family_keys = {record.record_id: assign_family_key(record) for record in records}
    families: dict[str, list[str]] = {}
    for record_id, family_key in family_keys.items():
        families.setdefault(family_key, []).append(record_id)
    for family_key in sorted(families):
        members = ", ".join(sorted(families[family_key]))
        print(f"  {family_key}  <- {members}")

    print("\n-- split --")
    split = split_by_family(records, ratios=ratios, seed=args.seed)
    for name, group in split.by_name().items():
        ids = ", ".join(record.record_id for record in group)
        print(f"  {name:<11} ({len(group)}): {ids}")

    print("\n-- manifest --")
    manifest = build_manifest(records, seed=args.seed, ratios=ratios)
    print(f"  manifest hash: {manifest.content_hash}")
    print(f"  records: {manifest.record_count}  families: {manifest.family_count}")
    print(f"  label tiers: {manifest.label_tier_counts}")
    verification = verify_manifest(manifest, records)
    print(f"  self-verification: {'ok' if verification.matches else 'FAILED'}")

    print("\n-- dataset licences --")
    for dataset, licence in sorted(KNOWN_DATASET_LICENCES.items()):
        audit = " (per-repository audit required)" if licence.per_repository_audit_required else ""
        print(f"  {dataset}: {licence.spdx_id}{audit}")

    print("\n-- promotion gate --")
    decision = can_promote(manifest)
    print(f"  allowed: {decision.allowed}")
    print(f"  reason: {decision.reason}")
    print(
        f"  counts: reviewed={decision.reviewed_count} "
        f"heuristic={decision.heuristic_count} "
        f"unlabelled={decision.unlabelled_count}"
    )
    if not decision.allowed:
        print("  (exploratory training on this data is still permitted; promotion is not)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
