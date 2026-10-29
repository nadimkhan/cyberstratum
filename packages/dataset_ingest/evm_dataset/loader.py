"""Loading records from JSON Lines files.

The loader is deliberately forgiving about a *missing* file: ingestion
runs against corpora that may not have been fetched yet, and a missing
input is an empty corpus, not a crash. A malformed *present* file is a
different matter - it is a bug in the corpus or the fetcher, and it is
reported loudly with the line number.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .records import DatasetRecord

__all__ = ["load_jsonl", "parse_record", "records_to_jsonl"]

_LOGGER = logging.getLogger(__name__)


def parse_record(payload: dict[str, Any], *, source: str = "<memory>") -> DatasetRecord:
    """Build a :class:`DatasetRecord` from a decoded JSON object.

    Unknown keys are kept in ``metadata`` so that a dataset-specific
    field is never silently dropped.
    """
    known = {
        "record_id",
        "id",
        "source_dataset",
        "source_ref",
        "code",
        "source",
        "project",
        "contract_name",
        "chain",
        "compiler_version",
        "swc_id",
        "cwe_id",
        "label",
        "label_provenance",
        "severity",
        "license",
        "upstream_revision",
    }
    record_id = str(payload.get("record_id") or payload.get("id") or "")
    if not record_id:
        raise ValueError(f"{source}: record is missing a record_id")
    source_dataset = str(payload.get("source_dataset") or "")
    if not source_dataset:
        raise ValueError(f"{source}: record {record_id!r} is missing source_dataset")

    metadata = {key: value for key, value in payload.items() if key not in known}
    source_ref = str(payload.get("source_ref") or "")
    if not source_ref:
        source_ref = record_id

    return DatasetRecord(
        record_id=record_id,
        source_dataset=source_dataset,
        source_ref=source_ref,
        code=str(payload.get("code") or payload.get("source") or ""),
        project=str(payload.get("project") or ""),
        contract_name=str(payload.get("contract_name") or ""),
        chain=str(payload.get("chain") or "unknown"),
        compiler_version=(
            str(payload["compiler_version"]) if payload.get("compiler_version") else None
        ),
        swc_id=str(payload["swc_id"]) if payload.get("swc_id") else None,
        cwe_id=str(payload["cwe_id"]) if payload.get("cwe_id") else None,
        label=None if payload.get("label") is None else str(payload["label"]),
        label_provenance=(
            str(payload["label_provenance"]) if payload.get("label_provenance") else None
        ),
        severity=str(payload["severity"]) if payload.get("severity") else None,
        license=str(payload["license"]) if payload.get("license") else None,
        upstream_revision=(
            str(payload["upstream_revision"]) if payload.get("upstream_revision") else None
        ),
        metadata=metadata,
    )


def load_jsonl(path: str | Path) -> list[DatasetRecord]:
    """Load a JSONL file of records.

    A missing file yields an empty list. Blank lines are skipped. A line
    that is not valid JSON, or that is not a JSON object, raises
    ``ValueError`` naming the file and line.
    """
    file_path = Path(path)
    if not file_path.exists():
        _LOGGER.info("dataset file %s does not exist; treating it as empty", file_path)
        return []

    records: list[DatasetRecord] = []
    with file_path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{file_path}:{line_number}: invalid JSON: {exc}") from exc
            if not isinstance(payload, dict):
                raise ValueError(
                    f"{file_path}:{line_number}: expected a JSON object, "
                    f"got {type(payload).__name__}"
                )
            records.append(parse_record(payload, source=f"{file_path}:{line_number}"))
    return records


def records_to_jsonl(records: Iterable[DatasetRecord]) -> str:
    """Serialise records back to JSON Lines, one canonical object per line."""
    lines = [
        json.dumps(record.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        for record in records
    ]
    return "\n".join(lines) + ("\n" if lines else "")
