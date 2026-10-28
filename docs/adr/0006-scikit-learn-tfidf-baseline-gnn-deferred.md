# ADR-0006: scikit-learn TF-IDF baseline; GNN deferred

- **Status:** Accepted
- **Date:** 2026-10-28
- **Governs:** design-document §6.2, §6.4, §13, §17 (Phase 4), §18, §23.1, §24.1, §27

## Context

The design document distinguishes two ML ambitions and is careful about their
different costs:

- §6.4 describes candidate feature families (opcode/N-gram frequencies, block
  mix, call/storage locations, branch and cycle counts, stack-depth
  consistency) and then says plainly: "The proposed GNN update is a design
  sketch, not a complete model specification."
- §6.4 then lists nine things engineering must define before a GNN exists:
  graph direction and edge types; node and edge features; graph pooling;
  labels and class definitions; loss function and class-imbalance handling;
  calibration and thresholds; model/version registry; explainability method and
  evidence mapping.
- §13.2 requires precision/recall per category, F1 and PR-AUC, false positives
  per 100 contracts, recall at an analyst review budget, calibration, slice
  performance, and inference latency — and says "Accuracy alone is
  insufficient".
- §13.3 sets an eight-step model release gate ending in shadow deployment and
  human-reviewed rollout.
- §17 Phase 4 says "GNN only if dataset size/quality justifies it".
- §23.1 lists "Graph ML (later) | PyTorch; PyTorch Geometric only if graph data
  and labels justify it" and "Treat as optional P1/P2 until data quality and
  baseline metrics are proven".
- §24.1 says "Do not make free GPU availability a product dependency. A GNN is
  not an MVP requirement."
- §21 question 5 asks: "Is the first ML deliverable a baseline classifier or is
  a GNN mandatory?"

The honest constraint is that a GNN requires a labelled dataset with graph-level
labels, and no such dataset exists yet (§21 question 4 asks whether there is
one, and what its provenance and licences are — it is unanswered).

## Decision

The ML baseline is **scikit-learn with sparse TF-IDF features over opcode
n-grams**. The GNN is **deferred**, not planned-and-scheduled.

Concretely:

- **Features.** TF-IDF over opcode n-grams (default N = 3, per §6.2), plus the
  deterministic numeric features that `evm_analysis.features.ContractFeatures`
  already produces: opcode frequencies, block/edge/branch counts, unresolved
  jump count and ratio, cycle count, call/create/storage read-write counts,
  call-then-storage-write count, stack underflow count, max stack depth, and
  code/instruction counts.
- **Vocabulary discipline** (§6.2): the TF-IDF vocabulary is fit **only on the
  training corpus**, persisted, versioned, and reused for inference. Splits are
  at contract/project/family level, never at random bytecode-fragment level, to
  prevent leakage.
- **Raw and normalised features stay separate** (§6.2): normalisation of
  `PUSHn` width, constants, addresses, and compiler metadata is a separate
  feature family, not a silent rewrite of the raw one.
- **Labelling.** Every model output is a **candidate**, never a confirmation
  (§5.2, §12): "A finding must not be called 'confirmed' solely because a
  classifier score crosses a threshold."
- **Release gate.** §13.3 applies unchanged to the TF-IDF model. No model
  becomes production-active without evaluation results, a model card, approved
  thresholds, a reproducible artifact, and a rollback path (§11.13).
- **Flag.** `ENABLE_EXPERIMENTAL_ML=false` by default
  (`apps/api/app/core/config.py`, `.env.example`). The scanner must run with ML
  disabled (§23.2). Any ML-labelled result is displayed as "experimental" until
  validated (§12).
- **Adapter.** A model adapter interface keeps scikit-learn and any future GNN
  swappable without changing API contracts (§23.2).

The GNN is deferred until all of the following are true, and then only by a new
ADR:

1. A labelled dataset exists with documented provenance and licences (§13.1).
2. The TF-IDF baseline has been evaluated on a held-out, family-level split,
   with metrics reported per §13.2.
3. The baseline's failure analysis shows a specific, named class of pattern
   that the n-gram representation provably cannot express.
4. A GPU or equivalent compute budget exists that does not depend on an
   unverified free tier (§24.1).

## Consequences

**Positive**

- The ML deliverable is achievable on CPU, on a free tier, with no GPU
  dependency — §24.1's explicit constraint.
- The TF-IDF baseline is the *comparison point* every later model must beat.
  Without it, "is the GNN better?" is unanswerable.
- Feature extraction is already deterministic and reproducible in
  `evm_analysis.features.extract_features`, so the baseline consumes
  already-verified inputs rather than inventing its own.
- §13.3's release gate is satisfiable in full, which keeps the "experimental"
  labelling honest rather than rhetorical.

**Negative / accepted cost**

- A TF-IDF n-gram model cannot represent graph structure. It will miss
  reentrancy patterns that depend on CFG shape. This is a real capability gap
  and the reason the deferral must be revisited once labels exist — not a
  reason to hide the gap.
- Deferring the GNN means the §6.4 "design sketch" stays a sketch. The nine
  definitions §6.4 demands are not written down, and no GNN code will exist
  during the MVP. That is the intent, but it should be stated plainly rather
  than implied.
- The scikit-learn extra (`pyproject.toml` `[project.optional-dependencies] ml`)
  is not installed in the current virtual environment, so the baseline is
  specified but not yet executed.

> **Implementation update (2026-10-28):** the baseline is now **built** as an
> installable package at `packages/ml_baseline/evm_ml/` — tokenizer, dataset
> with family-level splits, feature assembly, `SklearnTfidfAdapter`,
> evaluation, manifest, model card, and report. `scikit-learn` 1.9.1 and the
> `evm_ml` package are installed in the working virtual environment;
> `pandas` is not, so the parts of the package that would need it are not
> exercised.
>
> The package is **standalone**: the scan pipeline does not import it, and
> `ENABLE_EXPERIMENTAL_ML` still defaults to `false`. A scan therefore
> produces detector findings only, with no ML score attached. The decision
> this ADR records is unchanged — the GNN remains deferred — but the phrase
> "specified but not yet executed" above now describes the *integration* step
> rather than the baseline itself.

**Explicitly not in scope**

- Training runs, dataset curation, and the model registry UI. §13's process
  applies when the baseline is actually built.
- Any claim that the baseline "detects vulnerabilities". It produces
  prioritisation scores over a labelled corpus.

## Design-document sections resolved

- **§6.2** — TF-IDF convention and vocabulary discipline are fixed here.
- **§6.4** — the GNN is explicitly deferred; the nine-item definition list
  becomes a future prerequisite, not MVP work.
- **§13.1–§13.3** — retained in full and applied to the TF-IDF baseline.
- **§17 Phase 4** — the phase deliverable is the TF-IDF baseline and its
  evaluation report; the GNN is removed from the phase's scope.
- **§18 item 14** — ML results stay labelled experimental until the release
  gate is met.
- **§23.1** — "Baseline ML" is scikit-learn + sparse TF-IDF; "Graph ML" is
  deferred.
- **§24.1** — CPU-only local training confirmed; no free-GPU dependency.
- **§27** — item 10 ("ML baseline, dataset provenance, and whether graph ML is
  deferred") is answered.
- **§21** — questions 4 and 5 are answered: baseline classifier first; GNN not
  mandatory.
