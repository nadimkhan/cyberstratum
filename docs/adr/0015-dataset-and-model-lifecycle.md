# ADR-0015 — Dataset ingestion and model promotion discipline

- Status: Accepted
- Date: 2026-10-29
- Related: ADR-0006 (scikit-learn TF-IDF baseline, GNN deferred), ADR-0014 (engine portfolio)

## Context

The platform needs real vulnerability, exploit, bug and hack data to train and
evaluate its ML baseline. Two failure modes are fatal to a commercial product:

1. **Poisoning.** Training on unreviewed, machine-generated findings teaches the
   model to agree with our own false positives.
2. **Leakage.** If near-duplicate exploits land in both train and test, the
   reported accuracy is fiction and a customer will find out on their data.

There is also a licensing dimension: datasets carry their own licences, and
some carry conditions that do not permit commercial redistribution.

## Decision

### Dataset sources and their licences (measured)

| Source | Licence | Use |
| --- | --- | --- |
| SmartBugs Curated | Apache-2.0 | Training + evaluation. Pre-labelled, pre-triaged, has SWC IDs and CWE IDs, `vulnerabilities.json` with a stable schema. **The primary evaluation corpus.** |
| DeFiHackLabs | Apache-2.0 | Real-world exploit PoCs. Used as a *target* corpus for recall measurement and for regression fixtures, not as a naively-labelled training set. |
| SWC Registry | MIT | Weakness taxonomy and canonical IDs. Used as the join key, not as a training set. |
| Web3Bugs | per-repo (mixed) | Ingestion allowed only after a per-repo licence and label-quality audit. Findings are `true`/`false`/`not-yet-determined` — undetermined rows are **not** usable as negative labels without review. |
| ConsenSys solidity-advisories | — | Advisory text as a severity prior and description source. Not a labelled training set. |
| Own platform findings | n/a | The long-term moat. Unreviewed findings are quarantined, never auto-promoted. |

### Ingestion pipeline

Every dataset enters through one ingestion pipeline that produces an
**immutable dataset manifest**:

1. **Fetch and pin** — record the upstream repo, commit SHA, and retrieval
   timestamp. Pin the commit, never a branch.
2. **Licence record** — store the licence text and SPDX identifier per source
   file. A file with an incompatible licence is rejected, not silently skipped.
3. **Parse into a canonical record** — one schema for all sources:
   `id`, `source_dataset`, `source_ref`, `language`, `compiler_version`,
   `code`, `swc_id`, `cwe_id`, `label`, `label_provenance`, `severity`,
   `family_key`.
4. **Deduplicate** — exact hash, then normalised-code hash, then near-duplicate
   clustering within a family.
5. **Family grouping** — every record gets a `family_key` grouping exploits that
   are variants of the same root cause (same bug class in the same protocol
   family, forks of one another, etc.). **Family grouping happens before
   splitting.**
6. **Split** — split **by family**, never by record. A variant of a training
   example can never appear in the test set. The split is seeded and recorded
   in the manifest so it is reproducible.
7. **Immutability** — the manifest is content-addressed. Training runs reference
   a manifest SHA; the manifest is never edited in place.

### Label provenance

Three tiers, and a label is only usable in training at the tier it declares:

- `reviewed` — human-confirmed. Usable for training and evaluation.
- `heuristic` — transparent rule-derived (e.g. "contains a `delegatecall` to a
  user-controlled address"). Usable for training only with the rule recorded,
  and **never** as evaluation ground truth. The current smoke dataset is in
  this tier and is explicitly not a benchmark.
- `unreviewed` — model- or tool-generated and not yet checked. **Quarantined.**
  Not usable for training, not usable for evaluation.

### Model update cadence — the request was "updated regularly"

Daily retraining on unreviewed findings is rejected. It would make the model
chase its own noise, and a model that changes every day cannot be
referenced in a reproducible report or defended to a customer.

Instead:

- **Daily:** ingest new data into the quarantine tier. Produce a *candidate*
  dataset and a *candidate* model. Do not promote.
- **Scheduled retrain:** a fixed cadence (weekly) retrains the baseline from
  the current reviewed corpus and produces a candidate model with a manifest.
- **Event-triggered retrain:** retrain when a reviewed-label batch lands that
  is large enough to matter (a reviewed threshold, e.g. 50 new reviewed
  records or a full new family set).
- **Promotion gate:** a candidate model becomes the served model only when it
  beats the current model on the **held-out family-split evaluation set** on
  precision/recall/F1 per class, and does not regress on any previously
  passing class, and the evaluation is reproducible from the manifest.

Every model carries a **model manifest**: dataset manifest SHA, feature
schema version, hyperparameters, seed, training metrics, evaluation metrics,
and the code revision. A finding produced by the model records the model
version, so a report can always state which model produced which verdict.

### Vocabulary discipline (carried forward from ADR-0006)

- TF-IDF vocabulary is fitted **on training data only**.
- Normalisation happens before splitting so that the same normalisation
  function is applied identically at inference time.
- The served model's vocabulary and IDF are persisted as part of the model
  manifest.

## Consequences

- Reported model accuracy is meaningful and reproducible, because it is
  computed on a family-split held-out set that leaked nothing.
- "Update the model regularly" is satisfied by a controlled pipeline with
  explicit promotion, not by a nightly retrain that nobody can defend.
- We build our own labelled corpus over time. Every customer-visible
  high-confidence finding that a customer confirms becomes a reviewed label.
  That corpus is ours, licensed cleanly, and is the actual differentiator.
- The toolchain must be able to pin and diff dataset manifests, which means
  the ingestion pipeline is versioned alongside the code.

## Alternatives considered

- **Retrain daily on all new findings.** Rejected: self-poisoning, and
  unreproducible reports.
- **Train on DeFiHackLabs PoCs directly.** Rejected: PoCs are exploits, not
  labelled vulnerability samples; using them as training data teaches the model
  to find exploits rather than to judge vulnerability, and it has no negative
  examples.
- **Use SmartBugs as-is without family grouping.** Rejected: SmartBugs contains
  many records per project and per bug class; without family grouping the
  split leaks and the accuracy number is meaningless.
