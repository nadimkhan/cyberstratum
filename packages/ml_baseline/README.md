# evm-ml

The CyberStratum machine-learning baseline: a scikit-learn TF-IDF model over
decoded opcode n-grams, with deterministic control-flow-graph features.

This package implements Phase 4 of the design document. A graph neural network
is explicitly deferred — the baseline has to be measured first, because a GNN
cannot be justified without knowing what a linear model already achieves.

## What it does

| Module | Responsibility |
|---|---|
| `evm_ml.tokenize` | Turns a disassembled instruction stream into raw and normalised token documents, and builds n-grams. |
| `evm_ml.features` | Fits and applies the feature pipeline: two independent TF-IDF vocabularies (raw and normalised) plus numeric CFG features. |
| `evm_ml.dataset` | Loads a labelled dataset with full provenance, and splits it deterministically at project-family level. |
| `evm_ml.model` | The `ModelAdapter` interface and the scikit-learn implementation; artifact save and load. |
| `evm_ml.evaluate` | Precision/recall/F1/PR-AUC per category, false positives per 100 contracts, recall at a review budget, Brier score, breakdowns, latency. |
| `evm_ml.manifest` | The versioned model artifact manifest. |
| `evm_ml.modelcard` | Renders the model card from the manifest, so the card cannot drift from the numbers. |
| `evm_ml.train` | The training entry point. |

## Design rules this package enforces

* **Vocabulary is fitted on the training corpus only.** `FeatureBuilder.transform`
  refuses to run before `fit`, and the fitted vocabulary is persisted inside
  the model artifact so inference reuses exactly the same terms.
* **Splits are made at project-family level.** A family is assigned to a split
  by hashing its name, so it is structurally impossible for one project's
  contracts to appear on both sides of a split. The split is reproducible
  without a random seed.
* **Raw and normalised features stay separate.** They are two independent
  vocabularies, not one concatenated document, so a signal can be attributed
  to either view.
* **Multiple labels per contract.** Categories are modelled one-vs-rest, not
  as a single multiclass target.
* **ML is optional.** `load_adapter` returns `None` when no artifact exists,
  which is what keeps the scanner runnable with ML disabled.
* **Results are experimental.** Every artifact is written with
  `experimental=True` and a model card listing its limitations.

## Training

```bash
python -m evm_ml.train --dataset data/dataset.jsonl --output artifacts/model-v1
```

The dataset is JSON Lines. Each line is one contract:

```json
{"contract_id": "0xabc...", "family": "UniswapV2", "chain": "ethereum",
 "compiler": "0.8.17", "source": "sourcify", "license": "MIT",
 "label_source": "manual-review", "label_confidence": "high",
 "bytecode": "60806040...", "labels": {"reentrancy": false, "unchecked_call": true}}
```

`family` is the grouping key for splitting. Contracts from the same project
must share a family name.

## Output

```
artifacts/model-v1/
  model.joblib      fitted vectorizers + classifier + manifest
  manifest.json     versions, hashes, split, metrics, limitations
  MODEL_CARD.md     the model card
  evaluation.json   validation and test metrics
```
