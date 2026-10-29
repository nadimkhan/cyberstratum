# evm-dataset

Licensing-safe dataset ingestion for CyberStratum, implementing ADR-0015
(`docs/adr/0015-dataset-and-model-lifecycle.md`).

The package is self-contained: no network access, no database, no model
training. It provides:

* `evm_dataset.licensing` - per-dataset licence and provenance records
  (SmartBugs Curated Apache-2.0, DeFiHackLabs Apache-2.0, SWC Registry
  MIT, Web3Bugs per-repository audit required).
* `evm_dataset.labels` - the three label tiers. A missing or
  `not-yet-determined` label is `unlabelled`, never a negative.
* `evm_dataset.dedup` - exact, normalised and near-duplicate
  deduplication, each producing a stable hash id.
* `evm_dataset.family` - deterministic `family_key` assignment.
* `evm_dataset.split` - family-level train/validation/test splits.
* `evm_dataset.manifest` - immutable, content-addressed dataset
  manifests, plus `verify_manifest`.
* `evm_dataset.promotion` - the promotion gate: only reviewed labels may
  be promoted.
* `evm_dataset.loader` - JSONL loading.
* `evm_dataset.smoke` - a tiny **synthetic** dataset whose labels are
  heuristic, not benchmark ground truth.

## Usage

```bash
python -m evm_dataset.cli
```

## A note on the smoke dataset

`smoke_records()` returns synthetic records. Their labels are heuristic
or synthetic-reviewed. They exist to exercise the pipeline offline and
must never be quoted as an accuracy figure or a benchmark result.
