"""The SmartBugs Curated loader.

The corpus is fetched at a pinned revision, hashed, and ingested through
the ordinary door. These tests do not touch the network: the parsing and
the ingest are pure functions of the fetched files.
"""

from __future__ import annotations

import json

import pytest

from evm_dataset.family import assign_family_key
from evm_dataset.ingest import ingest_dataset
from evm_dataset.labels import (
    LabelTier,
    may_be_used_as_evaluation_ground_truth,
    may_be_used_for_exploratory_training,
)
from evm_dataset.licensing import IngestRefusalError, license_for
from evm_dataset.manifest import verify_manifest
from evm_dataset.smartbugs import (
    SMARTBUGS_DATASET,
    SMARTBUGS_LABELS,
    SMARTBUGS_REVISION,
    corpus_content_hash,
    ingest_smartbugs,
    parse_smartbugs,
)


def _source(marker: str) -> str:
    return (
        "// SPDX-License-Identifier: MIT\n"
        "pragma solidity ^0.4.24;\n"
        f"contract {marker} {{\n"
        "    uint public value;\n"
        "    function set(uint amount) public {{ value = amount; }}\n"
        "}\n"
    )


def _entry(name: str, category: str, line: int, source: str) -> dict[str, object]:
    return {
        "name": name,
        "path": f"dataset/{category}/{name}",
        "pragma": "0.4.24",
        "source": source,
        "vulnerabilities": [{"lines": [line], "category": category}],
    }


def _corpus() -> dict[str, str]:
    """Seven contracts in four families: two pairs are forks of each other."""
    entries = [
        _entry("alpha.sol", "reentrancy", 12, "https://example.org/alpha"),
        _entry("alpha_fork.sol", "reentrancy", 12, "https://example.org/alpha"),
        _entry("beta.sol", "access_control", 7, "https://example.org/beta"),
        _entry("beta_fork.sol", "access_control", 7, "https://example.org/beta"),
        _entry("gamma.sol", "arithmetic", 9, "https://example.org/gamma"),
        _entry("delta.sol", "arithmetic", 9, "https://example.org/delta"),
        _entry("epsilon.sol", "denial_of_service", 3, "https://example.org/epsilon"),
    ]
    files = {SMARTBUGS_LABELS: json.dumps(entries, indent=2)}
    for entry in entries:
        marker = str(entry["name"]).replace(".sol", "").replace("_fork", "")
        files[str(entry["path"])] = _source(marker)
    return files


def test_the_corpus_is_parsed_into_records() -> None:
    """Every contract the corpus carries becomes a record."""
    records = parse_smartbugs(_corpus())
    assert len(records) == 7
    for record in records:
        assert record.source_dataset == SMARTBUGS_DATASET
        assert record.source_ref.startswith("dataset/")
        assert record.code.strip()


def test_the_upstream_label_is_kept_with_its_source() -> None:
    """The label says where it came from, not only what it says."""
    records = parse_smartbugs(_corpus())
    record = next(item for item in records if item.contract_name == "gamma.sol")
    assert record.label == "vulnerable"
    assert record.label_provenance == "upstream curated"
    assert record.project == "https://example.org/gamma"
    assert record.compiler_version == "0.4.24"
    assert record.metadata["categories"] == ["arithmetic"]
    assert record.metadata["lines"] == [9]
    assert record.metadata["upstream_source"] == "https://example.org/gamma"


def test_the_upstream_label_is_never_reviewed_ground_truth() -> None:
    """Nobody in this platform reviewed these labels, so they are heuristic."""
    record = parse_smartbugs(_corpus())[0]
    assert record.label_tier is LabelTier.HEURISTIC
    assert may_be_used_for_exploratory_training(record.label_tier)
    assert not may_be_used_as_evaluation_ground_truth(record.label_tier)


def test_a_record_the_corpus_does_not_carry_is_not_invented() -> None:
    """A label without a file is left out rather than fabricated."""
    files = _corpus()
    files[SMARTBUGS_LABELS] = json.dumps(
        [_entry("missing.sol", "reentrancy", 3, "https://example.org/missing")]
    )
    assert parse_smartbugs(files) == []


def test_a_corpus_without_the_label_file_is_refused() -> None:
    """A corpus that carries no labels is not parsed into guesses."""
    with pytest.raises(ValueError, match="vulnerabilities.json"):
        parse_smartbugs({"dataset/reentrancy/alpha.sol": _source("Alpha")})


def test_forks_share_one_family() -> None:
    """A fork of a contract does not land in a different split."""
    records = parse_smartbugs(_corpus())
    by_name = {record.contract_name: record for record in records}
    assert assign_family_key(by_name["alpha.sol"]) == assign_family_key(by_name["alpha_fork.sol"])
    assert assign_family_key(by_name["alpha.sol"]) != assign_family_key(by_name["beta.sol"])


def test_the_content_hash_is_stable_and_notices_a_change() -> None:
    """The same corpus hashes the same; a changed corpus does not."""
    files = _corpus()
    first = corpus_content_hash(files)
    assert first == corpus_content_hash(dict(files))

    changed = dict(files)
    changed["dataset/arithmetic/gamma.sol"] = _source("changed")
    assert corpus_content_hash(changed) != first


def test_the_corpus_is_ingested_with_its_terms() -> None:
    """The manifest says which licence, which revision, and which bytes."""
    files = _corpus()
    manifest = ingest_smartbugs(files=files)

    licence = license_for(SMARTBUGS_DATASET)
    assert licence.spdx_id == "Apache-2.0"
    assert licence.upstream_revision == SMARTBUGS_REVISION

    provenance = manifest.provenance[0]
    assert provenance["license"]["spdx_id"] == "Apache-2.0"
    assert provenance["upstream_revision"] == SMARTBUGS_REVISION
    assert provenance["extra"]["corpus_sha256"] == corpus_content_hash(files)
    assert manifest.content_hashes[SMARTBUGS_DATASET]


def test_the_ingested_manifest_verifies_against_its_records() -> None:
    """A manifest says what it was built from, and can be checked."""
    files = _corpus()
    manifest = ingest_smartbugs(files=files)
    records = parse_smartbugs(files)

    assert verify_manifest(manifest, records).matches


def test_a_changed_corpus_does_not_verify() -> None:
    """Changed content under the same name is caught."""
    files = _corpus()
    manifest = ingest_smartbugs(files=files)

    changed = dict(files)
    changed["dataset/arithmetic/gamma.sol"] = _source("changed")
    records = parse_smartbugs(changed)

    assert not verify_manifest(manifest, records).matches


def test_a_lying_content_hash_is_refused() -> None:
    """A caller cannot assert a hash the content does not have."""
    records = parse_smartbugs(_corpus())
    with pytest.raises(IngestRefusalError, match="does not match the content"):
        ingest_dataset(
            records,
            dataset=SMARTBUGS_DATASET,
            upstream_revision=SMARTBUGS_REVISION,
            content_sha256="0" * 64,
        )


def test_an_unpinned_revision_is_refused_for_this_corpus() -> None:
    """The corpus cannot be ingested from a moving branch."""
    records = parse_smartbugs(_corpus())
    with pytest.raises(IngestRefusalError, match="revision"):
        ingest_dataset(records, dataset=SMARTBUGS_DATASET, upstream_revision="main")


def test_the_command_line_ingests_the_pinned_corpus(monkeypatch) -> None:
    """The operator can ingest the real corpus from the command line."""
    from evm_dataset import cli as cli_module
    from evm_dataset.cli import main as cli_main

    corpus = _corpus()
    captured: dict[str, object] = {}

    def fake_ingest(revision=None, *, files=None, seed=0, ratios=None):
        captured["revision"] = revision
        return ingest_smartbugs(files=corpus, seed=seed, ratios=ratios or (0.7, 0.15, 0.15))

    monkeypatch.setattr(cli_module, "ingest_smartbugs", fake_ingest, raising=False)

    exit_code = cli_main(["--smartbugs"])
    assert exit_code == 0
    assert captured["revision"] == SMARTBUGS_REVISION
