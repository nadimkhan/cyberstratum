# ADR-0012: Merge Watchdog into CyberStratum

* **Status:** Proposed — awaiting sign-off
* **Date:** 2026-10-28
* **Supersedes:** nothing

## Context

Two projects exist that are the same product at two different levels of depth.

| | Watchdog (`E:/projects/watchdog`) | CyberStratum (`E:/projects/cyberstratum`) |
|---|---|---|
| Input | Verified **source** code from Blockscout | **Runtime bytecode** (or pasted bytes) |
| Engine | Slither (source-level detectors) | Custom fork-aware EVM engine (disassembler, CFG, resolver) |
| Reach | 59-chain discovery feed, continuous polling | On-demand, single contract at a time |
| Output | Findings with severity, per-contract risk vectors | Findings with severity **and** confidence, plus reproducible artifacts |
| User surface | Google OAuth, `/contracts` `/findings` `/chains` `/analyze` | API-key workspaces, `/scans` `/findings` `/reproducibility` |
| State | PostgreSQL | PostgreSQL + Redis/RQ |
| Size | ~2,400 Python LOC, ~1,350 TS LOC, 11 commits | ~10,600 Python LOC, ~4,200 TS LOC, 17 commits |

They fail in opposite directions, which is the argument for keeping both engines in one
product rather than choosing one:

- **Slither needs source.** It cannot see a contract whose source is unverified,
  outdated, or different from what was deployed. It sees reentrancy across function
  calls, precise `file:line` locations, and inheritance/composition issues.
- **The EVM engine needs no source.** It analyses the bytes that are actually on
  chain: compiler quirks, proxy and `delegatecall` runtime structure, unreachable
  code, fork-specific opcodes, and Solidity metadata. It works on unverified
  contracts, which is the majority of deployed code.
- **Comparing the two views is itself a finding.** A contract whose source analyses
  clean but whose runtime bytecode contains a different structure than the source
  implies is worth a human's attention. No single tool does this.

Keeping them as separate projects duplicates the contract/finding model, the
frontend, the auth layer and the database, and makes cross-checking impossible.

## Decision

**CyberStratum is the canonical project. Watchdog is absorbed into it**, keeping
both engines and one shared data model. The Watchdog repository stays on disk
unchanged and remains the source of truth for the code being ported until the
merge is complete and verified.

The merged product has two engines behind one pipeline:

```
Blockscout discovery (59 chains)
        │
        ▼
   contracts ──────────────────────────────┐
        │                                   │
        ▼                                   ▼
 [audit] source-level              [analysis] bytecode-level
 Slither on verified source        CyberStratum EVM engine
        │                                   │
        └──────────► unified findings ◄──────┘
                     (discriminator: source)
```

`findings.source` distinguishes `slither`, `rule` and `ml`, so a contract's risk
is the union of both views while each finding keeps its own provenance, severity
and confidence.

## Consequences

**Good**

- One product, one contract model, one findings table, one dashboard.
- Cross-engine checks become possible (source/runtime divergence, engine
  agreement/disagreement per finding).
- The strongest asset of each project survives: Watchdog's chain registry,
  Blockscout client and Slither runner; CyberStratum's EVM engine, artifact
  pipeline, launcher and ADR discipline.

**Bad**

- Two codebases to maintain in one repo, with two overlapping frontends to merge.
- Watchdog's schema (`contracts`, `slither_findings`, `ml_assessments`, `run_log`)
  must be reconciled with CyberStratum's (`scans`, `scan_jobs`, `findings`,
  `features`, `instructions`, `basic_blocks`, `cfg_edges`, ...).
- Slither is **AGPL-3.0**. See ADR-0013.

**Neutral**

- Campaign tracking stays out of scope (ADR-0007).
- The GNN stays deferred (ADR-0006); the TF-IDF baseline becomes the ML engine
  and is wired into the scan pipeline.

## Alternatives considered

| Alternative | Why rejected |
|---|---|
| Keep two projects, add an HTTP bridge | Duplicates the contract model and makes the cross-engine check a distributed transaction. |
| Watchdog becomes canonical | It lacks the reproducible-artifact pipeline, the cross-validated EVM engine, and the tested one-command launcher. |
| Replace Slither with the EVM engine | Gives up source-level detectors and `file:line` locations for no gain. |
| Replace the EVM engine with Slither | Gives up unverified-contract coverage, fork awareness, and reproducibility. |
