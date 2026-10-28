# Project CyberStratum
## Product Requirements, Technical Architecture, Development Plan & UI/UX Specification

**Document status:** Draft for engineering kickoff  
**Version:** 1.0  
**Date:** 28 October 2026  
**Audience:** Product owner, smart-contract security engineers, ML engineers, backend engineers, frontend engineers, DevOps, QA, and prospective technical reviewers.

---

## Document status — correction record (2026-10-28)

This document was written before the implementation stack was settled and
originally specified **two mutually incompatible backends**: a Python /
FastAPI / SQLAlchemy / Alembic backend (§23.1, §23.4) and a Node.js /
TypeScript / Prisma / BullMQ backend (§8.1, §8.2, §23.3, §25.2, §27,
Appendix B). That contradiction has now been resolved in writing.

**Resolved stack:** a **Python backend (FastAPI + Pydantic + SQLAlchemy 2 +
Alembic + RQ on Redis)** with a **Next.js (App Router, TypeScript) frontend**
that is a pure HTTP client of the API. The Node/TypeScript/Prisma/BullMQ
material in this document is stale and has been corrected in place. **Prisma is
not used anywhere in this project. BullMQ is not used anywhere in this
project.** No Docker: local infrastructure is native PostgreSQL 17.11 and
Redis 8.10.3.

**Governing decisions.** The authoritative log of decisions is
[`docs/adr/`](docs/adr/README.md). Where an ADR and this document disagree,
the ADR governs. Each corrected section below carries a dated "Correction
note" naming the ADR that governs it.

| ADR | Decision |
|---|---|
| [0001](docs/adr/0001-python-backend-over-node-prisma.md) | Python backend over Node/TypeScript + Prisma; RQ over BullMQ |
| [0002](docs/adr/0002-nextjs-frontend.md) | Next.js frontend, a pure HTTP client of the Python API |
| [0003](docs/adr/0003-no-docker-native-postgres-and-redis.md) | No Docker; native local PostgreSQL 17.11 and Redis 8.10.3 |
| [0004](docs/adr/0004-custom-vendored-opcode-table.md) | Custom vendored fork-accurate opcode table from `ethereum/execution-specs` v2.20.0; `pyevmasm` rejected |
| [0005](docs/adr/0005-evmole-as-cross-validation-oracle.md) | `evmole` 0.9.4 retained as an independent cross-validation oracle only |
| [0006](docs/adr/0006-scikit-learn-tfidf-baseline-gnn-deferred.md) | scikit-learn TF-IDF baseline; the GNN is deferred, not scheduled |
| [0007](docs/adr/0007-campaign-tracking-out-of-mvp-scope.md) | Campaign tracking removed from MVP scope |
| [0008](docs/adr/0008-no-airdrop-bounty-or-campaign-promises.md) | No airdrop, bounty, or campaign promises or metrics |

**Other changes recorded on 2026-10-28:**

- **Campaign tracking is out of scope for the MVP.** §1, §4, §5.3, §9.2,
  §11.1, §11.17, §18, §20 and §21 are annotated accordingly. The campaign
  tables, workflow, and page are not built. See ADR-0007.
- **Airdrop, bounty-income, and campaign-reward promises have been removed
  from scope.** The product makes no such promise and carries no such metric.
  §1, §1.2, §2, §11.3, §20 and Appendix A are annotated accordingly. See
  ADR-0008.
- **The graph neural network is deferred.** §6.4, §13, §17 (Phase 4), §23.1
  and §24.1 are annotated. The MVP ML deliverable is a scikit-learn TF-IDF
  baseline. See ADR-0006.
- **The EVM disassembler is decided.** The production parser is the custom
  `packages/evm_analysis` package with a vendored, versioned, fork-accurate
  opcode table generated from pinned `ethereum/execution-specs` v2.20.0.
  `pyevmasm` was rejected as stale; `evmole` 0.9.4 is a validation oracle only.
  See ADR-0004 and ADR-0005.

**How corrections are marked.** Each edited section opens with a short block
of the form:

> **Correction note (2026-10-28):** … — governed by
> [`docs/adr/000N-….md`](docs/adr/README.md).

**Nothing else was rewritten.** No requirement was deleted. Sections outside
those listed above are unchanged.

---

## 1. Executive Summary

> **Correction note (2026-10-28):** Workstream 2 below — "Authorized ecosystem
> research" / campaign tracking — is **out of scope for the MVP** and is not
> built. The MVP is the bytecode analysis workstream only. The product makes
> **no airdrop, token-allocation, bounty-income, or campaign-reward promise**,
> and carries no such metric or telemetry. Both requirements remain recorded
> here as the original intent; neither is an MVP deliverable. — governed by
> [`docs/adr/0007-campaign-tracking-out-of-mvp-scope.md`](docs/adr/0007-campaign-tracking-out-of-mvp-scope.md)
> and
> [`docs/adr/0008-no-airdrop-bounty-or-campaign-promises.md`](docs/adr/0008-no-airdrop-bounty-or-campaign-promises.md).

CyberStratum is proposed as a Web3 security-analysis and authorized testnet research platform with two related workstreams:

1. **Bytecode security analysis:** ingest EVM bytecode and contract metadata, disassemble bytecode correctly, derive opcode and control-flow features, run static and ML-assisted detection, and produce explainable findings for human validation.
2. **Authorized ecosystem research:** manage approved testnet campaigns and wallet activity only where explicitly permitted by the relevant protocol's terms. The product must not promise airdrops, token allocations, or zero-cost participation; it records eligible activity and costs transparently.

The business proposal also describes competitive bug-bounty participation. CyberStratum should assist researchers with triage, evidence, and report preparation. It must not automatically exploit third-party live contracts, drain assets, evade anti-bot or anti-Sybil controls, impersonate users, or submit reports without researcher approval. Proof-of-concept execution must be confined to a local fork, a dedicated sandbox, or a program-authorized environment.

### 1.1 Product outcomes

> **Correction note (2026-10-28):** The campaign-tracking outcome below is
> **out of scope for the MVP** and is not built (ADR-0007). The remaining
> outcomes are the MVP. The product makes **no** airdrop, allocation,
> bounty-income, or campaign-reward promise and carries no such metric
> (ADR-0008). — governed by
> [`docs/adr/0007-campaign-tracking-out-of-mvp-scope.md`](docs/adr/0007-campaign-tracking-out-of-mvp-scope.md)
> and
> [`docs/adr/0008-no-airdrop-bounty-or-campaign-promises.md`](docs/adr/0008-no-airdrop-bounty-or-campaign-promises.md).

- Analyse verified and unverified EVM contracts using bytecode-first workflows.
- Identify candidate security issues with confidence, evidence, trace information, and limitations.
- Help a security researcher reproduce findings in a controlled environment.
- Track authorized testnet campaigns, tasks, costs, eligibility notes, and evidence without promising rewards.
- Provide an operator dashboard for scan health, queues, model performance, infrastructure costs, and audit history.
- Create a defensible data and evaluation pipeline for improving detection quality over time.

### 1.2 Non-goals for the first release

- Guaranteed vulnerability discovery or guaranteed bounty income.
- Guaranteed airdrop eligibility, allocations, token value, or liquidity.
- Mainnet transaction execution or autonomous asset movement.
- Unattended exploitation of public contracts.
- Anti-Sybil evasion, bot-detection bypass, proxy rotation to disguise identity, or violating campaign terms.
- A claim that ML replaces manual review, symbolic execution, fuzzing, or a professional audit.

---

## 2. Source Material, Assumptions, and Items Requiring Validation

> **Correction note (2026-10-28):** This section reconciles the **supplied
> business material**, not product commitments. Nothing in it is a promise
> CyberStratum makes. The MVP product makes **no** airdrop, allocation,
> bounty-income, or campaign-reward promise and carries no such metric
> (ADR-0008), and campaign tracking is out of scope (ADR-0007). The
> reconciliation and the "hypotheses, not facts" framing below are unchanged
> and remain the correct treatment of the source claims. — governed by
> [`docs/adr/0007-campaign-tracking-out-of-mvp-scope.md`](docs/adr/0007-campaign-tracking-out-of-mvp-scope.md)
> and
> [`docs/adr/0008-no-airdrop-bounty-or-campaign-promises.md`](docs/adr/0008-no-airdrop-bounty-or-campaign-promises.md).

This document is based on the supplied pitch-deck/forecast file and the supplied EVM bytecode vectorization and investor outreach text. Source claims are retained as business intent, not treated as independently verified facts.

### 2.1 Claims in the supplied material that need evidence before external use

- “95%” of public airdrop campaigns being diluted by spam.
- Billions in losses attributable specifically to unvetted pre-launch contracts.
- Successful mapping of complex cross-chain contracts and “flawless” execution under high load.
- The existence and performance of a proprietary trained model.
- The projected frequency and value of bounty awards.
- Historical TGE averages used to estimate airdrop value.
- The forecast's $985,000 revenue and 87.6% margin.
- The assertion that testnet participation has no capital or operational cost.
- Any claim that private RPC relays, proxies, or behavioral randomization bypass protocol protections.

Until evidence exists, mark these as **hypotheses**, **targets**, or **management projections**. Marketing and investor materials should distinguish actual results, backtests, and forecasts.

### 2.2 Financial model reconciliation

The supplied table totals:
- Bounty revenue: **$515,000**
- Vested airdrop value: **$470,000**
- Total projected revenue/value: **$985,000**
- Infrastructure costs: **$122,000**
- Net projected amount: **$863,000**
- Weighted net margin: approximately **87.6%**

The table's arithmetic is internally consistent at the total level. However, airdrop value is not the same as realised cash revenue until tokens are received, transferable, liquid, and sold or otherwise monetised. The financial dashboard must separate:
- cash received,
- bounty awarded but unpaid,
- tokens received and vested,
- estimated token value,
- realised token proceeds,
- operating expenses,
- forecast versus actual.

The pitch deck says funding allocation is 50% GPU, 35% RPC/proxy operations, and 15% core runway. The detailed forecast instead lists $48,000 GPU (39.3%), $32,000 node clusters (26.2%), $24,000 proxy networks (19.7%), and $18,000 contingency (14.8%). These are different allocation models and must be reconciled before fundraising. The target raise amount is not specified in the supplied deck.

### 2.3 Product assumptions to confirm during kickoff

- Initial EVM scope: Ethereum-compatible bytecode and selected EVM chains.
- Primary user: internal security researcher / protocol security team.
- Deployment: web dashboard plus background workers.
- Initial operating mode: read-only analysis and local sandbox reproduction.
- No mainnet signing or exploit execution in MVP.
- Supported input: bytecode pasted into UI, uploaded artifact, or retrieved from an approved explorer/RPC source.
- Source code, when available, is supplementary; bytecode analysis must still work without source.

---

## 3. User Roles and Permissions

### 3.1 Roles

| Role | Capabilities |
|---|---|
| Owner / Admin | Manage workspace, members, integrations, policies, retention, and system settings. |
| Security Researcher | Submit targets, launch scans, inspect findings, create reproductions, prepare reports. |
| Reviewer | Review evidence, validate or reject findings, approve report export. |
| ML Engineer | Manage datasets, model versions, evaluation runs, thresholds, and drift metrics. |
| Operator / DevOps | Monitor queues, workers, infrastructure, logs, and service health; no automatic access to secrets. |
| Read-only Viewer | View approved scans, findings, reports, and dashboard metrics. |

### 3.2 Permission principles

- Enforce role-based access control (RBAC) server-side on every API.
- Use workspace-level tenant isolation.
- Require explicit approval before exporting a disclosure report or running a sandbox reproduction.
- Keep signing keys out of the application database. MVP should not require private keys.
- Log privileged actions and configuration changes.

---

## 4. Functional Scope and Priorities

### P0 — MVP (must ship)

1. Authentication, workspace, and role management.
2. Contract target intake by chain, address, bytecode, and optional source/ABI.
3. Bytecode validation and EVM-aware disassembly.
4. Correct handling of `PUSH1`–`PUSH32` immediate data so data bytes are not misread as opcodes.
5. Basic-block and control-flow graph (CFG) extraction with unresolved-jump tracking.
6. Opcode frequency and N-gram feature generation.
7. Baseline rules and ML inference interface; model can initially be a placeholder behind a clearly labelled experimental status.
8. Findings list and detail view with severity, confidence, evidence, trace, and false-positive feedback.
9. Local/sandbox reproduction job with strict resource and network limits.
10. Scan history, reports, audit log, job status, and health monitoring.
11. Dataset versioning and a reproducible evaluation harness.
12. Documentation, tests, and developer setup.

### P1 — After MVP validation

> **Correction note (2026-10-28):** The "campaign tracker" item below is
> **out of scope**, not merely deferred to P1. It would need its own ADR
> before it is reconsidered. The remaining P1 items are unchanged. — governed by
> [`docs/adr/0007-campaign-tracking-out-of-mvp-scope.md`](docs/adr/0007-campaign-tracking-out-of-mvp-scope.md).

- Symbolic execution integration.
- Differential bytecode comparison and proxy/implementation resolution.
- Call graph and cross-contract relationship view.
- Model registry, calibration, drift monitoring, and analyst feedback loop.
- Approved testnet campaign tracker with terms/eligibility notes and transparent cost accounting. — **Out of scope (ADR-0007).**
- Scheduled scans for explicitly authorized targets.
- Report templates for internal triage and responsible disclosure.

### P2 — Later / only after policy and product review

- Multi-chain adapters beyond the first EVM networks.
- Team analytics and customer workspaces.
- Optional protocol-authorized testnet task automation, with documented campaign permission, rate limits, no identity concealment, and human review. — **Out of scope (ADR-0007).**
- Enterprise SSO, advanced retention controls, and private deployment.

---

## 5. Core Workflows

### 5.1 Bytecode scan workflow

1. User creates a target with chain/network, contract address (if known), and bytecode source.
2. API validates input size, chain identifier, address format, bytecode hex, and permissions.
3. Intake service stores the original artifact and computes a cryptographic hash.
4. Disassembler parses bytecode using the active EVM fork/opcode table and handles immediate data.
5. Parser identifies candidate basic blocks, valid `JUMPDEST` locations, static jump targets where resolvable, and unresolved dynamic jumps.
6. Feature service generates opcode counts, opcode 3-grams, stack/control-flow metadata, call/storage operation features, and graph features.
7. Rule engine runs deterministic checks; optional ML model returns calibrated scores and candidate labels.
8. Findings are deduplicated and mapped to evidence ranges / basic blocks.
9. Scan is marked complete, partial, or failed with reason and tool/model versions.
10. Researcher reviews evidence, marks true/false positive/needs-review, and may launch a sandbox-only reproduction.
11. Reviewer approves a report export.

### 5.2 Finding review workflow

`New → Triage → Confirmed / False Positive / Needs More Evidence → Report Draft → Reviewer Approved → Exported`

A finding must not be called “confirmed” solely because a classifier score crosses a threshold. The UI should explain that ML scores are prioritisation signals, not proof.

### 5.3 Authorized campaign workflow

> **Correction note (2026-10-28):** **Out of scope for the MVP.** This
> workflow is not implemented and no campaign tables, API routes, or UI pages
> exist for it. It is retained here as the original intent, with the caveat
> that step 7's "reward estimates" and the associated activity/reward ledger
> are exactly the kind of campaign-income tracking the MVP deliberately
> excludes. It would need its own ADR before being reconsidered. — governed by
> [`docs/adr/0007-campaign-tracking-out-of-mvp-scope.md`](docs/adr/0007-campaign-tracking-out-of-mvp-scope.md)
> and
> [`docs/adr/0008-no-airdrop-bounty-or-campaign-promises.md`](docs/adr/0008-no-airdrop-bounty-or-campaign-promises.md).

1. Admin/researcher creates a campaign record and links official program terms.
2. Researcher records allowed actions, prohibited actions, rate limits, and eligibility requirements.
3. Tasks are created from permitted actions or entered manually.
4. Activity is logged with wallet label (not private key), testnet, timestamp, transaction hash, fees, and evidence.
5. Eligibility and reward are recorded as unknown / pending / confirmed / rejected.
6. No automated wallet action runs unless explicitly permitted and approved.
7. Reward estimates are kept separate from confirmed rewards and realised value.

---

## 6. Technical Design: EVM Bytecode Vectorization

### 6.1 Input model

> **Correction note (2026-10-28):** The fork-aware disassembly requirement
> below is implemented by the **custom `packages/evm_analysis` package** with
> a vendored, versioned, fork-accurate opcode table generated from pinned
> `ethereum/execution-specs` v2.20.0. `pyevmasm` was rejected as stale; `evmole`
> 0.9.4 is a cross-validation oracle only, not the production parser. The
> behavioural requirements below are unchanged. — governed by
> [`docs/adr/0004-custom-vendored-opcode-table.md`](docs/adr/0004-custom-vendored-opcode-table.md)
> and
> [`docs/adr/0005-evmole-as-cross-validation-oracle.md`](docs/adr/0005-evmole-as-cross-validation-oracle.md).

A bytecode artifact is a byte sequence `B = [b0, b1, ..., bn]`. The parser maps valid instruction positions to opcode instructions. It must distinguish opcode bytes from immediate data bytes.

**Critical implementation detail:** `PUSH1` through `PUSH32` consume the following 1–32 bytes as immediate data. Those bytes must not be decoded as instructions. Truncated PUSH instructions must be flagged as malformed/truncated input and handled deterministically.

Inputs may be:
- runtime bytecode,
- creation/init bytecode,
- deployed code retrieved from an RPC or explorer,
- implementation bytecode for a proxy,
- bytecode uploaded by the user.

Record the bytecode type and provenance. Runtime and init code must not be mixed silently.

### 6.2 Opcode tokenization and N-grams

- Tokenize decoded instructions, not raw hex bytes.
- Preserve opcode name and byte offset.
- Generate N-grams with configurable N; MVP default is 3.
- Consider normalisation options for `PUSHn` width, constants, addresses, and compiler metadata. Keep raw and normalised features separate.
- Treat Solidity metadata appended to bytecode carefully; do not remove it unless detection is reliable and the original artifact remains available.
- TF-IDF vocabulary must be fit only on the training corpus, persisted, versioned, and reused for inference.
- Prevent train/test leakage by splitting at contract/project/family level, not random bytecode fragments.

For term `t` and contract document `d`:
`TF(t,d) = f(t,d) / sum_t' f(t',d)`

`IDF(t,D) = log((1 + |D|)/(1 + df(t,D))) + 1`

`V(d) = [TF(t1,d) × IDF(t1,D), ..., TF(tx,d) × IDF(tx,D)]`

For production implementation, specify the exact TF-IDF convention and library version in the model artifact manifest. Sparse vectors should be used when vocabulary is large.

### 6.3 Basic blocks and CFG

A block boundary can occur at:
- control-flow terminators such as `JUMP`, `JUMPI`, `STOP`, `RETURN`, `REVERT`, `INVALID`, and `SELFDESTRUCT` where applicable to the target EVM version;
- instruction following a conditional/unconditional branch;
- valid `JUMPDEST` locations;
- other boundaries required by the chosen CFG algorithm.

A CFG is generally **not a DAG**. Smart contracts can contain loops and cyclic edges. Model it as a directed graph `G=(V,E)`; do not impose acyclicity unless a downstream algorithm explicitly builds a separate acyclic representation. `JUMPDEST` is a candidate destination, but dynamic stack values can make targets unresolved. Track edge confidence: statically resolved, inferred, or unknown.

Store each instruction's byte offset, opcode, immediate bytes, stack effect where known, and containing block.

### 6.4 Graph and ML features

> **Correction note (2026-10-28):** The GNN sketch below is **deferred, not
> scheduled**. The MVP ML deliverable is a **scikit-learn TF-IDF baseline** over
> opcode n-grams plus the deterministic numeric features listed here. The nine
> items engineering must define are still undefined, and no labelled dataset
> is known to exist — both are reopening conditions in the ADR. The feature
> families listed below are implemented in the deterministic extractor and are
> what the baseline model consumes. — governed by
> [`docs/adr/0006-scikit-learn-tfidf-baseline-gnn-deferred.md`](docs/adr/0006-scikit-learn-tfidf-baseline-gnn-deferred.md).

Candidate feature families:
- opcode and N-gram frequencies;
- block size and instruction mix;
- `CALL`, `STATICCALL`, `DELEGATECALL`, `CREATE`, and `CREATE2` locations;
- storage read/write locations (`SLOAD`, `SSTORE`);
- branch count, unresolved jumps, graph cycles, call-to-storage ordering;
- stack-depth and stack-effect consistency when statically derivable;
- call-context and state-write patterns where data-flow analysis supports them.

The proposed GNN update is a design sketch, not a complete model specification. Engineering must define:
- graph direction and edge types;
- node features and edge features;
- graph pooling / contract-level readout;
- labels and class definitions;
- loss function and class-imbalance handling;
- calibration and thresholds;
- model/version registry;
- explainability method and evidence mapping.

### 6.5 Reentrancy detection must be multi-signal

A `CALL` appearing before an `SSTORE` is a heuristic only. It is not proof of reentrancy. A robust candidate detector should consider:
- whether an external call can transfer control to untrusted code;
- whether the same execution path can re-enter a sensitive function;
- whether state invariants are temporarily violated;
- whether a relevant state write occurs after the external interaction;
- call type, value, guards, locks, and checks-effects-interactions patterns;
- feasible path constraints and contract-specific context.

MVP output should use wording such as **“Potential reentrancy pattern — manual validation required”**. Where feasible, pair static/ML signals with symbolic execution or a local-fork test. Map detections to bytecode offsets and blocks.

### 6.6 Findings output contract

Each finding should include:
- detector ID and version;
- category / weakness mapping (e.g. reentrancy candidate);
- severity and confidence as separate fields;
- affected bytecode offsets and basic-block IDs;
- evidence summary and limitations;
- supporting features/rules;
- reproduction status and environment;
- analyst status and comments;
- false-positive feedback;
- timestamp and scan/model version.

---

## 7. Security, Sandbox, and Responsible Research Requirements

### 7.1 Safe execution model

- Static analysis is the default and must not execute target code on a public network.
- Dynamic execution occurs only in an isolated local EVM, controlled fork, or explicitly authorised environment.
- Sandbox has no outbound network by default, strict CPU/memory/time limits, ephemeral filesystem, and no host secrets.
- Use disposable chain state and deterministic test fixtures.
- Never execute generated proof-of-concept transactions against live third-party contracts by default.
- PoC generation produces test code for review; execution requires a human approval gate.
- No automatic transfer of assets, signing of mainnet transactions, or use of private keys in MVP.

### 7.2 Campaign and wallet compliance

> **Correction note (2026-10-28):** **Campaign tooling is out of scope for
> the MVP** and is not built, so the requirements below describe a future
> capability that would need its own ADR. The substantive point stands and is
> a hard constraint on this product: CyberStratum must not conceal
> coordinated identities, evade a protocol's eligibility controls, or use
> behavioural randomisation, residential proxies, or anti-bot bypass. This
> behaviour is **not implemented anywhere** in the codebase. — governed by
> [`docs/adr/0007-campaign-tracking-out-of-mvp-scope.md`](docs/adr/0007-campaign-tracking-out-of-mvp-scope.md)
> and
> [`docs/adr/0008-no-airdrop-bounty-or-campaign-promises.md`](docs/adr/0008-no-airdrop-bounty-or-campaign-promises.md).

The supplied pitch mentions behavioural randomisation, anti-Sybil controls, residential proxies, and bypassing anti-bot filters. These are not MVP requirements. The product must not conceal coordinated identities or evade a protocol's eligibility controls. Campaign tooling must:
- link the official terms;
- record permitted automation and rate limits;
- honour robots/API usage restrictions where applicable;
- identify the operator honestly;
- support opt-out / stop controls;
- enforce per-campaign budgets and transaction limits;
- log all actions;
- disable automation when terms are unclear or disallow it.

### 7.3 Application security

- OWASP-aligned secure coding, CSRF protection where applicable, input validation, rate limits, and secure headers.
- Password hashing via a modern password-hashing algorithm or a trusted OIDC provider.
- Secrets managed through environment/secret manager, never committed.
- Encrypt sensitive data in transit and at rest.
- Signed, expiring URLs for private artifact downloads.
- Tenant-scoped database access and tests for cross-tenant access.
- Dependency scanning, SBOM generation, and pinned production dependencies.
- Audit logs append-only from the application's perspective.
- Backups and restore drills.

---

## 8. Recommended Architecture

### 8.1 Logical architecture

> **Correction note (2026-10-28):** The API layer was specified as
> "Node.js + TypeScript" here, which contradicted §23.1, §23.4, and
> Appendix B.2 (Python + FastAPI + SQLAlchemy + Alembic). Corrected to the
> resolved stack: a Python FastAPI API with a Next.js web client. The
> **Node.js / TypeScript / Prisma / BullMQ** backend described elsewhere in
> this document is **not** used. — governed by
> [`docs/adr/0001-python-backend-over-node-prisma.md`](docs/adr/0001-python-backend-over-node-prisma.md)
> and
> [`docs/adr/0002-nextjs-frontend.md`](docs/adr/0002-nextjs-frontend.md).

```text
Web UI (Next.js App Router, TypeScript)   <- HTTP client of the Python API
   |
   v
API / Auth / RBAC (Python + FastAPI + Pydantic)
   |-----------------------> PostgreSQL (metadata, jobs, findings, audit)
   |-----------------------> Object Storage (bytecode, reports, datasets)
   |-----------------------> Redis Queue (RQ)
                                  |
                                  v
                         Worker Orchestrator (Python)
                         |        |         |
                         v        v         v
                    Disassembler Rules   ML Inference
                         |        |         |
                         +--------+---------+
                                  |
                                  v
                       Result Normalisation
                                  |
                                  v
                        Findings / Reports API

Optional isolated sandbox worker:
job broker → ephemeral sandbox → result artifact → review gate
```

### 8.2 Suggested stack

> **Correction note (2026-10-28):** The queue, deployment, and parser
> bullets below were stale. Corrected to the resolved stack: **RQ** (not
> BullMQ) on Redis; **native PostgreSQL 17.11 and Redis 8.10.3** for local
> development with **no Docker**; and a **custom vendored fork-accurate
> opcode table** as the production EVM disassembler, with `evmole` retained
> only as an independent cross-validation oracle. The Node.js / TypeScript /
> Prisma backend is not used. — governed by
> [`docs/adr/0001-python-backend-over-node-prisma.md`](docs/adr/0001-python-backend-over-node-prisma.md),
> [`docs/adr/0003-no-docker-native-postgres-and-redis.md`](docs/adr/0003-no-docker-native-postgres-and-redis.md),
> [`docs/adr/0004-custom-vendored-opcode-table.md`](docs/adr/0004-custom-vendored-opcode-table.md),
> and
> [`docs/adr/0005-evmole-as-cross-validation-oracle.md`](docs/adr/0005-evmole-as-cross-validation-oracle.md).

- Frontend: Next.js App Router, TypeScript, Tailwind CSS, shadcn/ui. The web
  app is a pure HTTP client of the Python API and holds no backend logic.
- Backend API: **Python + FastAPI + Pydantic**, with versioned OpenAPI
  schemas. Keep API request handling separate from long-running scan and ML
  workers.
- Database: **PostgreSQL 17.11** with **SQLAlchemy 2** ORM and **Alembic**
  migrations. **Prisma is not used.**
- Queue/cache: **Redis 8.10.3 with RQ**. **BullMQ is not used.**
- Object storage: S3-compatible storage (self-hosted or managed), behind a
  storage adapter so local disk and a bucket share one interface.
- Analysis worker: Python. The EVM disassembler is the **custom
  `packages/evm_analysis` package** with a vendored, versioned, fork-accurate
  opcode table generated from pinned `ethereum/execution-specs` v2.20.0.
  `pyevmasm` was rejected as stale (it lacks `PUSH0` and other modern
  opcodes). `evmole` 0.9.4 is retained **only** as an independent
  cross-validation oracle, never in the production scan path.
- ML: **scikit-learn TF-IDF baseline**. PyTorch / PyTorch Geometric is
  **deferred**, not scheduled — see the correction note in §6.4 and
  §13 for the conditions that would reopen it.
- Sandbox: isolated EVM runner with no outbound network and strict resource
  limits, disabled by default and gated behind explicit human approval.
- Observability: structured logs (structlog JSON), metrics, traces, error
  reporting.
- Deployment: **native local PostgreSQL and Redis — no Docker, no
  docker-compose.yml.** Staged deployment for production is a later concern.

Use a modular application for MVP with a Python FastAPI API and separate
worker processes. Keep the API and worker code in one repository initially,
but run them as separate processes. Split into independent services only when
queue throughput, security boundaries, or scaling require it.

### 8.3 Environments

- `local`: synthetic/test fixtures, no production secrets.
- `test`: CI integration tests and ephemeral database.
- `staging`: production-like, no unrestricted mainnet transaction execution.
- `production`: restricted access, backups, alerting, secrets manager, approved target policy.

---

## 9. Database Schema (MVP)

Use UUID primary keys, UTC timestamps, indexes for query paths, and explicit tenant/workspace IDs.

### 9.1 Core tables

**users**
- `id`, `email`, `display_name`, `auth_provider_id`, `created_at`, `last_login_at`, `status`

**workspaces**
- `id`, `name`, `slug`, `created_by`, `created_at`

**workspace_members**
- `workspace_id`, `user_id`, `role`, `created_at`; unique `(workspace_id,user_id)`

**chains**
- `id`, `name`, `chain_id`, `environment` (`mainnet`, `testnet`, `local`), `rpc_config_ref`, `enabled`

**contract_targets**
- `id`, `workspace_id`, `chain_id`, `address_nullable`, `label`, `bytecode_type`, `bytecode_hash`, `bytecode_object_key`, `source_uri_nullable`, `abi_object_key_nullable`, `provenance`, `authorization_status`, `created_by`, `created_at`

**scans**
- `id`, `workspace_id`, `target_id`, `status`, `requested_by`, `queued_at`, `started_at`, `completed_at`, `parser_version`, `ruleset_version`, `model_version_nullable`, `error_code_nullable`, `error_message_redacted_nullable`

**scan_jobs**
- `id`, `scan_id`, `job_type`, `queue_name`, `status`, `attempt`, `started_at`, `finished_at`, `duration_ms`, `resource_usage_json`

**instructions**
- `id`, `scan_id`, `byte_offset`, `opcode_byte`, `opcode_name`, `immediate_hex_nullable`, `instruction_size`, `block_id_nullable`, `stack_in_nullable`, `stack_out_nullable`

**basic_blocks**
- `id`, `scan_id`, `start_offset`, `end_offset`, `terminator_opcode_nullable`, `is_entry`, `is_exit`, `metadata_json`

**cfg_edges**
- `id`, `scan_id`, `from_block_id`, `to_block_id_nullable`, `edge_type`, `resolution` (`resolved`, `inferred`, `unresolved`), `evidence_json`

**features**
- `id`, `scan_id`, `feature_schema_version`, `feature_type`, `feature_object_key_nullable`, `feature_json_nullable`, `created_at`

**findings**
- `id`, `workspace_id`, `scan_id`, `detector_id`, `detector_version`, `category`, `title`, `description`, `severity`, `confidence`, `status`, `evidence_json`, `limitations`, `created_at`, `updated_at`

**finding_feedback**
- `id`, `finding_id`, `reviewer_id`, `decision`, `comment`, `created_at`

**reproduction_jobs**
- `id`, `finding_id`, `environment_type`, `approval_user_id`, `status`, `sandbox_image_digest`, `started_at`, `completed_at`, `result_object_key_nullable`

**reports**
- `id`, `workspace_id`, `scan_id`, `report_type`, `status`, `created_by`, `reviewed_by_nullable`, `object_key`, `created_at`, `approved_at_nullable`

**model_versions**
- `id`, `name`, `version`, `artifact_uri`, `training_dataset_version`, `feature_schema_version`, `metrics_json`, `thresholds_json`, `status`, `created_at`

**datasets**
- `id`, `name`, `version`, `provenance`, `labeling_policy`, `split_manifest_uri`, `created_by`, `created_at`

**audit_events**
- `id`, `workspace_id`, `actor_user_id_nullable`, `action`, `resource_type`, `resource_id`, `ip_hash_nullable`, `metadata_redacted_json`, `created_at`

### 9.2 Optional P1 tables

> **Correction note (2026-10-28):** **Out of scope for the MVP.** None of these
> tables exist in the implemented schema. The implemented ORM defines 14 core
> tables (identity, workspaces, chains, targets, scans, jobs, artifacts,
> instructions, blocks, edges, features, findings, audit events) and no campaign
> tables. The `reward_records` table in particular would introduce
> token-value and estimated-value fields, which the MVP does not carry. — governed by
> [`docs/adr/0007-campaign-tracking-out-of-mvp-scope.md`](docs/adr/0007-campaign-tracking-out-of-mvp-scope.md)
> and
> [`docs/adr/0008-no-airdrop-bounty-or-campaign-promises.md`](docs/adr/0008-no-airdrop-bounty-or-campaign-promises.md).

**campaigns**: official URL, network, terms snapshot, permission status, budget cap, allowed automation, rate limits, status.  
**campaign_tasks**: campaign ID, task description, required evidence, status, operator approval.  
**wallet_labels**: workspace ID, public address, label, network, owner/consent notes; never store private keys.  
**campaign_activity**: task ID, wallet label ID, tx hash, timestamp, cost, evidence, outcome.  
**reward_records**: campaign ID, status, token symbol, token amount, vesting status, estimated value, realised value, valuation source/time.

---

## 10. API Design (Illustrative REST Contract)

Prefix: `/api/v1`. All routes require authentication unless explicitly marked public. Enforce workspace membership and RBAC on the server.

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/workspaces` | List accessible workspaces |
| `POST` | `/workspaces` | Create workspace |
| `GET` | `/targets` | Search/list contract targets |
| `POST` | `/targets` | Create target and upload bytecode |
| `GET` | `/targets/:id` | Target details and artifact metadata |
| `POST` | `/targets/:id/scans` | Queue scan |
| `GET` | `/scans` | List scans and status |
| `GET` | `/scans/:id` | Scan summary, stages, errors |
| `GET` | `/scans/:id/graph` | CFG nodes and edges |
| `GET` | `/scans/:id/instructions` | Paginated disassembly |
| `GET` | `/scans/:id/findings` | Findings for scan |
| `GET` | `/findings/:id` | Finding detail and evidence |
| `PATCH` | `/findings/:id` | Update triage status/comment |
| `POST` | `/findings/:id/feedback` | Record reviewer feedback |
| `POST` | `/findings/:id/reproductions` | Request approved sandbox reproduction |
| `GET` | `/reports` | List reports |
| `POST` | `/scans/:id/reports` | Generate draft report |
| `POST` | `/reports/:id/approve` | Reviewer approval |
| `GET` | `/models` | List model versions and status |
| `GET` | `/health` | Liveness/readiness (restricted detail) |

### 10.1 API conventions

- Use standard HTTP status codes and a consistent error envelope.
- Add request IDs and idempotency keys for job-creation routes.
- Use cursor pagination for large results.
- Validate all payloads with schemas.
- Do not expose stack traces, RPC credentials, filesystem paths, or secrets.
- A queued scan returns `202 Accepted` with a scan ID and status URL.
- Rate-limit uploads and scan creation.
- Keep long-running work asynchronous; clients poll or subscribe to job status.
- Version API response contracts and feature schemas.

Example scan request:

```json
{
  "targetId": "uuid",
  "analysisProfile": "bytecode-baseline",
  "enableExperimentalMl": true
}
```

Example finding response:

```json
{
  "id": "uuid",
  "category": "reentrancy_candidate",
  "severity": "high",
  "confidence": 0.72,
  "status": "needs_review",
  "evidence": {
    "byteOffsets": [412, 468],
    "basicBlockIds": ["block-12", "block-14"],
    "signals": ["external_call_before_state_write"]
  },
  "limitations": "Static pattern only; exploitability has not been confirmed."
}
```

These examples are illustrative contracts; final schemas should be committed as OpenAPI definitions and tested in CI.

---

## 11. Page-by-Page UI/UX Specification

### 11.1 Design system

**Visual direction:** security operations console, technical, restrained, legible. Follow the supplied deck's deep-charcoal / neon-green concept without making the interface look like a trading casino.

**Core palette**
- App background: `#0B0F10`
- Primary surface: `#12191A`
- Raised surface: `#182122`
- Main text: `#E8F0EE`
- Muted text: `#98AAA5`
- Primary accent: `#B7F34A` (neon green)
- Info: `#65B7FF`
- Warning: `#F4C66A`
- Danger: `#FF6B6B`
- Border: `#2A3938`

Use semantic status colour plus text/icon; never rely on colour alone. Use a readable sans-serif UI font and monospace for addresses, byte offsets, hashes, and opcodes. Support keyboard navigation, visible focus states, WCAG AA contrast, responsive layouts, empty states, loading skeletons, and explicit error states.

**Global shell**
- Left sidebar: logo, workspace switcher, primary navigation.
- Top bar: breadcrumb, current network/environment badge, global search, notifications, profile menu.
- Main content: page title, short explanatory subtitle, primary CTA on the right.
- Avoid decorative charts that do not help an operator make a decision.

**Navigation**
1. Overview
2. Contract Targets
3. Scans
4. Findings
5. CFG Explorer
6. Reports
7. Model Lab (ML Engineer/Admin)
8. Campaigns (P1; hidden until enabled) — **Out of scope for the MVP (ADR-0007); no Campaigns route, page, or navigation entry is built.**
9. Infrastructure
10. Audit Log
11. Settings

### 11.2 Page 1 — Sign in / Accept invitation

**Purpose:** secure workspace access.

**Layout**
- Centered narrow panel on charcoal background.
- CyberStratum wordmark and short product statement.
- Email/OIDC sign-in; password flow only if not using an identity provider.
- Invitation acceptance shows workspace name and invited role.
- Footer links to privacy, terms, and status page.

**Content**
- “Analyse bytecode. Review evidence. Ship safer contracts.”
- Clear note: this is a security-analysis tool; findings require validation.
- Error messages for expired invite, invalid credentials, disabled account, or unavailable auth provider.

**States:** default, submitting, invalid credentials, expired invite, success, service unavailable.

### 11.3 Page 2 — Overview Dashboard

**Purpose:** answer “Is the system healthy, and what needs attention?”

**Top row KPI cards**
- Targets monitored
- Scans completed (time range selector)
- Findings awaiting triage
- Confirmed findings
- Queue depth / worker health

**Main content**
- Left (wide): scan activity timeline with status breakdown.
- Right: “Needs attention” list for failed scans, high-severity unreviewed findings, model errors, and stale jobs.
- Bottom: recent scans table with target, chain, status, duration, finding count, model version, created by.
- Small infrastructure panel: API status, queue status, worker heartbeat, database status.

**Interactions**
- Date range: 24h / 7d / 30d / custom.
- KPI cards navigate to filtered lists.
- Clicking a failed scan opens diagnostic details with secrets redacted.

**Do not show by default:** projected bounty or airdrop revenue as if it were actual revenue. If financial tracking is added later, separate actual, pending, estimated, and realised values. — **The MVP has no financial tracking at all.** The dashboard shows no bounty, airdrop, token-value, or campaign metric (ADR-0008).

### 11.4 Page 3 — Contract Targets

**Purpose:** add and organise bytecode targets.

**Table columns**
- Label / address
- Chain
- Bytecode type (runtime/init)
- Verification status (verified/unverified/unknown)
- Last scan
- Latest result
- Owner / created date
- Actions

**Filters:** chain, verification, scan status, date, label/address search.

**Add target drawer / wizard**
1. Select chain/environment.
2. Choose input method: paste bytecode, upload file, enter address for retrieval.
3. Choose runtime or init bytecode if known.
4. Add label and provenance/authorization note.
5. Validate preview: byte length, hash, parser compatibility, truncation warning.
6. Submit target.

**Important UX:** show a warning when the target is mainnet code. Analysis remains read-only. Do not request a wallet connection to scan bytecode.

### 11.5 Page 4 — Target Detail

**Header:** target label, shortened address, chain, bytecode hash, source provenance, created date.

**Tabs**
- Summary
- Bytecode
- Scans
- CFG
- Related contracts (P1)

**Summary**
- Last scan status and timestamp.
- Bytecode size, detected EVM version (if inferred), metadata status.
- Findings summary by severity.
- Warnings: unresolved dynamic jumps, truncated code, proxy not resolved, unknown compiler metadata.

**Bytecode tab**
- Virtualised disassembly table: offset, opcode, immediate data, stack effect, basic block.
- Search by offset/opcode.
- Selecting a row highlights corresponding CFG node and finding evidence.

### 11.6 Page 5 — Scan Creation

**Purpose:** configure and launch a scan.

**Wizard sections**
- Target and bytecode type.
- Analysis profile: baseline static rules / rules + experimental ML.
- Optional modules: CFG, N-grams, graph features, symbolic execution (if available).
- Execution policy: static only by default; sandbox reproduction is a separate approved action.
- Estimated queue status and resource profile.
- Review screen with target hash and configuration.

**CTA:** “Queue scan”.

**Confirmation:** show scan ID and progress page. Explain that ML is experimental if applicable and that a scan may produce false positives/negatives.

### 11.7 Page 6 — Scans List

**Table columns**
- Scan ID
- Target
- Chain
- Status
- Started / duration
- Ruleset version
- Model version
- Findings
- Requested by

**Filters:** status, chain, date, model, target, requester.

**Status values:** queued, validating, disassembling, feature extraction, rules analysis, ML inference, normalising results, completed, partial, failed, cancelled.

**Actions:** view, retry eligible failed scan, compare scans, export summary (permission controlled).

### 11.8 Page 7 — Scan Detail / Pipeline Trace

**Header:** target, scan ID, status, started time, elapsed time, retry/cancel controls where allowed.

**Pipeline stepper**
1. Input validation
2. Disassembly
3. Basic blocks / CFG
4. Feature extraction
5. Rules
6. ML inference (if enabled)
7. Finding normalisation
8. Complete

Each step shows status, duration, version, and safe error summary.

**Panels**
- Findings by severity
- Parser warnings
- Unresolved jumps and graph coverage
- Feature/model version
- Job resource usage and retry history

**Failure UX:** give actionable errors (invalid hex, unsupported opcode table, truncated input, worker timeout) without leaking stack traces or secrets.

### 11.9 Page 8 — Findings Queue

**Purpose:** triage candidate findings efficiently.

**Table columns**
- Severity
- Finding title/category
- Target
- Confidence
- Review status
- Detector/model version
- First seen
- Assigned reviewer

**Filters:** severity, category, confidence range, status, chain, detector, target.

**Design:** use confidence and severity as separate fields. Do not equate a high ML score with confirmed exploitability.

### 11.10 Page 9 — Finding Detail

**Header:** finding title, severity, confidence, status, target, detector version.

**Primary column**
- Summary in plain language.
- Why it was flagged.
- Evidence list with byte offsets, opcodes, basic blocks, and CFG path.
- Rule/feature signals.
- Limitations and alternative explanations.
- Reproduction status.

**Side panel**
- Status control: new, triage, confirmed, false positive, needs more evidence.
- Assignee, comments, labels.
- “Create sandbox reproduction” action requiring permission and confirmation.
- “Draft report” action.
- Timeline of all decisions.

**Evidence viewer**
- Disassembly with relevant offsets highlighted.
- CFG graph with branch edges and unresolved edges visually distinct.
- A textual fallback for screen readers and export.

### 11.11 Page 10 — CFG Explorer

**Purpose:** understand control flow, not just display a decorative graph.

**Layout**
- Main canvas: zoomable CFG with block nodes and directed edges.
- Left inspector: block list, search, entry/exit filters, unresolved-jump filter.
- Right inspector: selected block instructions, incoming/outgoing edges, findings touching the block.
- Toolbar: fit graph, zoom, show/hide opcodes, show findings, export SVG/PNG (if implemented).

**Visual encoding**
- Normal block: neutral surface.
- Selected block: accent border.
- Finding-linked block: severity outline plus icon.
- Unresolved edge: dashed line and “unresolved” label.
- Entry/exit blocks: explicit markers.

**Performance:** large graphs must support graph slicing, lazy rendering, and a text/list alternative. Do not attempt to render thousands of nodes at once.

### 11.12 Page 11 — Reports

**Report types**
- Internal scan summary
- Finding technical report
- Responsible-disclosure draft
- Executive summary

**Report builder**
- Select scan/findings.
- Include scope, target hashes, tools/versions, methodology, limitations, evidence, reproduction details, and remediation suggestions.
- Redact internal notes and secrets.
- Preview in browser and export PDF/Markdown/JSON.

**Approval:** responsible-disclosure report requires reviewer approval. No automatic submission to bounty platforms.

### 11.13 Page 12 — Model Lab

**Audience:** ML engineer / admin only.

**Sections**
- Model registry: name, version, training dataset, feature schema, status.
- Evaluation runs: precision, recall, F1, PR-AUC, false-positive rate, per-class results.
- Calibration and threshold settings.
- Confusion matrix and error review queue.
- Dataset provenance and label-quality notes.
- Drift monitoring by chain/compiler/bytecode family.

**Release gate:** no model becomes production-active without evaluation results, model card, approved thresholds, reproducible artifact, and rollback path.

### 11.14 Page 13 — Infrastructure

**Purpose:** operational health and resource use.

**Cards**
- API health
- Queue depth and oldest job age
- Worker heartbeats and active workers
- Database connectivity
- Object storage status
- Error rate and latency
- Sandbox worker status

**Tables**
- Job failures grouped by reason
- Worker resource usage
- Recent deployments and version IDs

**Security:** do not show raw secrets, complete environment variables, private RPC credentials, or sensitive host paths. Admin-only.

### 11.15 Page 14 — Audit Log

**Columns:** timestamp, actor, action, resource type, resource, outcome, request ID.

**Filters:** actor, action, resource, date, workspace.

Log target creation, scan requests, report exports, permission changes, model releases, sandbox approvals, and authentication/security events. Sensitive metadata must be redacted. (Campaign policy changes are **removed** — there is no campaign policy, because campaigns are out of scope; ADR-0007.)

### 11.16 Page 15 — Settings

**Sections**
- Workspace profile and members
- Roles and permissions
- Chain/RPC integrations (credentials stored in secret manager)
- Scan defaults and resource limits
- Data retention and deletion
- Notifications
- Security settings / identity provider
- API keys (show once, rotate/revoke)
- Billing and cost controls (if applicable)

### 11.17 Page 16 — Campaigns (P1, optional)

> **Correction note (2026-10-28):** **Out of scope for the MVP.** This page
> is not built and is not in the navigation. Note also that the "pending
> reward / confirmed reward / realised value" fields below are exactly the
> campaign-income tracking the MVP excludes — so this page would need its own
> ADR, and probably a compliance review, before it is reconsidered. — governed by
> [`docs/adr/0007-campaign-tracking-out-of-mvp-scope.md`](docs/adr/0007-campaign-tracking-out-of-mvp-scope.md)
> and
> [`docs/adr/0008-no-airdrop-bounty-or-campaign-promises.md`](docs/adr/0008-no-airdrop-bounty-or-campaign-promises.md).

This module is a compliant testnet activity ledger, not an anti-Sybil evasion engine.

**Campaign list:** protocol, network, official terms URL, authorization status, activity status, budget consumed, last activity.

**Campaign detail**
- Official terms and captured review date.
- Allowed/prohibited actions and rate limits.
- Task checklist and evidence requirements.
- Activity timeline and transaction hashes.
- Wallet labels (public addresses only).
- Estimated cost, actual cost, pending reward, confirmed reward, realised value.
- Stop/disable automation control.

**Hard gate:** do not enable automation unless the campaign's terms and explicit permission status have been reviewed. No identity concealment or controls bypass.

### 11.18 Responsive behavior

- Desktop-first for CFG and disassembly work.
- Tablet: collapsible sidebar, tables retain horizontal scroll and essential columns.
- Mobile: dashboard and finding summary are readable; complex graph interactions are secondary and include a list view.
- All primary actions must work with keyboard and screen reader.

---

## 12. Design Components and Content Standards

Reusable components:
- `AppShell`, `SidebarNav`, `TopBar`, `WorkspaceSwitcher`
- `KpiCard`, `StatusBadge`, `SeverityBadge`, `ConfidenceMeter`
- `DataTable`, `FilterBar`, `EmptyState`, `ErrorState`, `Skeleton`
- `ScanPipelineStepper`, `DisassemblyViewer`, `CFGCanvas`
- `FindingEvidencePanel`, `ReviewTimeline`, `ApprovalDialog`
- `Code/HexCopyButton`, `AddressDisplay`, `HashDisplay`
- `ReportPreview`, `AuditLogTable`

Content rules:
- Use “candidate finding” until reviewed.
- Label model-based results “experimental” until validated.
- Show timestamps in the user's locale while storing UTC.
- Show shortened addresses with copy-full-address control.
- Every chart needs a title, time range, legend, and accessible text alternative.
- Provide useful empty states with one clear next action.

---

## 13. ML Data, Evaluation, and Release Process

> **Correction note (2026-10-28):** This section governs the **scikit-learn
> TF-IDF baseline** only. The GNN is **deferred, not scheduled** (ADR-0006),
> and no labelled dataset is known to exist — §13.1's dataset requirements are
> therefore the first thing to satisfy, not an assumption. The release gate in
> §13.3 is unchanged and still applies to the baseline model. — governed by
> [`docs/adr/0006-scikit-learn-tfidf-baseline-gnn-deferred.md`](docs/adr/0006-scikit-learn-tfidf-baseline-gnn-deferred.md).

### 13.1 Dataset quality

- Record source, license/permission, contract/project family, chain, compiler metadata where known, label source, reviewer, and label confidence.
- Avoid duplicates across train/test splits.
- Include benign contracts and difficult negatives, not only known vulnerable examples.
- Keep vulnerability categories distinct; do not treat one contract as one label if it contains multiple findings.
- Review label disagreement and dataset leakage.

### 13.2 Metrics

At minimum:
- Precision and recall per vulnerability category.
- F1 and PR-AUC for imbalanced classes.
- False positives per 100 contracts or per scan.
- Recall at a practical analyst review budget.
- Calibration (e.g. reliability curve / Brier score).
- Performance by chain/compiler/family and bytecode size.
- Inference latency and memory use.

Accuracy alone is insufficient because vulnerable examples may be rare.

### 13.3 Model release gate

1. Dataset and label review.
2. Reproducible train/validation/test split.
3. Baseline rule and baseline ML comparison.
4. Holdout evaluation at contract/project-family level.
5. Model card and limitations.
6. Security review of model artifact loading.
7. Shadow deployment.
8. Human-reviewed rollout with rollback.

---

## 14. Testing Strategy

### 14.1 Unit tests

- Opcode table mapping by EVM version.
- `PUSH1`–`PUSH32` immediate parsing.
- Truncated PUSH behavior.
- Unknown/invalid opcode handling.
- Basic block boundaries and CFG edge extraction.
- N-gram counts and TF-IDF reproducibility.
- Feature schema versioning.
- Finding deduplication and confidence/severity separation.
- RBAC policy checks.

### 14.2 Integration tests

- Target upload → scan queue → worker → persisted result.
- Worker retry and idempotency.
- Failed scan recovery.
- Report generation and reviewer approval.
- Tenant isolation across targets, scans, findings, and reports.
- Object storage permissions and signed URL expiry.
- Sandbox resource limits and network isolation.

### 14.3 Security tests

- Unauthorized target access and IDOR attempts.
- Malformed/oversized bytecode uploads.
- Zip/decompression bombs if archive upload is supported.
- Rate limiting and abuse controls.
- Secrets in logs and error messages.
- Dependency vulnerabilities and container configuration.
- Sandbox escape-resistance review.

### 14.4 Evaluation corpus

Create a versioned corpus of:
- known benign contracts,
- known vulnerable contracts with credible references,
- synthetic edge cases,
- malformed/truncated bytecode,
- proxy/implementation pairs,
- different compiler and EVM versions.

Record expected outputs and known limitations. Never use a single demonstration contract as evidence of general model performance.

---

## 15. Non-Functional Requirements

- **Reliability:** jobs are idempotent and retryable; no silent result loss.
- **Scalability:** queue workers can scale independently of web/API processes.
- **Performance:** define baseline targets after profiling; show queue wait separately from execution duration.
- **Observability:** structured logs, metrics, trace/request IDs, and alerting.
- **Security:** least privilege, tenant isolation, secret management, and sandbox boundaries.
- **Maintainability:** typed API contracts, migrations, linting, formatting, and CI.
- **Reproducibility:** every scan stores parser/rules/model/feature versions and input hash.
- **Explainability:** every candidate finding links to evidence and limitations.
- **Accessibility:** keyboard support, contrast, semantic labels, and non-colour-only status indicators.
- **Portability:** local development on **native PostgreSQL 17.11 and Redis 8.10.3 (no Docker)** and documented environment configuration. — governed by
  [`docs/adr/0003-no-docker-native-postgres-and-redis.md`](docs/adr/0003-no-docker-native-postgres-and-redis.md).

Numeric service-level objectives should be set after profiling and deployment constraints are known; do not promise scan latency before benchmark data exists.

---

## 16. Suggested Repository Structure

> **Correction note (2026-10-28):** This tree described a hypothetical
> Node/TypeScript monorepo with `packages/contracts`, `packages/database`,
> `packages/ui`, and `docker-compose.yml`. Corrected to the structure that
> actually exists: a Python API under `apps/api`, a Next.js app under
> `apps/web`, the EVM analysis engine as an installable Python package under
> `packages/evm_analysis`, and **no Docker**. — governed by
> [`docs/adr/0001-python-backend-over-node-prisma.md`](docs/adr/0001-python-backend-over-node-prisma.md),
> [`docs/adr/0002-nextjs-frontend.md`](docs/adr/0002-nextjs-frontend.md),
> and
> [`docs/adr/0003-no-docker-native-postgres-and-redis.md`](docs/adr/0003-no-docker-native-postgres-and-redis.md).

```text
cyberstratum/
  apps/
    web/                    # Next.js App Router UI (TypeScript, Tailwind)
      app/                  # 6 pages (Overview, Scans, New scan, Scan detail,
                            # Findings, Reproducibility)
      src/
        components/         # 9 UI primitives
        lib/                # typed API client + canonical domain types
    api/                    # Python FastAPI API
      app/
        main.py             # create_app() — CORS, request-ID, error handlers
        worker.py           # RQ job consumer: enqueue_scan(), process_scan_job()
        core/               # settings, structured logging, API-key auth, errors
        db/                 # SQLAlchemy base, enums, session, models
        api/                # routers: health, scans, findings
        schemas/            # Pydantic request/response schemas
        services/           # pipeline, detectors, bytecode fetch, storage
        queue/              # Redis + RQ connection helper
      alembic/              # Alembic migrations (env.py + versions/)
  packages/
    evm_analysis/           # installable Python package: opcode table,
                            # disassembler, metadata, CFG, resolver, features
      evm_analysis/
      data/opcodes.json     # vendored, generated, committed opcode table
    ml_baseline/            # installable Python package: scikit-learn TF-IDF
      evm_ml/                # tokenize, dataset, features, model, evaluate
                            # (standalone; not wired into the scan pipeline)
  workers/
    sandbox_runner/         # isolated, approval-gated reproduction (disabled)
  scripts/
    generate_opcodes.mjs    # regenerate the vendored opcode table (Node)
    crosscheck_evmole.py    # independent-oracle cross-validation
    validate_real_bytecode.py
    build_fixture_dataset.py
  docs/
    adr/                    # architecture decision records (authoritative)
    architecture.md         # as-built architecture
    product-requirements.md # distilled requirements + traceability
    runbook.md              # local development runbook
  tests/
    unit/                   # engine + ML baseline
    api/                    # scans, findings, worker, health
    e2e/                    # (empty)
  .env.example
  README.md
```

This is the structure in use. Note the EVM analysis engine is a **separate
installable Python package** rather than a folder under `workers/`, so that it
can be unit-tested, versioned, and imported by both the API and the workers
without importing either.

---

## 17. Development Phases and Deliverables

### Phase 0 — Discovery and architecture (Week 1)

- Confirm MVP boundaries, supported EVM versions/chains, target authorization policy, and deployment constraints.
- Define threat model and data retention.
- Choose parser/library and baseline static-analysis integrations.
- Publish OpenAPI skeleton, schema, and design tokens.
- Deliverable: signed-off architecture decision records (ADRs), clickable low-fidelity flows, repo skeleton.

### Phase 1 — Foundation (Weeks 2–3)

- Auth, workspace, RBAC, database migrations.
- App shell, dashboard shell, target list/create flow.
- Object storage and queue infrastructure.
- CI lint/typecheck/test/build.
- Deliverable: usable app with targets and background job plumbing.

### Phase 2 — Bytecode parser and CFG (Weeks 4–5)

- Correct disassembly with immediate-data handling.
- Basic blocks, CFG, unresolved edge support.
- Disassembly UI and CFG Explorer.
- Unit tests and corpus fixtures.
- Deliverable: deterministic parser and visual control-flow exploration.

### Phase 3 — Scan pipeline and rules (Weeks 6–7)

- Queue orchestration, feature extraction, baseline rules, result normalisation.
- Scan list/detail, finding queue/detail, retry/failure handling.
- Deliverable: end-to-end reproducible static scan.

### Phase 4 — ML baseline and evaluation (Weeks 8–9)

> **Correction note (2026-10-28):** The GNN clause below is **deferred, not
> scheduled**. This phase delivers the **scikit-learn TF-IDF baseline** only.
> — governed by
> [`docs/adr/0006-scikit-learn-tfidf-baseline-gnn-deferred.md`](docs/adr/0006-scikit-learn-tfidf-baseline-gnn-deferred.md).

- Dataset manifest and label policy.
- TF-IDF N-gram baseline.
- ML inference interface; GNN only if dataset size/quality justifies it. — **GNN deferred (ADR-0006).**
- Evaluation report and model card.
- Deliverable: measurable experimental model with known limitations.

### Phase 5 — Reporting and sandbox controls (Weeks 10–11)

- Report drafts and reviewer approval.
- Isolated reproduction worker with no default outbound network.
- Audit logs and security testing.
- Deliverable: controlled triage-to-report workflow.

### Phase 6 — Hardening and release (Week 12)

- Performance/security tests, backups, monitoring, runbooks, user acceptance.
- Staging deployment and rollback drill.
- Deliverable: MVP release candidate and operational handover.

Timeline is an initial estimate for a small experienced team; it depends on scope, dataset readiness, chosen analysis libraries, and staffing.

---

## 18. Acceptance Criteria

MVP is acceptable when:

1. A user can create a target from pasted or uploaded bytecode and retrieve its hash.
2. The parser correctly handles PUSH immediate data and has tests for all PUSH widths and truncated inputs.
3. A scan runs asynchronously and exposes each pipeline stage and failure reason.
4. CFG output includes unresolved edges and does not incorrectly assume all graphs are acyclic.
5. A scan's features and results are reproducible from stored versions and input hash.
6. Findings display evidence offsets, confidence, severity, detector version, and limitations.
7. A reviewer can mark a finding false positive and the decision is audited.
8. Reports cannot be externally approved/exported through the responsible-disclosure flow without the configured reviewer permission.
9. Sandbox jobs are isolated, resource-limited, and require explicit approval.
10. Cross-workspace access tests pass for all major resources.
11. No secrets appear in logs or exported reports.
12. The app has loading, empty, partial, failed, and success states for major workflows.
13. CI passes linting, type checking, unit tests, integration tests, and production build.
14. ML results are labelled experimental until evaluation and release criteria are met.
15. Campaign tracking, if enabled, records official terms and does not implement anti-Sybil evasion or prohibited actions. — **Withdrawn from the MVP.** Campaign tracking is out of scope and is not built; this criterion does not apply to the MVP. — governed by
    [`docs/adr/0007-campaign-tracking-out-of-mvp-scope.md`](docs/adr/0007-campaign-tracking-out-of-mvp-scope.md).

---

## 19. DevOps, Monitoring, and Runbooks

### 19.1 Required metrics

- API request count, error rate, latency percentiles.
- Queue depth, oldest job age, retries, dead-letter count.
- Scan stage duration and failure reason.
- Parser warnings and unresolved-jump rate.
- ML inference latency, model errors, distribution drift.
- Sandbox job resource usage and termination reasons.
- Database connection pool, query latency, storage utilisation.
- Artifact upload/download failures.

### 19.2 Alerts

- Queue backlog exceeds configured threshold.
- Worker heartbeat missing.
- Repeated parser/ML failures after deployment.
- Elevated API 5xx or latency.
- Database/storage unavailable.
- Sandbox attempts outbound network access.
- Unusual report export or permission-change activity.

### 19.3 Operational runbooks

- Stuck scan / dead-letter recovery.
- Roll back parser, ruleset, or model version.
- Rotate RPC credentials and API secrets.
- Restore database and artifact storage from backup.
- Revoke compromised user/session/API key.
- Disable sandbox workers quickly.
- Incident response and audit-log preservation.

---

## 20. Investor and Financial Dashboard Requirements (Optional, Not MVP Core)

> **Correction note (2026-10-28):** **Not built, and out of MVP scope.** This
> page is explicitly optional and is not part of the MVP. Note the
> "token allocations estimated / tokens received / realised proceeds" lines
> below: the MVP carries **no** such telemetry, and a bounty/airdrop-income
> view is exactly the kind of feature ADR-0008 prohibits promising. It is
> retained here as an internal-management option, not a product commitment.
> — governed by
> [`docs/adr/0007-campaign-tracking-out-of-mvp-scope.md`](docs/adr/0007-campaign-tracking-out-of-mvp-scope.md)
> and
> [`docs/adr/0008-no-airdrop-bounty-or-campaign-promises.md`](docs/adr/0008-no-airdrop-bounty-or-campaign-promises.md).

If management wants internal financial reporting, create a separate **Finance / Outcomes** page with categories:
- bounty opportunity pipeline,
- submitted reports,
- accepted findings,
- bounty awards pending payment,
- cash received,
- testnet activity costs,
- token allocations estimated,
- tokens received/vested,
- realised proceeds,
- infrastructure spend,
- forecast versus actual.

Each number must carry a source and state: `actual`, `pending`, `estimated`, or `forecast`. Estimated airdrop value should show valuation timestamp, pricing source, vesting/liquidity assumptions, and a clear disclaimer. Do not present forecast amounts as earned revenue.

---

## 21. Open Questions for Product Owner

> **Correction note (2026-10-28):** Several of these questions have since been
> **answered by decision** and are marked accordingly. Questions 3, 5, and 10
> are resolved (see ADR-0004/0005, ADR-0006, ADR-0007). Question 9 is moot
> for the MVP because campaigns are out of scope. The remainder still need an
> owner decision. — governed by
> [`docs/adr/0001-python-backend-over-node-prisma.md`](docs/adr/0001-python-backend-over-node-prisma.md),
> [`docs/adr/0004-custom-vendored-opcode-table.md`](docs/adr/0004-custom-vendored-opcode-table.md),
> [`docs/adr/0005-evmole-as-cross-validation-oracle.md`](docs/adr/0005-evmole-as-cross-validation-oracle.md),
> [`docs/adr/0006-scikit-learn-tfidf-baseline-gnn-deferred.md`](docs/adr/0006-scikit-learn-tfidf-baseline-gnn-deferred.md),
> and
> [`docs/adr/0007-campaign-tracking-out-of-mvp-scope.md`](docs/adr/0007-campaign-tracking-out-of-mvp-scope.md).

Resolve these before implementation is considered final:

1. What is the initial chain list and supported EVM fork range? — **Fork range answered** (`frontier` → `prague`; ADR-0004). Initial chain list still open.
2. Will users paste bytecode, provide addresses, upload artifacts, or all three? — **All three** are supported by the target model (FR-2.1).
3. Which existing disassembler/static-analysis libraries are acceptable? — **Answered.** Custom `packages/evm_analysis` with a vendored fork-accurate table; `pyevmasm` rejected; `evmole` validation-only. ADR-0004, ADR-0005.
4. Is there a labelled dataset? What are its provenance and licences? — **Open, and blocking for the ML baseline.** No labelled dataset is known to exist. ADR-0006.
5. Is the first ML deliverable a baseline classifier or is a GNN mandatory? — **Answered: baseline classifier.** scikit-learn TF-IDF; GNN deferred. ADR-0006.
6. Which user roles and workspace boundaries are needed for the first customer? — **Answered:** the six roles of §3.1, workspace-level isolation.
7. Which report formats are mandatory? — **Open.**
8. What deployment budget and target concurrency are available? — **Partially answered:** free tier only, no paid service required (ADR-0003). Target concurrency still open.
9. Which campaign interactions are explicitly allowed by each target protocol? — **Moot for the MVP.** Campaigns are out of scope. ADR-0007.
10. Should campaign tracking ship in P1 or be removed from the first product? — **Answered: removed from the first product.** ADR-0007.
11. What is the actual seed raise target? — **Open (business).** Also §2.2's allocation reconciliation.
12. Which financial forecast assumptions are supported by historical evidence? — **Open (business).** §2.1 marks these as hypotheses.
13. What constitutes success for the first 30/60/90 days? — **Open.**
14. Who is accountable for reviewing findings and approving disclosure reports? — **Open.** The `reviewer` role exists, but the accountable person is unassigned.

---

## 22. Developer Handoff Checklist

Before coding:
- [ ] Confirm scope and open questions.
- [ ] Agree on stack, repository, environments, and deployment.
- [ ] Review threat model and authorised-research policy.
- [ ] Approve data model and API contract.
- [ ] Approve design tokens and page wireframes.

During coding:
- [ ] Work in vertical slices; ship target → scan → findings before advanced ML.
- [ ] Keep parser and model versions attached to every scan.
- [ ] Add tests with each parser rule and detector.
- [ ] Use feature flags for experimental ML. (The campaign-tooling flag is **removed** — campaigns are out of scope, ADR-0007.)
- [ ] Never place secrets or private keys in source control or DB records.

Before release:
- [ ] Run parser corpus and ML evaluation.
- [ ] Run tenant-isolation and sandbox tests.
- [ ] Validate report redaction and approval controls.
- [ ] Configure monitoring, backups, alerts, and rollback.
- [ ] Complete operator and developer runbooks.
- [ ] Review all investor-facing claims against measured evidence.

---

## Appendix A — Pitch Deck Mapping

> **Correction note (2026-10-28):** Two rows below — "Dual-engine solution"
> and "Airdrop business model" — assume a **campaign ledger and airdrop
> allocation tracking** that are **out of MVP scope** and not built. The
> "Bug-bounty business model" row is an internal business-model statement,
> not a product feature: CyberStratum does not track submissions, awards, or
> payment status, and makes **no** promise of bounty income. The
> "Financial projections" row remains a management/finance concern and is not
> a product commitment. — governed by
> [`docs/adr/0007-campaign-tracking-out-of-mvp-scope.md`](docs/adr/0007-campaign-tracking-out-of-mvp-scope.md)
> and
> [`docs/adr/0008-no-airdrop-bounty-or-campaign-promises.md`](docs/adr/0008-no-airdrop-bounty-or-campaign-promises.md).

| Pitch deck section | Product implementation / evidence required |
|---|---|
| Dual-engine solution | Separate security-analysis pipeline and compliant campaign ledger; do not couple scanner findings to automatic exploitation. |
| Technical architecture | Bytecode intake, parser, CFG, feature extraction, rules, optional ML, review, reports. |
| Market / traction | Only publish measured scans, benchmark results, and verifiable outcomes. |
| Bug-bounty business model | Track submissions, acceptance, awards, and payment status; no guaranteed payout. |
| Airdrop business model | Track permitted activity and realised allocation separately; no guaranteed token distribution. |
| Operational blueprint | Phased roadmap in Section 17. |
| Competitive advantage | Benchmark against baselines on a held-out, labelled corpus. |
| Financial projections | Separate actual cash, pending awards, estimated token value, realised proceeds, and costs. |
| Capital deployment | Reconcile 50/35/15 pitch allocation with detailed $122k expense plan. |

## Appendix B — Suggested First Sprint Tickets

> **Correction note (2026-10-28):** Ticket 1 said "Docker Compose" and ticket
> 2 said "Define Prisma schema". Corrected: **no Docker** — native
> PostgreSQL 17.11 and Redis 8.10.3 — and the data layer is **SQLAlchemy
> models + Alembic migrations**, not a Prisma schema. Ticket 5 is also pinned
> to the custom vendored opcode table rather than left as "a parser". — governed by
> [`docs/adr/0001-python-backend-over-node-prisma.md`](docs/adr/0001-python-backend-over-node-prisma.md),
> [`docs/adr/0003-no-docker-native-postgres-and-redis.md`](docs/adr/0003-no-docker-native-postgres-and-redis.md),
> and
> [`docs/adr/0004-custom-vendored-opcode-table.md`](docs/adr/0004-custom-vendored-opcode-table.md).

1. Create the monorepo skeleton, CI, and environment validation; document the native PostgreSQL 17.11 and Redis 8.10.3 startup commands. **No Docker Compose.**
2. Define the **SQLAlchemy 2** models and **Alembic** migration setup for users, workspaces, targets, scans, findings, audit events.
3. Implement auth middleware and workspace RBAC tests.
4. Implement bytecode input validation and SHA-256 hashing.
5. Implement the parser interface over the vendored fork-accurate opcode table, with opcode fixture tests and an `evmole` cross-validation script.
6. Create target list and target creation UI.
7. Implement scan job model and RQ worker skeleton.
8. Add API error contract, request IDs, and structured logging.
9. Add design system tokens and reusable table/status components.
10. Write README with setup, test, migration, and troubleshooting instructions.

**End of document.**

---

## 23. Technology Stack and Engineering Standards

This section converts the logical architecture into an actionable implementation stack. The goal is a low-cost MVP that can run locally, use free tiers for demos, and migrate to paid infrastructure without redesigning core business logic.

### 23.1 Selected stack

> **Correction note (2026-10-28):** Four rows in this table were stale:
> **API validation** said Zod (a TypeScript library) for a Python API,
> **Queue** said BullMQ, **EVM disassembly** left the library undecided, and
> **Local services** said Docker Compose. Corrected to the resolved stack:
> **Pydantic** validation, **RQ** on Redis, the **custom vendored
> fork-accurate opcode table** (`packages/evm_analysis`, generated from
> `ethereum/execution-specs` v2.20.0) as the production disassembler, and
> **native PostgreSQL 17.11 / Redis 8.10.3 with no Docker**. The **Graph ML
> row is now deferred, not "later"** — see ADR-0006. — governed by
> [`docs/adr/0001-python-backend-over-node-prisma.md`](docs/adr/0001-python-backend-over-node-prisma.md),
> [`docs/adr/0003-no-docker-native-postgres-and-redis.md`](docs/adr/0003-no-docker-native-postgres-and-redis.md),
> [`docs/adr/0004-custom-vendored-opcode-table.md`](docs/adr/0004-custom-vendored-opcode-table.md),
> [`docs/adr/0005-evmole-as-cross-validation-oracle.md`](docs/adr/0005-evmole-as-cross-validation-oracle.md),
> and
> [`docs/adr/0006-scikit-learn-tfidf-baseline-gnn-deferred.md`](docs/adr/0006-scikit-learn-tfidf-baseline-gnn-deferred.md).

| Layer | Selection | Why / implementation note |
|---|---|---|
| Web application | Next.js App Router, React, TypeScript | Dashboard, authenticated pages, routing, and server-rendered UI where useful. |
| UI system | Tailwind CSS + shadcn/ui + Lucide icons | Reusable accessible components and consistent design tokens. |
| API | Python + FastAPI + Pydantic | Async-friendly REST API, OpenAPI generation, typed request/response validation, and a natural fit with the Python ML pipeline. Keep long-running scans in background workers. |
| API validation | **Pydantic v2** (server-side) + TypeScript types generated from / checked against the OpenAPI contract on the client | Request/response validation happens in the Python API. The Next.js client consumes the published OpenAPI contract rather than re-validating with a separate runtime schema library. |
| ORM / migrations | SQLAlchemy 2 + Alembic + PostgreSQL | Typed queries and versioned migrations. Use raw SQL only where justified and reviewed. **Prisma is not used.** |
| Queue | **Redis + RQ** | Durable-enough asynchronous job orchestration for the MVP, with retries and dead-letter handling. **BullMQ is not used.** |
| EVM disassembly | **Custom `packages/evm_analysis` package with a vendored, versioned, fork-accurate opcode table**, generated from pinned `ethereum/execution-specs` v2.20.0 and wrapped behind an internal interface | `pyevmasm` was rejected as stale (no `PUSH0`, no modern opcodes). `evmole` 0.9.4 is retained **only** as an independent cross-validation oracle. Fork coverage: `frontier` → `prague`. See ADR-0004 and ADR-0005. |
| CFG and feature extraction | **Python module** (`packages/evm_analysis`) with versioned input/output schemas | Keep parsing deterministic and preserve byte offsets and unresolved jump information. |
| Baseline ML | Python + scikit-learn + sparse TF-IDF features | Establish a reproducible baseline before investing in a GNN. |
| Graph ML (**deferred**) | PyTorch; PyTorch Geometric only if graph data and labels justify it | **Deferred, not scheduled.** §6.4 lists nine items engineering must define before a GNN exists, and no labelled dataset is known to exist. Reopening conditions are in ADR-0006. |
| Data analysis | pandas, NumPy, scikit-learn metrics | Dataset inspection, evaluation, threshold analysis, and model cards. |
| Sandbox | Isolated, non-privileged worker running a pinned local EVM/test harness | Static-only is the default. No outbound network or host secrets; strict limits and explicit approval. **Disabled by default.** |
| Testing | Vitest for TypeScript; pytest for Python; Playwright for end-to-end UI | Pick one TypeScript unit-test runner and standardise it across the repo. |
| Code quality | ESLint, Prettier, TypeScript strict mode, Python Ruff | Enforce in CI. |
| Local services | **Native PostgreSQL 17.11 + Redis 8.10.3 — no Docker, no docker-compose.yml** | Reproducible local Postgres and Redis, started with the documented native commands in `docs/runbook.md`. See ADR-0003. |
| Source control / CI | GitHub + GitHub Actions | Pull-request checks, build, tests, dependency audit, and deployment workflow. |
| Observability | Structured JSON logs (structlog) + OpenTelemetry-compatible metrics/traces; optional hosted error tracker | Ensure a local logging path exists even if a vendor quota is exceeded. |
| Artifact storage | Local filesystem for development; S3-compatible object storage adapter in staging/production | Store bytecode, reports, dataset manifests, and model artifacts; keep object keys out of public URLs. |

### 23.2 Architectural rules

- Keep UI, API, parser, rules, model inference, and sandbox behind explicit module interfaces.
- The scanner must run with ML disabled.
- Use a model adapter interface so scikit-learn and any future GNN can be swapped without changing API contracts.
- Use an object-storage adapter so local storage and a cloud bucket share the same application interface.
- Use environment variables for service configuration; validate required values at startup.
- Pin dependency versions and record parser, ruleset, feature-schema, and model versions for each scan.
- Avoid introducing Kubernetes, a service mesh, or multiple independently deployed microservices during the MVP unless a measured need appears.
- Do not add paid AI APIs as a runtime dependency. If optional LLM-assisted summaries are later added, they must be feature-flagged and must never be the sole basis for vulnerability classification.


### 23.3 Repository implementation notes

> **Correction note (2026-10-28):** The boundary list below described a
> TypeScript monorepo (`packages/contracts`, `packages/database` with a
> **Prisma schema**, `workers/evm-analysis`). Corrected to the structure that
> actually exists: a **Next.js** `apps/web` client, a **Python FastAPI**
> `apps/api` with **SQLAlchemy** models and **Alembic** migrations, and the EVM
> analysis engine as an installable Python package at
> `packages/evm_analysis`. **Prisma is not used.** — governed by
> [`docs/adr/0001-python-backend-over-node-prisma.md`](docs/adr/0001-python-backend-over-node-prisma.md),
> [`docs/adr/0002-nextjs-frontend.md`](docs/adr/0002-nextjs-frontend.md),
> and
> [`docs/adr/0004-custom-vendored-opcode-table.md`](docs/adr/0004-custom-vendored-opcode-table.md).

Recommended package boundaries:
- `apps/web`: UI only; call the API through typed client functions. Next.js App Router, TypeScript, Tailwind.
- `apps/api`: authentication, RBAC, targets, scans, findings, reports, audit log. Python, FastAPI, Pydantic, SQLAlchemy 2, Alembic.
- `packages/evm_analysis`: the EVM analysis engine as an installable Python package — disassembly, CFG, jump resolution, static rules, feature generation. Separately versioned and unit-testable, importable by both the API and the workers.
- `apps/api/app/worker.py`: the RQ job consumer and pipeline coordination. It lives inside the API package rather than in a separate `workers/` tree so that the job function and the service layer it calls share one importable package.
- `packages/ml_baseline`: the scikit-learn TF-IDF baseline as an installable Python package — tokenizer, dataset, adapter, evaluation, manifest, model card. It is standalone and is **not** imported by the API, so it carries no runtime coupling.
- `workers/sandbox_runner`: separate security boundary, disabled by default.
- `packages/contracts`: shared schemas and API types, generated from the FastAPI OpenAPI document. *(Not built.)*
### 23.4 Python backend implementation notes

> **Correction note (2026-10-28):** This section was already correct and is
> the **governing** statement of the backend stack. The contradictory
> Node/TypeScript/Prisma/BullMQ material in §8.1, §8.2, §23.3, §25.2, §27
> and Appendix B has been corrected to match this section. The choices below
> are now closed rather than open ("pick one and standardise"): **RQ + Redis**
> is the queue, and **SQLAlchemy 2 + Alembic** is the ORM. — governed by
> [`docs/adr/0001-python-backend-over-node-prisma.md`](docs/adr/0001-python-backend-over-node-prisma.md).

- **API framework:** FastAPI.
- **Validation and schemas:** Pydantic models; expose OpenAPI and keep response contracts versioned.
- **Database access:** SQLAlchemy 2 async or sync sessions (choose one approach consistently) with Alembic migrations. Do not use Prisma in the Python backend.
- **Authentication:** secure session or OIDC/JWT integration; validate issuer, audience, expiry, and workspace membership server-side.
- **Queue:** **RQ + Redis is the decided choice.** Celery remains a documented alternative if task routing, scheduling, and workflow needs later justify the extra complexity. **BullMQ is not used.**
- **Workers:** Python workers can share typed domain models with the API, but should run in separate processes from the API.
- **Testing:** pytest + HTTPX/FastAPI TestClient; add integration tests against disposable PostgreSQL and Redis.
- **Linting/type checks:** Ruff + mypy or Pyright; choose a consistent strictness level.
- **Dependency management:** `uv` or Poetry; pin versions and commit the lockfile.
- **API server:** Uvicorn for development; a production deployment configuration should define worker count, graceful shutdown, health checks, and request timeouts.
- **Do not use BullMQ from Python** unless the team intentionally introduces a cross-language queue protocol and tests its compatibility. A Python-native queue avoids unnecessary runtime coupling.


---

## 24. External Services and Free-Tier Research

> **Correction note (2026-10-28):** The local-service rows in §24.1, the
> Docker/Prisma links in §24.2, and item 2 of §24.4 said to run PostgreSQL and
> Redis in Docker. Corrected: **native PostgreSQL 17.11 (port 5433) and native
> Redis 8.10.3 (port 6379)**, with **no Docker**. The hosted-provider
> research below is unchanged and remains subject to the §26 verification
> requirement. — governed by
> [`docs/adr/0003-no-docker-native-postgres-and-redis.md`](docs/adr/0003-no-docker-native-postgres-and-redis.md).

Free tiers are suitable for initial development, internal demos, and small-scale validation, but they are not equivalent to production SLAs. Limits and eligibility change; the owner must confirm the current official pricing and acceptable-use terms before creating an account or deploying customer data.

### 24.1 Recommended initial service choices

| Need | Primary starting option | Alternative | Usage / caveat |
|---|---|---|---|
| Source control and CI | GitHub + GitHub Actions | Self-hosted Git service and runner | Use CI for lint, typecheck, unit/integration tests, dependency checks, and build. Hosted minutes/storage are quota-limited. |
| Frontend hosting | Cloudflare Pages for a compatible frontend deployment, or an existing Netlify account | Vercel for personal/non-commercial prototyping where plan terms permit | Verify Next.js feature compatibility, commercial-use terms, build limits, and function/runtime restrictions. Do not assume every host supports every Next.js feature identically. |
| API / worker hosting | Existing developer machine or an owned VPS for always-on workers; free host for demos only | Render free services for testing | Free app services may sleep/restart and are unsuitable for reliable always-on queues. Render explicitly says free instances are for testing/hobby use, and its free Postgres expires after 30 days. |
| PostgreSQL | Neon Free for a small standalone database, or Supabase Free if integrated auth/storage is useful | **Native PostgreSQL 17.11 for local development** | Neon can scale to zero; Supabase free projects pause after inactivity. Check connection limits, storage, backup and retention constraints. Local development uses native PostgreSQL 17.11 on port 5433. |
| Redis / queue | **Native Redis 8.10.3 for development** | Upstash Redis Free | Confirm current command, storage, and bandwidth quotas. A queue backlog must not depend on an unverified free-tier guarantee. |
| Object storage | Cloudflare R2 | Backblaze B2 or local filesystem for development | R2's published free allowance includes storage and operation quotas with no egress fees; verify current terms and request classes. Never expose private artifacts through public buckets by default. |
| Authentication | Auth.js / OIDC integration, or Supabase Auth if using Supabase | Clerk free tier for a prototype | Choose one auth approach. Avoid maintaining multiple user directories. Check MAU, organisation, domain, and commercial-use limits. |
| Transactional email | Resend Free | SMTP/API provider with a suitable free allowance | Use only for verification, invitations, and essential alerts. Check sending/day, monthly quota, domain verification, and retention. |
| Error monitoring | Sentry Free, if its current limits fit | New Relic Free or self-hosted logs/metrics | Keep structured logs and request IDs in the application regardless of vendor. Confirm event limits and retention. |
| Uptime checks | GitHub Actions scheduled health check or a free uptime-monitoring service | Self-hosted health check | Scheduled workflow timing is not guaranteed to the minute. Avoid monitoring internal endpoints with sensitive diagnostics. |
| DNS / TLS / edge protection | Cloudflare DNS and free edge features where appropriate | Host-provided DNS/TLS | Keep origin secrets private. Configure rate limits and access rules as supported by the chosen plan. |
| EVM RPC / explorer data | Local node or chain's documented public endpoints for low-volume testing; evaluate a free developer API from a provider such as Alchemy, Infura, or Etherscan | RPC endpoint operated by the team | Provider free tiers vary by chain, request units, archive/history access, and API key rules. Use an RPC adapter and cache metadata; never hardcode a provider into the analysis engine. |
| Model training/inference | Local CPU for scikit-learn; local CPU for early PyTorch experiments | Optional notebook/cloud GPU free quotas if available | Do not make free GPU availability a product dependency. A GNN is not an MVP requirement. |
| Dependency/security scanning | GitHub Dependabot and repository security features available on the chosen plan | OSV-Scanner and other open-source tools in CI | Review licence and vulnerability findings; pin and update dependencies deliberately. |

### 24.2 Official links to verify before implementation

These links are starting points for the developer to confirm the latest quota, commercial-use terms, regional availability, and data-processing terms.

- GitHub Actions: https://github.com/features/actions
- Cloudflare Pages: https://pages.cloudflare.com/
- Cloudflare Workers: https://developers.cloudflare.com/workers/platform/pricing/
- Cloudflare R2: https://developers.cloudflare.com/r2/pricing/
- Netlify pricing: https://www.netlify.com/pricing/
- Vercel pricing: https://vercel.com/pricing
- Render free services: https://render.com/docs/free
- Neon pricing: https://neon.tech/pricing
- Supabase pricing: https://supabase.com/pricing
- Upstash pricing: https://upstash.com/pricing
- Resend pricing: https://resend.com/pricing
- Sentry pricing: https://sentry.io/pricing/
- New Relic pricing: https://newrelic.com/pricing
- Auth.js documentation: https://authjs.dev/
- Clerk pricing: https://clerk.com/pricing
- Alchemy pricing: https://www.alchemy.com/pricing
- Infura pricing: https://www.infura.io/pricing
- Etherscan API plans: https://etherscan.io/apis
- scikit-learn: https://scikit-learn.org/stable/
- PyTorch: https://pytorch.org/
- Playwright: https://playwright.dev/

**Removed on 2026-10-28** (see ADR-0001 and ADR-0003): the Docker Compose and
Prisma documentation links, because neither Docker nor Prisma is used. The
Stack table's EVM disassembler is decided, so its library links are recorded in
the ADRs rather than here.

### 24.3 Free-tier findings checked for this document

The following are examples of currently published limits, not permanent guarantees:
- Supabase Free advertises 500 MB database size, 1 GB file storage, 5 GB egress, and project pausing after one week of inactivity. Source: https://supabase.com/pricing and https://supabase.com/docs/guides/platform/billing-on-supabase
- Render's free services are positioned for testing/hobby use; its free Postgres instance has a 1 GB limit and expires after 30 days. Source: https://render.com/docs/free
- Cloudflare R2's pricing page documents a free allowance for storage and operations and no egress fees. Source: https://developers.cloudflare.com/r2/pricing/
- Upstash's free allowance and limits should be checked on its live pricing page before choosing it for a queue. Source: https://upstash.com/pricing
- Resend's free allowance should be confirmed against the live pricing page and domain-verification requirements. Source: https://resend.com/pricing
- New Relic advertises a free tier with 100 GB of data ingest per month, subject to plan terms. Source: https://newrelic.com/pricing

A third-party free-tier comparison can help discover options, but final decisions must be based on each vendor's official documentation and terms.

### 24.4 Initial recommendation: keep the MVP to a small service set

To reduce account overhead and surprise costs, begin with:
1. GitHub + GitHub Actions for source control and CI.
2. **Native PostgreSQL 17.11 (port 5433) and native Redis 8.10.3 (port 6379) for local development — no Docker, no docker-compose.yml.**
3. One hosted PostgreSQL provider for a demo environment, if needed.
4. One hosting provider for the web app.
5. One RPC/explorer provider adapter, with low-volume use and caching.
6. Local artifact storage in development, then one private object-storage bucket when remote hosting is required.
7. One email provider only when account invitations or verification are implemented.
8. Local structured logs first; add a hosted monitoring service only when the application is deployed.

Do not sign up for every alternative at once. Choose a primary provider per capability, isolate it behind an adapter where switching matters, and keep a fallback documented.

---

## 25. Environment Variables and Service Configuration

The exact names should be standardised in `.env.example`. Never commit real values.

### 25.1 Core application

```dotenv
NODE_ENV=development
APP_BASE_URL=http://localhost:3000
API_BASE_URL=http://localhost:8000
API_PORT=8000
LOG_LEVEL=debug
```

### 25.2 Database and queue

> **Correction note (2026-10-28):** The `DATABASE_URL` below already used the
> SQLAlchemy driver form, but the surrounding paragraph told the reader to
> "verify Prisma compatibility", which was a leftover from the rejected
> Node/Prisma stack. Corrected: this is a **SQLAlchemy** URL and **Prisma is
> not used**. The `QUEUE_BACKEND=rq` value is now the decided queue, not an
> option. The example host/port reflect the local native setup
> (PostgreSQL 17.11 on **5433**); the password is a placeholder and must be
> supplied through `.env`, never committed. — governed by
> [`docs/adr/0001-python-backend-over-node-prisma.md`](docs/adr/0001-python-backend-over-node-prisma.md)
> and
> [`docs/adr/0003-no-docker-native-postgres-and-redis.md`](docs/adr/0003-no-docker-native-postgres-and-redis.md).

```dotenv
DATABASE_URL=postgresql+psycopg://cyberstratum_app:[REDACTED]@127.0.0.1:5433/cyberstratum
REDIS_URL=redis://127.0.0.1:6379
QUEUE_BACKEND=rq
QUEUE_PREFIX=cyberstratum
```

Use a separate database and credentials per environment. For hosted Postgres, use the provider's recommended connection string and pooling mode; verify **SQLAlchemy** compatibility with that mode. The local development setup uses native PostgreSQL 17.11 and native Redis 8.10.3 — no Docker, no docker-compose.yml. Exact startup commands are in `docs/runbook.md`.

### 25.3 Authentication and security

```dotenv
AUTH_SECRET=replace-with-a-long-random-secret
AUTH_BASE_URL=http://localhost:3000
```

If an OIDC provider is selected, add only that provider's required issuer/client variables. Do not include unused providers' secrets.

### 25.4 Object storage (optional in local development)

```dotenv
OBJECT_STORAGE_DRIVER=local
OBJECT_STORAGE_BUCKET=
OBJECT_STORAGE_ENDPOINT=
OBJECT_STORAGE_REGION=
OBJECT_STORAGE_ACCESS_KEY_ID=
OBJECT_STORAGE_SECRET_ACCESS_KEY=
```

Use a private bucket and short-lived signed URLs for hosted artifacts. Keep the local driver usable without cloud credentials.

### 25.5 EVM RPC / explorer provider (optional per integration)

```dotenv
EVM_RPC_PROVIDER=public
EVM_RPC_URL=
EXPLORER_API_BASE_URL=
EXPLORER_API_KEY=
```

Store one credential per environment. Redact provider URLs if they contain API keys from logs and exception messages.

### 25.6 ML and scan pipeline

```dotenv
ENABLE_EXPERIMENTAL_ML=false
ML_MODEL_VERSION=
ML_MODEL_ARTIFACT_URI=
SCAN_MAX_BYTECODE_BYTES=2000000
SCAN_JOB_TIMEOUT_SECONDS=300
SANDBOX_ENABLED=false
SANDBOX_MAX_MEMORY_MB=512
SANDBOX_MAX_CPU_SECONDS=30
```

Defaults must be safe. Tune limits after corpus benchmarking. The sandbox should be disabled in development and production until isolation tests pass.

### 25.7 Email and observability (optional)

```dotenv
EMAIL_PROVIDER=disabled
EMAIL_API_KEY=
EMAIL_FROM=
ERROR_TRACKING_DSN=
OTEL_EXPORTER_OTLP_ENDPOINT=
```

Validate configuration at startup. If a provider is disabled or not configured, the product should show a clear status and continue to support core static analysis.

---

## 26. Cost-Control and Vendor Exit Plan

- Add usage dashboards or alerts for every metered external service.
- Set hard application-level limits on bytecode size, scan concurrency, retry count, report exports, and sandbox CPU/memory/time.
- Cache public chain metadata and use exponential backoff for rate-limited provider requests.
- Do not use free RPC endpoints for high-volume scanning without checking their terms.
- Keep the scanner usable with local fixtures when an external provider is unavailable.
- Back up database metadata and object artifacts independently; free-tier hosting may not include backups or durable storage.
- Do not rely on a sleeping/free host for continuous background workers.
- Store the provider name and artifact URI in configuration, not in business logic.
- Maintain export/migration scripts for PostgreSQL and object storage.
- Before moving from prototype to production, calculate expected monthly costs for database, compute, storage, egress, RPC, email, and monitoring from measured usage.
- No service may be described as “free forever” or “production-ready at no cost” without a current official source and a clear explanation of limits.

---

## 27. Technology and Service Decisions to Sign Off

> **Correction note (2026-10-28):** This section is now largely **decided**
> rather than pending. Items 3, 4, 5, 10 and the "Recommended default"
> paragraph were corrected: **native PostgreSQL 17.11 and Redis 8.10.3
> (no Docker)**, **RQ**, the **custom vendored fork-accurate opcode table**,
> and the **scikit-learn TF-IDF baseline with the GNN deferred**. The
> "Recommended default" also named Node/TypeScript and Prisma; those are
> removed. Items 1, 2, 6, 7, 8, 9, 11 and 12 remain open and still need an
> owner decision. — governed by
> [`docs/adr/0001-python-backend-over-node-prisma.md`](docs/adr/0001-python-backend-over-node-prisma.md),
> [`docs/adr/0003-no-docker-native-postgres-and-redis.md`](docs/adr/0003-no-docker-native-postgres-and-redis.md),
> [`docs/adr/0004-custom-vendored-opcode-table.md`](docs/adr/0004-custom-vendored-opcode-table.md),
> and
> [`docs/adr/0006-scikit-learn-tfidf-baseline-gnn-deferred.md`](docs/adr/0006-scikit-learn-tfidf-baseline-gnn-deferred.md).

Decisions are recorded as ADRs in `docs/adr/`. The ones already settled are
marked **Decided** below; the rest are still open.

1. Next.js hosting: Cloudflare-compatible deployment, Netlify, Vercel, or another selected host. — **Open.**
2. API and worker hosting: local/owned VPS versus demo-only free host. — **Open.**
3. PostgreSQL provider: **native PostgreSQL 17.11 locally, on port 5433; a hosted provider for staging.** — **Decided** (ADR-0003).
4. Redis provider: **native Redis 8.10.3 locally, on port 6379; hosted Redis only if needed.** — **Decided** (ADR-0003).
5. EVM disassembler library and supported fork/opcode table. — **Decided:** the custom `packages/evm_analysis` package with a vendored, fork-accurate opcode table generated from pinned `ethereum/execution-specs` v2.20.0; forks `frontier` → `prague`. `pyevmasm` rejected; `evmole` retained as a cross-validation oracle only. (ADR-0004, ADR-0005.)
6. Initial EVM chains and RPC/explorer provider. — **Open.**
7. Auth approach: Auth.js/OIDC or one managed auth provider. — **Open.**
8. Private object-storage provider. — **Open.**
9. Email and monitoring provider, if enabled. — **Open.**
10. ML baseline, dataset provenance, and whether graph ML is deferred. — **Decided:** scikit-learn TF-IDF baseline; **graph ML deferred**. (ADR-0006.)
11. Maximum acceptable monthly spend and who receives quota/billing alerts. — **Open.**
12. Data retention, artifact backup, and provider migration procedure. — **Open.**

**Recommended default:** develop locally with **native PostgreSQL 17.11 and
Redis 8.10.3 (no Docker)**, a **Python FastAPI + SQLAlchemy + Alembic + RQ**
backend, a **Next.js** frontend, the **custom vendored fork-accurate opcode
table** as the disassembler, and a **Python scikit-learn TF-IDF** baseline. Add
only one hosted provider per required capability when a remote demo is needed.
Keep the GNN, managed AI APIs, paid RPC upgrades, and campaign automation out
of the initial critical path.
