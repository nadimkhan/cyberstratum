# CyberStratum

**EVM security analysis and audit, in one platform.**

CyberStratum ingests EVM bytecode, disassembles it correctly against a pinned
fork-aware opcode table, derives control-flow and feature signals, runs
deterministic detectors, and produces **candidate findings with evidence a
human can inspect** — each one mapped to byte offsets and basic blocks, each one
carrying its limitations, each one labelled experimental if a model produced
it.

It is a security researcher's tool. It is not a guarantee of anything.

---

## Two engines, one platform

| | **Analysis** — deployed bytecode | **Audit** — verified source |
|---|---|---|
| Engine | CyberStratum's own fork-aware EVM engine | Slither, run as an external process |
| Needs source? | No — works on unverified contracts | Yes |
| Finds | What is *actually deployed*: compiler quirks, proxy runtime structure, `delegatecall` chains, unreachable code, fork-specific opcodes | Reentrancy across calls, precise `file:line` locations, inheritance and composition problems |
| Output | Severity **and** confidence, plus reproducible artifacts | Severity, detector id, source location |

They fail in opposite directions, which is why both are here. The two views are
also comparable: a contract whose source analyses clean but whose deployed
runtime tells a different story is itself worth a human's attention.

> **Licence note.** Slither is AGPL-3.0. It runs here as an *unmodified,
> out-of-process* executable whose JSON output we read — we never import it, and
> our own source stays clean. See
> [ADR-0013](docs/adr/0013-licensing-fastapi-mit-and-slither-agpl.md). The
> bytecode engine is our own code and carries no such restriction; a deployment
> can run the product with the Slither lane disabled.

## Continuous multi-chain discovery

Contracts are discovered across 59 EVM mainnets through Blockscout, analysed,
and stored with their findings. The discovery feed advances a **per-chain
cursor before analysis runs**, so a crash or timeout never causes re-fetching,
and one chain failing degrades only that chain.

Two access routes, chosen per chain and recorded so the choice is never
re-litigated:

- **Per-chain Blockscout instance** — no API key, fast, richer payload. Used
  where the instance responds.
- **Blockscout PRO API** — unified, metered in credits. Used for the chains
  whose instance is blocked or absent.

`filter=verified` is never used: measured on 2026-10-28, it costs **44-79
seconds per call** against **0.4 seconds** for the same query without it.

---

## What it does

- **Fork-aware disassembly.** `PUSH1`–`PUSH32` immediates are consumed as
  data, never decoded as opcodes. Truncated pushes, unknown opcodes, and the
  designated invalid opcode `0xFE` are *reported*, not silently absorbed.
- **Solidity metadata handling.** The CBOR trailer is detected with a
  conservative reader, is never decoded as instructions, and the original bytes
  are never modified.
- **A real control-flow graph.** Basic blocks, directed edges with explicit
  confidence (`resolved` / `inferred` / `unresolved`), cycle detection, and
  reachability analysis. The graph is **never assumed to be a DAG** — loops are
  normal in Solidity.
- **Static jump resolution by abstract interpretation.** A forward dataflow
  fixpoint plus an abstract stack simulation resolves the destinations that
  `solc` shuffles around before branching. Where the answer is genuinely
  unknown, it stays unknown: **the resolver never guesses.**
- **Deterministic feature extraction.** Opcode frequencies, n-grams, block and
  edge metrics, call and storage locations, call-then-storage-write ordering,
  stack-depth signals. The same bytecode and fork always produce the same
  feature vector.
- **Six baseline detectors.** Call-before-state-write, `DELEGATECALL` usage,
  `SELFDESTRUCT`, `tx.origin` dependence, unresolved jumps, and stack
  underflow. The reentrancy rule is explicitly a **heuristic** — its title
  reads "Potential reentrancy pattern — manual validation required", and every
  finding carries its own `limitations` field.
- **Reproducibility by construction.** Every scan can be reproduced from four
  stored facts: the input hash, the opcode-table version, the EVM fork, and
  the tool versions.
- **Cross-validated against an independent engine.** The tokenizer is checked
  instruction-by-instruction against `evmole` on real deployed mainnet
  bytecode.

## What it explicitly does **not** do

Being explicit here is a product decision, not an oversight.

- **It does not promise money.** No airdrop eligibility, no token allocation,
  no bounty income, no reward estimates — and no metrics that could be read as
  projections. See [ADR-0008](docs/adr/0008-no-airdrop-bounty-or-campaign-promises.md).
- **It does not track campaigns.** No campaign ledger, no wallet labels, no
  task automation, no anti-Sybil tooling. See
  [ADR-0007](docs/adr/0007-campaign-tracking-out-of-mvp-scope.md).
- **It does not exploit anything.** It never automatically executes against
  third-party live contracts, never moves assets, never signs mainnet
  transactions, and never uses private keys. Dynamic execution, when it exists,
  is confined to an isolated local environment behind a human approval gate.
- **It does not connect a wallet to scan.** Analysis is read-only and needs no
  wallet, no signature, and no RPC credential to run on pasted bytecode.
- **It does not replace an auditor.** Every output is a *candidate*. A finding
  is not "confirmed" because a classifier score crossed a threshold. The tool
  produces evidence; a human decides.
- **It does not claim ML replaces analysis.** The ML baseline is a
  scikit-learn TF-IDF model over opcode n-grams — a prioritisation signal. The
  graph neural network is **deferred**, not scheduled.
- **It does not use Docker.** Local infrastructure is native PostgreSQL 17.11
  and Redis 8.10.3.

---

## Architecture

```mermaid
graph TB
    subgraph client["Browser"]
        WEB["Next.js 15 App Router<br/>apps/web · React 19 · Tailwind 4<br/>6 pages"]
    end

    subgraph api["API process · Python 3.12+"]
        FASTAPI["FastAPI + Pydantic v2<br/>apps/api/app/main.py"]
        AUTH["API-key auth → Principal<br/>core/security.py"]
        ORM["SQLAlchemy 2 ORM · 15 tables<br/>Alembic migrations"]
    end

    subgraph queue["Async"]
        REDIS[("Redis 8.10.3<br/>RQ queues")]
        WORKER["RQ worker<br/>apps/api/app/worker.py"]
        PIPE["services/pipeline.py<br/>fetch → disasm → CFG → features"]
        RULES["services/rules.py<br/>6 baseline detectors"]
    end

    subgraph engine["EVM analysis engine · pure Python"]
        direction LR
        OPC["opcodes.py<br/>vendored fork table"] --> DIS["disassembler.py<br/>tokenizer"]
        META["metadata.py<br/>CBOR trailer"] --> DIS
        DIS --> CFG["cfg.py<br/>blocks + graph"]
        CFG --> RES["resolver.py + stack.py<br/>abstract interpretation"]
        CFG --> FEAT["features.py<br/>deterministic features"]
    end

    subgraph mlpkg["ML baseline · offline package"]
        TOKEN["evm_ml/tokenize.py<br/>opcode n-grams"]
        MODEL["evm_ml/model.py<br/>SklearnTfidfAdapter"]
    end

    subgraph store["Persistence"]
        PG[("PostgreSQL 17.11<br/>port 5433")]
        FILES[("Local artifact store<br/>var/artifacts")]
    end

    WEB -->|HTTP /api/v1| FASTAPI
    FASTAPI --> AUTH
    FASTAPI --> ORM
    ORM --> PG
    FASTAPI --> REDIS
    REDIS --> WORKER
    WORKER --> PIPE
    PIPE --> RULES
    PIPE --> ENGINE
    PIPE --> PG
    PIPE --> FILES
    FEAT -.-> TOKEN
    TOKEN -.-> MODEL

    style engine fill:#1a2a1a,stroke:#B7F34A,color:#E8F0EE
    style store fill:#182122,stroke:#2A3938,color:#E8F0EE
```

The scanner pipeline, end to end:

```text
bytecode (pasted or fetched by address)
  → validate (hex, size, chain, address)
  → hash the original bytecode
  → disassemble against the target fork's opcode table
  → detect the Solidity metadata trailer
  → basic blocks + control-flow graph
  → abstract-stack jump resolution (resolved / inferred / unresolved)
  → deterministic feature extraction
  → 6 baseline detectors            [implemented]
  → normalise → candidate findings with evidence, severity, confidence, limits
  → optional ML scoring              [package built; not wired into the pipeline]
  → human triage → reviewer-approved report   [report builder not built]
```

The **current implementation status of every stage** is documented in
[`docs/architecture.md`](docs/architecture.md). That document is explicit about
what is built and what is not.

---

## Repository layout

```text
cyberstratum/
├── apps/
│   ├── api/                       # Python FastAPI backend
│   │   ├── app/
│   │   │   ├── main.py            # create_app() — CORS, middleware, routers
│   │   │   ├── worker.py          # RQ worker + enqueue_scan()
│   │   │   ├── core/              # config, logging, security, errors
│   │   │   ├── db/                # SQLAlchemy base, enums, session, models
│   │   │   ├── api/               # health, scans, findings routers
│   │   │   ├── schemas/           # Pydantic request/response models
│   │   │   ├── services/          # pipeline, rules, bytecode, storage
│   │   │   └── queue/             # Redis + RQ connection helper
│   │   └── alembic/               # migrations (2 revisions)
│   └── web/                       # Next.js App Router frontend
│       ├── app/                   # 6 pages (App Router)
│       └── src/
│           ├── components/        # 9 UI primitives
│           └── lib/               # typed API client + domain types
├── packages/
│   ├── evm_analysis/              # the EVM analysis engine (pure Python)
│   │   ├── evm_analysis/
│   │   │   ├── opcodes.py         # fork-aware opcode table loader
│   │   │   ├── disassembler.py    # instruction tokenizer
│   │   │   ├── metadata.py        # Solidity CBOR trailer detection
│   │   │   ├── cfg.py             # basic blocks + control-flow graph
│   │   │   ├── stack.py           # abstract stack simulation
│   │   │   ├── resolver.py        # jump-target resolution
│   │   │   └── features.py        # deterministic feature extraction
│   │   └── data/opcodes.json      # vendored, generated, committed table
│   └── ml_baseline/               # scikit-learn TF-IDF baseline (offline)
│       └── evm_ml/                # tokenize, dataset, features, model, evaluate
├── scripts/
│   ├── generate_opcodes.mjs       # regenerate the opcode table (Node)
│   ├── crosscheck_evmole.py       # independent-oracle cross-check
│   ├── validate_real_bytecode.py  # real-bytecode validation
│   └── build_fixture_dataset.py   # build the smoke JSONL fixture
├── tests/
│   ├── unit/                      # 8 modules — engine + ML baseline
│   └── api/                       # 4 modules — scans, findings, worker, health
├── docs/
│   ├── adr/                       # architecture decision records
│   ├── architecture.md            # as-built architecture
│   ├── product-requirements.md    # distilled requirements + traceability
│   └── runbook.md                 # local development runbook
├── workers/                       # reserved for a sandbox runner (empty)
├── .env.example
├── package.json
└── pyproject.toml
```

---

## Prerequisites

| Requirement | Version | Needed for |
|---|---|---|
| Python | 3.12+ | API, worker, analysis engine |
| Node.js | 20+ | Regenerating the opcode table only |
| `uv` | recent | Python package management |
| PostgreSQL | **17.11** | Metadata, jobs, findings, audit log |
| Redis | **8.10.3** | RQ job queue |

No Docker. No paid services. No cloud account is required to run the project.

---

## Setup

```bash
cd /e/projects/cyberstratum

# 1. Python environment
uv venv --python 3.12
uv pip install -e ".[dev]"
uv pip install -e packages/evm_analysis
uv pip install -e packages/ml_baseline     # ML baseline package
uv pip install "evmole==0.9.4"             # validation oracle only

# 2. Node dependencies (opcode-table generator, web app)
npm install

# 3. Environment file
cp .env.example .env
```

Then set a real database password and auth secret **in `.env` only** — never in
a tracked file:

```dotenv
DATABASE_URL=postgresql+psycopg://cyberstratum_app:[REDACTED]@127.0.0.1:5433/cyberstratum
AUTH_SECRET=[REDACTED]
```

`.env.example` ships `CHANGE_ME` placeholders on purpose. Leave them there.

`npm run dev` (see below) starts PostgreSQL and Redis for you, so the manual
steps are only needed for first-time initialisation or for recovering a
cluster that was stopped by hand. First-time cluster creation, role creation,
and database creation are in [`docs/runbook.md`](docs/runbook.md) §3.4–§3.5.

The services themselves live at:

| Service | Location | Port |
|---|---|---|
| PostgreSQL 17.11 | `E:/tools/pg17/pgsql/bin`, data in `E:/data/cyberstratum/pgdata` | 5433 |
| Redis 8.10.3 | `E:/tools/redis8/Redis-8.10.3-Windows-x64-msys2` | 6379 |

---

## Running things

### One command

```bash
cd /e/projects/cyberstratum
npm run dev
```

That is the whole thing. It starts, in order:

1. **PostgreSQL** on `127.0.0.1:5433` (the isolated cluster, never the
   PostgreSQL 17 that already occupies port 5432 on this machine)
2. **Redis** on `127.0.0.1:6379`
3. **the API** on `http://127.0.0.1:8000`
4. **the RQ worker**
5. **the web UI** on `http://127.0.0.1:3100`

It also runs `alembic upgrade head` first, so the database schema is always
current. Services that are already running are left alone, so the command is
safe to re-run.

```
CyberStratum is up.
  web UI      http://127.0.0.1:3100
  API         http://127.0.0.1:8000
  API docs    http://127.0.0.1:8000/docs
  health      http://127.0.0.1:8000/api/health
  PostgreSQL  127.0.0.1:5433     Redis  127.0.0.1:6379
```

To stop it again:

```bash
npm run stop
```

`npm run stop` is the reliable way to stop the stack. It stops the
application processes, the worker, Redis and PostgreSQL, and removes the
stale `postmaster.pid` that a hard kill leaves behind. `Ctrl+C` also asks it
to stop, but npm sits between the terminal and the script, so `npm run stop`
is the one to reach for.

The running services are owned by a detached supervisor process, and
everything the stack logs goes to `.dev-logs/dev.log`:

```bash
npm run logs          # tail the development log
```

`npm run dev` also checks that the RQ worker actually registered. The
worker has no port of its own, so a stack whose worker failed to start
would otherwise look healthy while never processing a scan. The usual
cause is a worker of the same name that is still running, and the command
says so instead of reporting success.

Useful flags:

| Flag | Effect |
|---|---|
| `npm run dev -- --no-infra` | do not start PostgreSQL or Redis |
| `npm run dev -- --no-migrate` | do not run the migrations |
| `npm run dev -- --prod` | serve the web UI from the production build |
| `npm run dev -- --api-port 9000` | use a different API port |
| `npm run dev -- --web-port 4000` | use a different web UI port |

### Everything else

```bash
# Tests (169 Python tests + 57 Vitest tests)
npm test              # web tests, then python tests
npm run test:py       # python tests only
npm run test:web      # web tests only

# Lint and type check
npm run lint          # ruff
npm run typecheck     # mypy, then tsc

# API
npm run api           # uvicorn on http://127.0.0.1:8000

# RQ worker
npm run worker        # the RQ worker (python -m app.worker)

# Web app
npm run dev:web       # next dev
npm run build:web     # next build
npm run start:web     # next start

# Database migrations
npm run migrate
```

Full setup, including role and database creation, is in
[`docs/runbook.md`](docs/runbook.md).

### Use the engine directly

The analysis engine is usable today, without the API:

```python
from evm_analysis import build_cfg, disassemble, extract_features, load_fork

code = bytes.fromhex("6080604052...")
table = load_fork("cancun")
dis = disassemble(code, table)
cfg = build_cfg(dis)
feats = extract_features(dis, cfg, ngram_size=3)

print(feats.as_vector())
print(cfg.unresolved_edges)
print(dis.warnings)
```

### Regenerate the opcode table

```bash
npm run generate:opcodes
.venv/Scripts/python.exe -m pytest -q
```

The generator pins `ethereum/execution-specs` at tag **v2.20.0**, merges stack
effects from `evm-opcodes` and `@ethereumjs/evm`, and **refuses to emit a
table** if the sources disagree, if a fork loses an opcode relative to its
predecessor, or if any known opcode lacks a stack effect. The result is a
committed, diffable artifact at `packages/evm_analysis/data/opcodes.json`.

### Cross-validate against the independent oracle

```bash
.venv/Scripts/python.exe scripts/crosscheck_evmole.py
.venv/Scripts/python.exe scripts/validate_real_bytecode.py
```

Both need network access and are manual tools, not CI tests.

---

## Status

**Honest statement of what exists as of 2026-10-28.**

### Working

| Component | Notes |
|---|---|
| **EVM analysis engine** (`packages/evm_analysis`) | Opcode table loader, tokenizer, CBOR metadata detection, basic blocks + CFG, abstract-stack jump resolver, deterministic feature extraction. Complete and unit-tested. |
| **Vendored fork-aware opcode table** | 14 forks, `frontier` → `prague` (129 → 148 opcodes). Generated from pinned sources, committed, fail-loud validation. |
| **Jump resolver, cross-validated** | 31 504 instructions of 7 mainnet contracts cross-checked against `evmole`: 0 instruction mismatches, identical reachable-block counts, 0 wrong destinations, 89.2 % of static jumps agreed. See [ADR-0011](docs/adr/0011-static-jump-resolution.md). |
| **FastAPI backend** (`apps/api/app`) | `main.py` app factory, three routers (health, scans, findings), Pydantic schemas, service layer, API-key auth, structured logging, error envelope. |
| **RQ worker** (`apps/api/app/worker.py`) | `enqueue_scan()` + `process_scan_job()`. Drives fetch → disassemble → CFG → features → detectors and writes results to PostgreSQL. |
| **6 baseline detectors** (`apps/api/app/services/rules.py`) | call-before-state-write, delegatecall, selfdestruct, tx.origin, unresolved jumps, stack underflow. Severity and confidence are separate fields. |
| **ORM + migrations** | 15 tables, Alembic environment with 2 revisions (initial schema + `inline_bytecode`). |
| **ML baseline package** (`packages/ml_baseline/evm_ml`) | TF-IDF tokenizer, dataset with family-level splits, `SklearnTfidfAdapter`, evaluation, manifest, model card. Offline; **not** wired into the scan pipeline. |
| **Web app** (`apps/web`) | Next.js 15 App Router, 6 pages + 1 server route, typed API client, 9 UI primitives, 57 Vitest tests in 7 suites. |
| **Tests** | 169 Python tests across 12 modules, all passing. Plus 57 Vitest tests in 7 suites. |
| **Local infrastructure** | PostgreSQL 17.11 on 5433 and Redis 8.10.3 on 6379 are installed and working. |

### Known gaps

These are real and are not hidden. Three gaps that were listed here earlier
are now closed: the web app authenticates (server-side `X-API-Key`), the
backend serves `GET /api/v1/scans/{id}/findings`, and the frontend health
check calls `/api/health`, which the backend serves.

| Gap | Detail |
|---|---|
| **No finding review workflow** | `findings.status` is set to `new` at creation and never changes. There is no `PATCH` route, so a finding cannot be triaged, confirmed, or dismissed. |
| **Roles exist in the schema but are not enforced** | `WorkspaceRole` and `WorkspaceMember` are defined, but no route checks a role — every authenticated caller can do everything a stored key allows. The reviewer-approval gate in §3.2 and §11.10 is not implemented. |
| **The audit log is never written** | The `audit_events` table exists, but nothing inserts into it, so there is no record of who looked at or changed a target. |
| **No report builder** | The `reports` table, the report generator, and the reviewer-approval gate do not exist. Findings are read from the API instead. |
| **ML is not in the pipeline** | `packages/ml_baseline` is standalone. `ENABLE_EXPERIMENTAL_ML` defaults to `false` and no scan attaches an ML score. |
| **~11 % of static jumps stay unresolved** | A value pushed in one block and consumed several blocks later, across a shared utility block, cannot be proven by the merged-stack analysis. Such jumps are reported as unresolved rather than guessed, so the "unresolved dynamic jump" detector over-reports by roughly that margin. |
| **No sandbox runner** | `workers/sandbox_runner/` does not exist and `SANDBOX_ENABLED=false`. |
| **No browser-level end-to-end tests** | The API pipeline has end-to-end coverage in `tests/e2e/`, but there is no Playwright suite driving the UI. The UI is verified by Vitest unit tests plus a manual pass over the live stack. |

### Deliberately out of scope

- **Campaign tracking** — [ADR-0007](docs/adr/0007-campaign-tracking-out-of-mvp-scope.md)
- **Any airdrop, bounty, or campaign-reward promise or metric** — [ADR-0008](docs/adr/0008-no-airdrop-bounty-or-campaign-promises.md)

### About the ML baseline and the GNN

The ML baseline is **scikit-learn TF-IDF over opcode n-grams** plus the
deterministic numeric features. It is **built as a standalone package** at
`packages/ml_baseline/evm_ml` — tokenizer, dataset with family-level splits
that prevent leakage, the adapter, evaluation, and the model manifest — but it
is **not yet wired into the scan pipeline**. A scan today produces detector
findings only; no ML score is attached to any finding.

The **graph neural network is deferred**, not planned-and-scheduled. §6.4 of
the design document describes it as "a design sketch, not a complete model
specification" and lists nine things engineering must define before one
exists. There is no labelled dataset, and no compute budget that does not
depend on an unverified free tier. The four conditions that would reopen the
decision are in
[ADR-0006](docs/adr/0006-scikit-learn-tfidf-baseline-gnn-deferred.md).

Until the §13.3 release gate is satisfied, every model-based result is
labelled **experimental**, and no model-based result may be called a confirmed
finding.

---

## Documentation

| Document | Contents |
|---|---|
| [`CyberStratum_Product_Technical_Design_Documentation.md`](CyberStratum_Product_Technical_Design_Documentation.md) | The product and technical specification, with dated correction notes pointing at the governing ADRs |
| [`docs/adr/`](docs/adr/README.md) | Architecture decision records — the authoritative log of technical decisions |
| [`docs/architecture.md`](docs/architecture.md) | As-built architecture, data flow, ER diagram, artifact/reproducibility model, fork-aware opcode pipeline |
| [`docs/product-requirements.md`](docs/product-requirements.md) | Personas, functional and non-functional requirements, severity taxonomy, out-of-scope list, traceability to the design document |
| [`docs/runbook.md`](docs/runbook.md) | Exact local setup and run commands, migrations, tests, opcode regeneration, troubleshooting table |
| [`docs/INTEGRATION-PLAN.md`](docs/INTEGRATION-PLAN.md) | Merging Watchdog in: what ports from where, the measured Blockscout constraints, the phase list |
| [`docs/SCHEMA-RECONCILIATION.md`](docs/SCHEMA-RECONCILIATION.md) | How the two data models become one, and the seven decisions that forces |

### The stack contradiction, and how it was resolved

The design document specified both a Python/FastAPI/SQLAlchemy/Alembic backend
(§23.1, §23.4) **and** a Node/TypeScript/Prisma/BullMQ backend (§8.1, §8.2,
§23.3, §25.2, §27, Appendix B). §23.4 explicitly said "Do not use Prisma in the
Python backend" and "Do not use BullMQ from Python".

The resolution: **Python backend (FastAPI + SQLAlchemy + Alembic + RQ) with a
Next.js frontend.** The Node/Prisma/BullMQ material was stale and has been
corrected in place, with a dated correction note on each edited section
pointing at the governing ADR. The full reasoning is in
[ADR-0001](docs/adr/0001-python-backend-over-node-prisma.md).

---

## Design decisions

| ADR | Decision |
|---|---|
| [0001](docs/adr/0001-python-backend-over-node-prisma.md) | Python backend over Node/TypeScript + Prisma; RQ over BullMQ |
| [0002](docs/adr/0002-nextjs-frontend.md) | Next.js frontend, a pure HTTP client of the Python API |
| [0003](docs/adr/0003-no-docker-native-postgres-and-redis.md) | No Docker; native local PostgreSQL 17.11 and Redis 8.10.3 |
| [0004](docs/adr/0004-custom-vendored-opcode-table.md) | Custom vendored fork-accurate opcode table from execution-specs v2.20.0 |
| [0005](docs/adr/0005-evmole-as-cross-validation-oracle.md) | `evmole` retained as an independent oracle only |
| [0006](docs/adr/0006-scikit-learn-tfidf-baseline-gnn-deferred.md) | scikit-learn TF-IDF baseline; GNN deferred |
| [0007](docs/adr/0007-campaign-tracking-out-of-mvp-scope.md) | Campaign tracking out of MVP scope |
| [0008](docs/adr/0008-no-airdrop-bounty-or-campaign-promises.md) | No airdrop, bounty, or campaign promises |
| [0009](docs/adr/0009-sourcify-bytecode-acquisition.md) | Sourcify as the bytecode source; RPC and user-supplied bytes |
| [0010](docs/adr/0010-server-only-frontend-api-key.md) | The frontend API key is server-only |

---

## License

MIT (see `package.json`).

## Security

Found a vulnerability in a contract you are authorised to analyse? Report it to
the contract's own security contact. Do not use this tool to exploit live
systems — dynamic execution is confined to an isolated local environment and
requires explicit human approval.
