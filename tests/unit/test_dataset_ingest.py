"""Tests for licensing-safe dataset ingestion.

These cover the four failures ADR-0015 is written to prevent: poisoning
by unknown labels, leakage across the train/test boundary, unreproducible
manifests, and a model being promoted on data nobody reviewed.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

# The package is installed in editable mode (``uv pip install -e
# packages/dataset_ingest``), so it is imported by its package name exactly
# like every other project package. If it is not installed, this test fails
# rather than silently testing a copy on sys.path.
from evm_dataset.cli import main as cli_main
from evm_dataset.dedup import (
    DedupTier,
    deduplicate,
    exact_hash,
    near_duplicate_hash,
    normalised_hash,
)
from evm_dataset.family import assign_family_key
from evm_dataset.labels import (
    LabelTier,
    is_unknown_label,
    label_tier_for,
    may_be_used_as_negative,
)
from evm_dataset.licensing import (
    KNOWN_DATASET_LICENCES,
    license_for,
)
from evm_dataset.loader import load_jsonl
from evm_dataset.manifest import build_manifest, verify_manifest
from evm_dataset.promotion import can_promote
from evm_dataset.records import DatasetRecord
from evm_dataset.smoke import smoke_records
from evm_dataset.split import SplitError, split_by_family

SAMPLE = """pragma solidity ^0.8.20;

contract Vault {
    mapping(address => uint256) public balances;

    function withdraw(uint256 amount) external {
        require(balances[msg.sender] >= amount, "insufficient");
        balances[msg.sender] -= amount;
        (bool ok, ) = msg.sender.call{value: amount}("");
        require(ok, "transfer failed");
    }
}
"""


def _record(
    record_id: str,
    code: str,
    *,
    project: str = "acme-vault",
    swc_id: str | None = "SWC-107",
    label: str | None = "true",
    label_provenance: str | None = "reviewed",
) -> DatasetRecord:
    return DatasetRecord(
        record_id=record_id,
        source_dataset="test",
        source_ref=f"test/{record_id}.sol",
        code=code,
        project=project,
        contract_name=record_id,
        swc_id=swc_id,
        label=label,
        label_provenance=label_provenance,
    )


# --------------------------------------------------------------------------
# Deduplication
# --------------------------------------------------------------------------


def test_the_exact_hash_is_stable_across_calls():
    assert exact_hash(SAMPLE) == exact_hash(SAMPLE)


def test_the_exact_hash_differs_for_different_content():
    assert exact_hash(SAMPLE) != exact_hash(SAMPLE + "\n// a trailing comment\n")


def test_the_normalised_hash_is_stable_across_calls():
    assert normalised_hash(SAMPLE) == normalised_hash(SAMPLE)


def test_the_normalised_hash_differs_for_different_content():
    assert normalised_hash(SAMPLE) != normalised_hash(SAMPLE.replace("amount", "value"))


def test_the_normalised_hash_ignores_comments_and_whitespace():
    noisy = (
        "/* a block comment */\n"
        + SAMPLE.replace("\n", "\n\n").replace("    ", "\t")
        + "\n// a trailing comment\n"
    )
    assert normalised_hash(noisy) == normalised_hash(SAMPLE)


def test_the_exact_hash_is_sensitive_to_comments_and_whitespace():
    noisy = (
        "/* a block comment */\n"
        + SAMPLE.replace("\n", "\n\n").replace("    ", "\t")
        + "\n// a trailing comment\n"
    )
    assert exact_hash(noisy) != exact_hash(SAMPLE)


def test_the_near_duplicate_signature_is_stable_across_calls():
    assert near_duplicate_hash(SAMPLE) == near_duplicate_hash(SAMPLE)


def test_the_near_duplicate_signature_ignores_renamed_variables():
    renamed = SAMPLE.replace("balances", "ledger")
    assert near_duplicate_hash(renamed) == near_duplicate_hash(SAMPLE)


def test_the_near_duplicate_signature_is_stable_across_processes(tmp_path: Path):
    # The builtin hash() is salted per interpreter run, so a signature
    # built on it would differ between runs. This checks a fresh process.
    package_root = str(Path(__file__).resolve().parents[2] / "packages" / "dataset_ingest")
    environment = dict(os.environ)
    existing = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = (
        f"{package_root}{os.pathsep}{existing}" if existing else package_root
    )
    code_file = tmp_path / "code.txt"
    code_file.write_text(SAMPLE, encoding="utf-8")
    script = (
        "from evm_dataset.dedup import near_duplicate_hash;"
        "print(near_duplicate_hash(open('code.txt', encoding='utf-8').read()))"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=True,
        env=environment,
        cwd=str(tmp_path),
    )
    assert completed.stdout.strip() == near_duplicate_hash(SAMPLE)


def test_the_near_duplicate_signature_differs_for_different_contracts():
    other = """pragma solidity ^0.8.20;

contract Escrow {
    address public payer;
    uint256 public amount;

    function release() external {
        require(msg.sender == payer, "not payer");
        amount = 0;
    }
}
"""
    assert near_duplicate_hash(other) != near_duplicate_hash(SAMPLE)


def test_a_renamed_copy_is_matched_by_the_near_duplicate_tier():
    renamed = SAMPLE.replace("balances", "ledger")
    results = deduplicate([_record("a", SAMPLE), _record("b", renamed)])
    assert results[0].matched_tier is DedupTier.UNIQUE
    assert results[1].matched_tier is DedupTier.NEAR_DUPLICATE
    assert results[0].cluster_id == results[1].cluster_id


def test_a_comment_only_copy_is_matched_by_the_normalised_tier():
    commented = SAMPLE + "\n// an added comment\n"
    results = deduplicate([_record("a", SAMPLE), _record("b", commented)])
    assert results[1].matched_tier is DedupTier.NORMALISED
    assert results[1].exact != results[0].exact


def test_an_identical_copy_is_matched_by_the_exact_tier():
    results = deduplicate([_record("a", SAMPLE), _record("b", SAMPLE)])
    assert results[1].matched_tier is DedupTier.EXACT
    assert results[1].exact == results[0].exact


# --------------------------------------------------------------------------
# Labels
# --------------------------------------------------------------------------


def test_a_missing_label_is_unlabelled():
    assert label_tier_for(None) is LabelTier.UNLABELLED
    assert is_unknown_label(None)


def test_a_not_yet_determined_label_is_unlabelled():
    assert label_tier_for("not-yet-determined") is LabelTier.UNLABELLED
    assert label_tier_for("Not Yet Determined") is LabelTier.UNLABELLED
    assert label_tier_for("unknown") is LabelTier.UNLABELLED


def test_an_unlabelled_label_is_never_used_as_a_negative():
    assert may_be_used_as_negative(LabelTier.UNLABELLED) is False
    assert may_be_used_as_negative(LabelTier.HEURISTIC) is False
    assert may_be_used_as_negative(LabelTier.REVIEWED) is True


def test_a_known_label_with_reviewed_provenance_is_reviewed():
    assert label_tier_for("true", label_provenance="reviewed") is LabelTier.REVIEWED


def test_a_known_label_with_rule_provenance_is_heuristic():
    assert label_tier_for("true", label_provenance="heuristic-rule") is LabelTier.HEURISTIC


def test_an_unknown_label_stays_unlabelled_even_if_claimed_reviewed():
    assert label_tier_for("not-yet-determined", label_provenance="reviewed") is LabelTier.UNLABELLED


def test_an_unlabelled_record_has_no_boolean_verdict():
    record = _record("a", SAMPLE, label="not-yet-determined")
    assert record.label_tier is LabelTier.UNLABELLED
    assert record.is_vulnerable is None


# --------------------------------------------------------------------------
# Families and splits
# --------------------------------------------------------------------------


def test_two_members_of_the_same_family_get_the_same_family_key():
    first = _record("a", SAMPLE, project="acme-vault", swc_id="SWC-107")
    second = _record("b", SAMPLE + "\n// different\n", project="acme-vault", swc_id="SWC-107")
    assert assign_family_key(first) == assign_family_key(second)


def test_different_families_get_different_family_keys():
    first = _record("a", SAMPLE, project="acme-vault", swc_id="SWC-107")
    second = _record("b", SAMPLE, project="other-vault", swc_id="SWC-107")
    assert assign_family_key(first) != assign_family_key(second)


def test_two_members_of_the_same_family_land_in_the_same_split():
    records = smoke_records()
    split = split_by_family(records, seed=7)
    assert split.split_for_record("smoke-004") == split.split_for_record("smoke-005")
    assert split.split_for_record("smoke-001") == split.split_for_record("smoke-006")


def test_no_family_appears_in_two_splits():
    records = smoke_records()
    split = split_by_family(records, seed=7)
    seen: dict[str, str] = {}
    for name, group in split.by_name().items():
        for record in group:
            family_key = assign_family_key(record)
            previous = seen.setdefault(family_key, name)
            assert previous == name, f"family {family_key} leaked into {name} and {previous}"


def test_the_split_covers_every_record_exactly_once():
    records = smoke_records()
    split = split_by_family(records, seed=7)
    ids = [record.record_id for group in split.by_name().values() for record in group]
    assert len(ids) == len(set(ids))
    assert set(ids) == {record.record_id for record in records}


def test_the_split_is_deterministic_for_the_same_seed():
    records = smoke_records()
    first = split_by_family(records, seed=11)
    second = split_by_family(records, seed=11)
    assert first.record_ids() == second.record_ids()
    assert first.family_to_split == second.family_to_split


def test_a_split_that_would_be_empty_is_refused():
    records = [
        _record("a", SAMPLE, project="p1"),
        _record("b", SAMPLE + "//x\n", project="p2"),
    ]
    with pytest.raises(SplitError, match="non-empty splits"):
        split_by_family(records, seed=0)


# --------------------------------------------------------------------------
# Manifests
# --------------------------------------------------------------------------


def test_the_manifest_hash_is_identical_when_regenerated():
    records = smoke_records()
    first = build_manifest(records, seed=3)
    second = build_manifest(records, seed=3)
    assert first.content_hash == second.content_hash
    assert first.to_dict() == second.to_dict()


def test_the_manifest_hash_changes_when_a_record_changes():
    records = smoke_records()
    original = build_manifest(records, seed=3)
    tampered = list(records)
    tampered[0] = replace(tampered[0], code=tampered[0].code + "\n// injected\n")
    assert build_manifest(tampered, seed=3).content_hash != original.content_hash


def test_the_manifest_contains_the_families_splits_and_licences():
    records = smoke_records()
    manifest = build_manifest(records, seed=3)
    assert manifest.family_count >= 3
    assert set(manifest.split_assignment) == {record.record_id for record in records}
    assert sum(manifest.split_counts.values()) == len(records)
    assert manifest.label_tier_counts["unlabelled"] == 1
    licences = {entry["license"]["dataset"]: entry["license"] for entry in manifest.provenance}
    assert licences["smartbugs_curated"]["spdx_id"] == "Apache-2.0"
    assert licences["swc_registry"]["spdx_id"] == "MIT"
    assert licences["web3bugs"]["per_repository_audit_required"] is True
    assert all(entry["license"]["note"].strip() for entry in manifest.provenance)


def test_verify_manifest_accepts_an_untouched_manifest():
    records = smoke_records()
    manifest = build_manifest(records, seed=3)
    result = verify_manifest(manifest, records)
    assert result.matches
    assert result.actual_hash == result.expected_hash


def test_verify_manifest_detects_a_tampered_record():
    records = smoke_records()
    manifest = build_manifest(records, seed=3)
    tampered = list(records)
    tampered[0] = replace(tampered[0], code=tampered[0].code + "\n// injected\n")
    result = verify_manifest(manifest, tampered)
    assert not result.matches
    assert "smoke-001" in result.mismatched_records


# --------------------------------------------------------------------------
# Promotion gate
# --------------------------------------------------------------------------


def test_promotion_is_refused_for_heuristic_only_labels():
    records = [
        _record(
            "a",
            SAMPLE,
            project="p1",
            swc_id="SWC-1",
            label_provenance="heuristic-rule",
        ),
        _record(
            "b",
            SAMPLE + "// x\n",
            project="p2",
            swc_id="SWC-2",
            label_provenance="heuristic-rule",
        ),
        _record(
            "c",
            SAMPLE + "// y\n",
            project="p3",
            swc_id="SWC-3",
            label_provenance="heuristic-rule",
        ),
    ]
    manifest = build_manifest(records, seed=0)
    decision = can_promote(manifest)
    assert not decision.allowed
    assert decision.heuristic_count == 3
    assert "reviewed" in decision.reason


def test_promotion_is_allowed_for_reviewed_only_labels():
    records = [
        _record("a", SAMPLE, project="p1", swc_id="SWC-1"),
        _record(
            "b",
            SAMPLE + "// x\n",
            project="p2",
            swc_id="SWC-2",
            label="false",
        ),
        _record(
            "c",
            SAMPLE + "// y\n",
            project="p3",
            swc_id="SWC-3",
            label="false",
        ),
    ]
    manifest = build_manifest(records, seed=0)
    decision = can_promote(manifest)
    assert decision.allowed
    assert decision.reviewed_count == 3
    assert decision.heuristic_count == 0
    assert decision.reason


def test_promotion_is_refused_when_a_record_is_unlabelled():
    records = [
        _record("a", SAMPLE, project="p1", swc_id="SWC-1"),
        _record(
            "b",
            SAMPLE + "// x\n",
            project="p2",
            swc_id="SWC-2",
            label="not-yet-determined",
        ),
        _record(
            "c",
            SAMPLE + "// y\n",
            project="p3",
            swc_id="SWC-3",
            label="false",
        ),
    ]
    manifest = build_manifest(records, seed=0)
    decision = can_promote(manifest)
    assert not decision.allowed
    assert decision.unlabelled_count == 1
    assert decision.reason


def test_the_smoke_dataset_itself_cannot_be_promoted():
    decision = can_promote(build_manifest(smoke_records(), seed=0))
    assert not decision.allowed


# --------------------------------------------------------------------------
# Licensing
# --------------------------------------------------------------------------


def test_the_known_licences_are_enumerable_as_data():
    assert set(KNOWN_DATASET_LICENCES) == {
        "smartbugs_curated",
        "defihacklabs",
        "swc_registry",
        "web3bugs",
    }


def test_the_known_licences_have_the_expected_spdx_identifiers():
    assert license_for("smartbugs_curated").spdx_id == "Apache-2.0"
    assert license_for("defihacklabs").spdx_id == "Apache-2.0"
    assert license_for("swc_registry").spdx_id == "MIT"


def test_the_redistribution_terms_are_recorded():
    assert license_for("smartbugs_curated").derived_artifacts_may_be_redistributed is True
    assert license_for("web3bugs").derived_artifacts_may_be_redistributed is False


def test_web3bugs_requires_a_per_repository_audit():
    licence = license_for("web3bugs")
    assert licence.per_repository_audit_required
    assert not licence.is_resolved


def test_every_licence_carries_a_human_readable_note():
    for licence in KNOWN_DATASET_LICENCES.values():
        assert licence.note.strip()


def test_an_unknown_dataset_has_no_licence():
    with pytest.raises(KeyError):
        license_for("no-such-dataset")


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def test_the_cli_runs_the_smoke_pipeline_offline(capsys: pytest.CaptureFixture[str]):
    exit_code = cli_main([])
    output = capsys.readouterr().out
    assert exit_code == 0
    assert "manifest hash:" in output
    assert "-- family grouping --" in output
    assert "-- split --" in output
    assert "-- promotion gate --" in output
    assert "NOT benchmark ground truth" in output


# --------------------------------------------------------------------------
# Loader
# --------------------------------------------------------------------------


def test_a_missing_file_loads_as_an_empty_list(tmp_path: Path):
    assert load_jsonl(tmp_path / "absent.jsonl") == []


def test_a_jsonl_file_is_loaded_into_records(tmp_path: Path):
    path = tmp_path / "records.jsonl"
    payload = {
        "record_id": "r1",
        "source_dataset": "smartbugs_curated",
        "source_ref": "contracts/A.sol",
        "code": SAMPLE,
        "label": "true",
        "label_provenance": "reviewed",
    }
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    records = load_jsonl(path)
    assert len(records) == 1
    assert records[0].record_id == "r1"
    assert records[0].label_tier is LabelTier.REVIEWED
