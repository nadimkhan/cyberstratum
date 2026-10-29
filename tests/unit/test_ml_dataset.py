"""Tests for dataset loading, provenance and family-level splitting."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evm_ml.dataset import (
    Dataset,
    Sample,
    assign_split,
    load_dataset,
    split_dataset,
)

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "dataset_smoke.jsonl"


def _write(tmp_path: Path, lines: list[dict]) -> Path:
    path = tmp_path / "dataset.jsonl"
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8")
    return path


def test_a_family_always_lands_in_the_same_split():
    for family in ("UniswapV2", "DAI", "Compound", "MakerDAO"):
        assignments = {assign_split(family) for _ in range(10)}
        assert len(assignments) == 1


def test_the_split_is_deterministic_across_calls():
    assert assign_split("UniswapV2") == assign_split("UniswapV2")


def test_no_family_appears_in_two_splits():
    dataset = Dataset(
        samples=[
            Sample(
                contract_id=f"c{index}",
                family=f"family-{index % 7}",
                bytecode=b"\x00",
                labels={"reentrancy": index % 2 == 0},
            )
            for index in range(70)
        ]
    )
    splits = split_dataset(dataset)

    seen: dict[str, str] = {}
    for split_name, samples in splits.items():
        for sample in samples:
            previous = seen.setdefault(sample.family, split_name)
            assert previous == split_name, (
                f"family {sample.family} leaked into {split_name} and {previous}"
            )


def test_labels_must_be_booleans(tmp_path: Path):
    path = _write(
        tmp_path,
        [
            {
                "contract_id": "c1",
                "family": "f1",
                "bytecode": "00",
                "labels": {"reentrancy": "yes"},
            }
        ],
    )
    with pytest.raises(ValueError, match="must be a boolean"):
        load_dataset(path)


def test_missing_required_fields_are_reported(tmp_path: Path):
    path = _write(tmp_path, [{"contract_id": "c1", "bytecode": "00"}])
    with pytest.raises(ValueError, match="missing 'family'"):
        load_dataset(path)


def test_invalid_hex_is_reported(tmp_path: Path):
    path = _write(
        tmp_path,
        [{"contract_id": "c1", "family": "f1", "bytecode": "zz"}],
    )
    with pytest.raises(ValueError, match="not valid hex"):
        load_dataset(path)


def test_the_0x_prefix_is_accepted(tmp_path: Path):
    path = _write(
        tmp_path,
        [{"contract_id": "c1", "family": "f1", "bytecode": "0x6001"}],
    )
    dataset = load_dataset(path)
    assert dataset.samples[0].bytecode == bytes.fromhex("6001")


def test_the_dataset_header_carries_the_provenance(tmp_path: Path):
    path = _write(
        tmp_path,
        [
            {
                "__dataset__": {
                    "name": "demo",
                    "description": "a demo dataset",
                    "provenance": {"source": "unit-test", "license": "MIT"},
                }
            },
            {"contract_id": "c1", "family": "f1", "bytecode": "6001"},
        ],
    )
    dataset = load_dataset(path)
    assert dataset.name == "demo"
    assert dataset.description == "a demo dataset"
    assert dataset.provenance["license"] == "MIT"


def test_the_manifest_records_the_required_provenance_fields():
    sample = Sample(
        contract_id="c1",
        family="f1",
        bytecode=b"\x60\x01",
        labels={"reentrancy": True},
        chain="ethereum",
        compiler="0.8.24",
        source="sourcify",
        license="MIT",
        label_source="manual-review",
        label_confidence="high",
    )
    dataset = Dataset(samples=[sample], name="demo")
    manifest = dataset.manifest()

    record = manifest["samples"][0]
    for field in (
        "source",
        "license",
        "family",
        "chain",
        "compiler",
        "label_source",
        "label_confidence",
        "code_sha256",
    ):
        assert field in record, f"missing {field}"

    assert manifest["label_categories"]
    assert manifest["family_count"] == 1


def test_the_dataset_fingerprint_changes_with_content():
    first = Dataset(samples=[Sample("c1", "f1", b"\x00", {})])
    second = Dataset(samples=[Sample("c1", "f1", b"\x01", {})])
    assert first.fingerprint() != second.fingerprint()


def test_the_smoke_fixture_loads_with_real_bytecode():
    dataset = load_dataset(FIXTURE)
    assert len(dataset.samples) > 0
    for sample in dataset.samples:
        assert len(sample.bytecode) > 0
        assert sample.family
        assert sample.label_source
        assert sample.label_confidence in {"low", "medium", "high"}
