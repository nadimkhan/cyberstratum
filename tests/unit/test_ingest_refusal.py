"""An ingest that cannot be accounted for is refused.

A dataset is ingested only when the platform can say what it is, which
licence it is under, which upstream revision it came from, and what its
content hashes to. Anything less is a refusal, not a warning.
"""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from evm_dataset.ingest import ingest_dataset
from evm_dataset.licensing import (
    IngestRefusalError,
    is_pinned_revision,
    license_for,
    require_ingestable,
)
from evm_dataset.manifest import build_manifest, dataset_content_sha256, verify_manifest
from evm_dataset.records import DatasetRecord
from evm_dataset.smoke import smoke_records


def _record(record_id: str, dataset: str = "swc_registry") -> DatasetRecord:
    """One record from one dataset, in its own family."""
    return DatasetRecord(
        record_id=record_id,
        source_dataset=dataset,
        source_ref=f"{dataset}/{record_id}.sol",
        code=f"contract {record_id} {{ function f() public {{}} }}",
        project=f"project-{record_id}",
        contract_name=record_id,
        swc_id="SWC-101",
        label="true",
        label_provenance="reviewed",
    )


def _records(count: int = 6, dataset: str = "swc_registry") -> list[DatasetRecord]:
    return [_record(f"r{index}", dataset) for index in range(count)]


def test_a_dataset_with_no_licence_record_is_refused() -> None:
    """An unknown dataset inherits no terms at all."""
    with pytest.raises(IngestRefusalError) as error:
        ingest_dataset(_records(dataset="not_a_dataset"), dataset="not_a_dataset")
    assert "licence" in error.value.reason
    assert error.value.dataset == "not_a_dataset"


def test_a_dataset_whose_licence_is_not_settled_is_refused() -> None:
    """Web3Bugs has no single licence, so it cannot be ingested."""
    with pytest.raises(IngestRefusalError) as error:
        ingest_dataset(_records(dataset="web3bugs"), dataset="web3bugs")
    assert "per-repository" in error.value.reason


def test_a_dataset_with_no_pinned_revision_is_refused() -> None:
    """A corpus whose revision nobody has pinned cannot be ingested."""
    with pytest.raises(IngestRefusalError) as error:
        ingest_dataset(_records(dataset="smartbugs_curated"), dataset="smartbugs_curated")
    assert "revision" in error.value.reason


def test_a_moving_revision_is_refused() -> None:
    """A branch moves, so it cannot pin a corpus."""
    with pytest.raises(IngestRefusalError) as error:
        ingest_dataset(_records(), dataset="swc_registry", upstream_revision="main")
    assert "revision" in error.value.reason


def test_a_dataset_with_no_content_hash_is_refused() -> None:
    """Content that cannot be hashed cannot be ingested."""
    with pytest.raises(IngestRefusalError) as error:
        ingest_dataset(_records(), dataset="swc_registry", content_sha256="not-a-hash")
    assert "content hash" in error.value.reason


def test_a_record_from_another_dataset_is_refused() -> None:
    """A corpus is ingested as a whole or not at all."""
    records = _records(3) + [_record("other", "smartbugs_curated")]
    with pytest.raises(IngestRefusalError) as error:
        ingest_dataset(records, dataset="swc_registry")
    assert "belongs to" in error.value.reason


def test_an_ingest_that_can_be_accounted_for_produces_a_manifest() -> None:
    """The manifest says what was ingested, under which terms."""
    records = _records()
    manifest = ingest_dataset(records, dataset="swc_registry")

    assert manifest.record_count == len(records)
    assert manifest.content_hashes["swc_registry"] == dataset_content_sha256(records)
    provenance = manifest.provenance[0]
    assert provenance["license"]["spdx_id"] == "MIT"
    assert provenance["upstream_revision"] == "1b6227074ecd180b374e4844153afdda0332f979"
    assert provenance["extra"]["content_sha256"] == manifest.content_hashes["swc_registry"]


def test_the_content_hash_changes_when_the_content_changes() -> None:
    """The hash is of the content, so changed content means a changed hash."""
    records = _records()
    first = ingest_dataset(records, dataset="swc_registry").content_hashes

    changed = list(records)
    changed[0] = replace(changed[0], code="contract changed { function g() public {} }")
    second = ingest_dataset(changed, dataset="swc_registry").content_hashes

    assert first != second


def test_the_verification_notices_a_changed_corpus() -> None:
    """A corpus that changed under the manifest does not verify."""
    records = _records()
    manifest = ingest_dataset(records, dataset="swc_registry")

    changed = list(records)
    changed[0] = replace(changed[0], code="contract changed { function g() public {} }")
    verification = verify_manifest(manifest, changed)

    assert not verification
    assert verification.mismatched_records


def test_an_untouched_ingest_verifies() -> None:
    """A corpus that has not changed still verifies."""
    records = _records()
    manifest = ingest_dataset(records, dataset="swc_registry")
    assert verify_manifest(manifest, records)


def test_the_plain_manifest_path_is_unchanged() -> None:
    """Building a manifest without an ingest is still possible."""
    manifest = build_manifest(smoke_records(), seed=3)
    assert manifest.record_count > 0


def test_a_pinned_revision_is_recognised() -> None:
    """A commit or a tag pins; a branch does not."""
    assert is_pinned_revision("1b6227074ecd180b374e4844153afdda0332f979")
    assert is_pinned_revision("v1.0.0")
    assert not is_pinned_revision("main")
    assert not is_pinned_revision("MASTER")
    assert not is_pinned_revision(None)
    assert not is_pinned_revision("   ")


def test_the_check_returns_the_licence_when_everything_is_present() -> None:
    """The check hands back the licence when it is satisfied."""
    licence = license_for("swc_registry")
    assert (
        require_ingestable(
            dataset="swc_registry",
            dataset_license=licence,
            upstream_revision=licence.upstream_revision,
            content_sha256="0" * 64,
        )
        is licence
    )


def test_the_command_line_refuses_a_dataset_it_cannot_account_for(
    tmp_path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The operator is told the corpus was refused, and why."""
    from evm_dataset.cli import main as cli_main

    path = tmp_path / "corpus.jsonl"
    path.write_text(
        "\n".join(
            json.dumps(
                {
                    "record_id": record.record_id,
                    "source_dataset": record.source_dataset,
                    "source_ref": record.source_ref,
                    "code": record.code,
                    "project": record.project,
                    "contract_name": record.contract_name,
                    "swc_id": record.swc_id,
                    "label": record.label,
                    "label_provenance": record.label_provenance,
                }
            )
            for record in _records(dataset="web3bugs")
        ),
        encoding="utf-8",
    )

    exit_code = cli_main(["--ingest", str(path), "--dataset", "web3bugs"])
    output = capsys.readouterr().out

    assert exit_code == 2
    assert "ingest refused" in output
    assert "per-repository" in output


def test_the_command_line_ingests_a_corpus_it_can_account_for(
    tmp_path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A corpus that can be accounted for is ingested, and says so."""
    from evm_dataset.cli import main as cli_main

    path = tmp_path / "corpus.jsonl"
    path.write_text(
        "\n".join(
            json.dumps(
                {
                    "record_id": record.record_id,
                    "source_dataset": record.source_dataset,
                    "source_ref": record.source_ref,
                    "code": record.code,
                    "project": record.project,
                    "contract_name": record.contract_name,
                    "swc_id": record.swc_id,
                    "label": record.label,
                    "label_provenance": record.label_provenance,
                }
            )
            for record in _records()
        ),
        encoding="utf-8",
    )

    exit_code = cli_main(["--ingest", str(path), "--dataset", "swc_registry"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "manifest hash:" in output
    assert "content hash: swc_registry" in output
    assert "self-verification: ok" in output
