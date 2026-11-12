#!/usr/bin/env python3
"""Export the reviewed findings as a training dataset.

The labels this writes are the ones a person made: a finding was
reviewed, the reviewer said *confirmed* or *false positive*, and the
reason was written down. Contracts with an unreviewed finding are left
out rather than assumed safe.

Usage::

    .venv/bin/python scripts/export_reviewed_labels.py \
        --output var/datasets/reviewed-labels.jsonl
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))

from app.core.config import get_settings  # noqa: E402
from app.db.session import session_scope  # noqa: E402
from app.services.label_export import build_records, write_dataset  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--output",
        default=str(REPO_ROOT / "var" / "datasets" / "reviewed-labels.jsonl"),
        help="where to write the JSON Lines dataset",
    )
    parser.add_argument("--limit", type=int, default=None, help="stop after N records")
    args = parser.parse_args(argv)

    storage_root = Path(get_settings().object_storage_root)
    with session_scope() as session:
        export = build_records(session, storage_root=storage_root, limit=args.limit)
        path = write_dataset(export, Path(args.output))

    summary = export.as_dict()
    print(f"records            : {summary['records']}")
    print(f"skipped, unsettled : {summary['skipped_unsettled']}")
    print(f"ignored, unmapped  : {summary['ignored_unmapped']}")
    print(f"skipped, no code   : {summary['skipped_no_bytecode']}")
    print(f"chains             : {', '.join(summary['chains']) or 'none'}")
    print(f"dataset            : {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
