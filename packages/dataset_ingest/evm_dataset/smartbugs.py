"""The SmartBugs Curated corpus, fetched at a pinned revision.

SmartBugs Curated is Apache-2.0 and its revision is recorded, so the
corpus can be fetched, hashed and ingested through the ordinary door.
The upstream labels are curated by the upstream project, not by anybody
in this platform, so every record carries a *heuristic* label tier: the
corpus is good for exploratory training and measurement, and it is never
promotion ground truth.
"""

from __future__ import annotations

import hashlib
import io
import json
import tarfile
import urllib.request
from collections.abc import Mapping, Sequence
from typing import Any

from .ingest import ingest_dataset
from .manifest import DatasetManifest
from .records import DatasetRecord
from .split import DEFAULT_RATIOS

__all__ = [
    "SMARTBUGS_ARCHIVE_URL",
    "SMARTBUGS_DATASET",
    "SMARTBUGS_LABELS",
    "SMARTBUGS_REVISION",
    "corpus_content_hash",
    "fetch_smartbugs_files",
    "ingest_smartbugs",
    "parse_smartbugs",
]


#: The dataset name the licence records and the manifests use.
SMARTBUGS_DATASET = "smartbugs_curated"

#: The upstream commit the corpus is pinned to.
SMARTBUGS_REVISION = "230e649123477eff332742a59a1c7cc6dc286cab"

#: One request fetches the whole corpus, at that revision.
SMARTBUGS_ARCHIVE_URL = "https://codeload.github.com/smartbugs/smartbugs-curated/tar.gz/{revision}"

#: The upstream file that carries the labels.
SMARTBUGS_LABELS = "vulnerabilities.json"

#: The provenance spelling for a label somebody else curated.
SMARTBUGS_PROVENANCE = "upstream curated"


def corpus_content_hash(files: Mapping[str, str]) -> str:
    """Return the SHA-256 of a corpus.

    The hash covers the sorted paths and the content of every file, so
    two fetches of the same revision agree, and a corpus that changed
    under the same name does not.
    """
    digest = hashlib.sha256()
    for path in sorted(files):
        digest.update(path.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(hashlib.sha256(files[path].encode("utf-8")).digest())
    return digest.hexdigest()


def parse_smartbugs(files: Mapping[str, str]) -> list[DatasetRecord]:
    """Parse the SmartBugs Curated corpus into records.

    The upstream label is a curated vulnerability category together with
    the lines it applies to. The record keeps the category, the lines and
    the upstream source, so a reviewer can see where the label came from
    instead of taking it on trust.
    """
    raw = files.get(SMARTBUGS_LABELS)
    if raw is None:
        raise ValueError(f"the corpus does not contain {SMARTBUGS_LABELS}")

    entries = json.loads(raw)
    if not isinstance(entries, list):
        raise ValueError(f"{SMARTBUGS_LABELS} does not hold a list of entries")

    records: list[DatasetRecord] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError(f"{SMARTBUGS_LABELS} holds an entry that is not an object")
        path = str(entry.get("path") or "")
        if not path:
            raise ValueError(f"{SMARTBUGS_LABELS} holds an entry without a path")
        code = files.get(path)
        if code is None:
            # The label file names a file the archive does not carry.
            # The record is not invented; it is left out.
            continue

        vulnerabilities = entry.get("vulnerabilities") or []
        categories = sorted(
            {str(item.get("category")) for item in vulnerabilities if item.get("category")}
        )
        lines = sorted(
            {int(line) for item in vulnerabilities for line in (item.get("lines") or [])}
        )
        metadata: dict[str, Any] = {
            "categories": categories,
            "lines": lines,
            "upstream_name": entry.get("name"),
            "upstream_source": entry.get("source"),
        }

        records.append(
            DatasetRecord(
                record_id=f"{SMARTBUGS_DATASET}:{path}",
                source_dataset=SMARTBUGS_DATASET,
                source_ref=path,
                code=code,
                project=str(entry.get("source") or ""),
                contract_name=str(entry.get("name") or path),
                compiler_version=str(entry["pragma"]) if entry.get("pragma") else None,
                label="vulnerable",
                label_provenance=SMARTBUGS_PROVENANCE,
                license="Apache-2.0",
                upstream_revision=SMARTBUGS_REVISION,
                metadata=metadata,
            )
        )

    return records


def fetch_smartbugs_files(
    revision: str = SMARTBUGS_REVISION,
    *,
    timeout: int = 180,
) -> dict[str, str]:
    """Fetch the corpus at ``revision``.

    One request fetches the upstream archive; nothing is written to disk,
    so nothing can escape the working directory. Only the label file and
    the Solidity sources are kept.
    """
    url = SMARTBUGS_ARCHIVE_URL.format(revision=revision)
    if not url.startswith("https://"):
        raise ValueError("the corpus is only fetched over https")

    request = urllib.request.Request(  # noqa: S310 - the url is https only
        url,
        headers={"User-Agent": "cyberstratum-dataset-ingest"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - https only
        payload = response.read()

    files: dict[str, str] = {}
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
        for member in archive.getmembers():
            if not member.isfile():
                continue
            name = member.name.split("/", 1)[-1]
            if name != SMARTBUGS_LABELS and not name.endswith(".sol"):
                continue
            handle = archive.extractfile(member)
            if handle is None:
                continue
            files[name] = handle.read().decode("utf-8", "replace")
    return files


def ingest_smartbugs(
    revision: str = SMARTBUGS_REVISION,
    *,
    files: Mapping[str, str] | None = None,
    seed: int = 0,
    ratios: Sequence[float] = DEFAULT_RATIOS,
) -> DatasetManifest:
    """Fetch, parse and ingest the SmartBugs Curated corpus.

    The manifest records the licence, the pinned revision, the hash of the
    records and the hash of the fetched corpus.
    """
    corpus = dict(files) if files is not None else fetch_smartbugs_files(revision)
    records = parse_smartbugs(corpus)
    return ingest_dataset(
        records,
        dataset=SMARTBUGS_DATASET,
        upstream_revision=revision,
        corpus_sha256=corpus_content_hash(corpus),
        seed=seed,
        ratios=ratios,
    )
