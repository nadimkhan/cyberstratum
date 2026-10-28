# Schema Reconciliation — Watchdog into CyberStratum

**Status:** proposed, part of [ADR-0012](adr/0012-merge-watchdog-into-cyberstratum.md).
Phase P3 of the [integration plan](INTEGRATION-PLAN.md).

## The two schemas side by side

**Watchdog** (reconstructed, then implemented — `E:/projects/watchdog/alembic/versions/001_initial.py`):

| Table | Columns |
|---|---|
| `contracts` | id, chain, address, name, verified_at, source_code, compiler_version, bytecode, keccak256_bytecode, first_seen_at — UNIQUE(chain, address) |
| `slither_findings` | id, contract_id, detector, severity, confidence, description |
| `ml_assessments` | contract_id (PK), severity, vectors TEXT[], model_version, scored_at |
| `cursors` | chain (PK), last_verified_at, updated_at |
| `run_log` | id, started_at, finished_at, fetched, saved_new, findings, error_tail, status |

**CyberStratum** (15 tables): `users`, `api_keys`, `workspaces`, `workspace_members`,
`chains`, `contract_targets`, `audit_events`, `scans`, `scan_jobs`, `scan_artifacts`,
`instructions`, `basic_blocks`, `cfg_edges`, `features`, `findings`.

## Mapping

| Watchdog | CyberStratum | Action |
|---|---|---|
| `contracts` | `contract_targets` | **Extend.** Keep CyberStratum's model; add the discovery columns. |
| `slither_findings` | `findings` | **Map onto.** `detector` → `detector_id`. |
| `ml_assessments` | `findings` | **Flatten.** One row per risk vector, not one row per contract. |
| `cursors` | `feed_cursors` (new) | **New table.** |
| `run_log` | `scan_runs` (new) | **New table.** A discovery cycle is not a scan. |
| — | `chains` | **Already compatible.** The 59-chain registry populates it directly. |

## The decisions this forces

### 1. A discovery cycle is not a scan

Watchdog's `run_log` records a *cycle* — "110 fetched, 30 saved new, 104 findings".
CyberStratum's `scans` records *one contract analysis*. Conflating them would make
`scans` mean two different things, so `scan_runs` is a separate table:

```
scan_runs
  id, started_at, finished_at, status, chains_attempted, chains_succeeded,
  chains_failed, contracts_fetched, contracts_new, scans_enqueued,
  findings_total, error_tail
```

`run_log` maps onto it one-for-one. The per-chain detail lives in `feed_cursors`
and in the individual `scans` rows the cycle enqueued.

### 2. `contract_targets` gains the discovery metadata

CyberStratum's `contract_targets` already models "a contract to be analysed" and
already has the columns a discovered contract needs. It is missing only the
provenance that discovery supplies:

| New column | Type | Source |
|---|---|---|
| `contract_name` | `String(200)` | Watchdog's `contracts.name` → also feeds `label` |
| `verified_at` | timestamptz | Watchdog's `contracts.verified_at` — the cursor comparison key |
| `compiler_version` | `String(64)` | e.g. `0.8.24+commit.e11b9ed9` |
| `optimization_used` | `Boolean` | |
| `source_object_key` | `String(512)` | **not** a TEXT column — see §3 |
| `discovery_source` | `String(32)` | `blockscout` \| `manual` \| `imported` |

`bytecode_hash` already exists on `contract_targets` and is the natural home for
Watchdog's `keccak256_bytecode`. That gives clone detection for free, which
`DATA-MODEL.md` identified as the single biggest available speedup, since Slither
dominates runtime and many "new" contracts are redeploys of identical bytecode.

`chain` in Watchdog is a slug string (`"arbitrum"`); CyberStratum's is a UUID
foreign key to `chains`. The slug goes away and the `chains` table becomes the
single source of truth for chain identity. `chains` already has `chain_id`,
`name`, `enabled` and `environment` — the registry populates it directly.

### 3. Source code goes to the artifact store, not a column

Watchdog stores `source_code` as a TEXT column and its plan adds a daily job to
truncate it, because the table grows ~70k contracts a month. CyberStratum already
has a content-addressed artifact store (`scan_artifacts` + `storage.put_bytes`).

**So source code becomes an artifact**, referenced by `source_object_key`, and the
truncation job disappears. The storage cost is the same; the daily destructive
maintenance job is not. This is a case where the merged product is strictly better
than either project alone.

### 4. Findings unify, with `source` as the discriminator

Both engines write into `findings`. The discriminator is the existing `category`
column, extended with a `source` value, so a contract's risk is the union of both
views while each finding keeps its own provenance.

| | Slither finding | ML vector | EVM rule finding |
|---|---|---|---|
| `detector_id` | Slither detector id, e.g. `reentrancy-eth` | `ml.vector.<name>` | e.g. `delegatecall` |
| `detector_version` | Slither version | model version | ruleset version |
| `category` | `audit` | `ml` | `analysis` |
| `title` | detector id, humanised | `Risk vector: <name>` | rule title |
| `severity` | `high`/`medium`/`low`/`info` | verdict severity | rule severity |
| `confidence` | **not numeric** — see below | model score | rule confidence |
| `evidence_json` | detector description, source location, code snippet | `{"vectors": [...]}` | CFG evidence |
| `source_uri` | source location `file:line` | — | artifact reference |

**Severity mapping** is clean: Slither's `High`/`Medium`/`Low`/`Informational` maps
onto CyberStratum's `high`/`medium`/`low`/`info` enum one-to-one.

**Confidence is the subtle one.** CyberStratum's `findings.confidence` is a
`Float` in `[0,1]`; Slither emits a textual confidence (`High`/`Medium`/`Low`).
Two options:

1. Map Slither's text onto a fixed numeric scale (High=0.9, Medium=0.6, Low=0.3).
   Simple, and comparable across engines.
2. Leave it and put the text in `evidence_json`.

**Decision: option 1**, with the original text preserved in `evidence_json` so
nothing is lost. A single numeric confidence is what makes "the highest-confidence
finding across both engines" a queryable thing, which is the point of having one
findings table.

### 5. ML assessments are flattened, and the conflation is fixed

Watchdog's `ml_assessments` is one row per contract holding a `severity` and a
list of `vectors`. `RECOVERY-NOTES.md` and `DATA-MODEL.md` both flag the same
defect: the original run conflated *"this bytecode contains a risky pattern"*
(a feature) with *"this contract is exploitable"* (a verdict), and the result was
a storm of false positives on standard proxy templates.

Flattening fixes it structurally. Each vector becomes its own finding:

- `category='ml'`, `title='Risk vector: selfdestruct'`
- `severity` = the **verdict**, which is only set when there is real evidence
- `evidence_json` = `{"vectors": ["selfdestruct", "access_control"]}` plus the
  pattern locations that triggered it

A vector with no verdict is `severity=low` with `confidence` reflecting the
pattern match — a *feature*, honestly labelled. A verdict is `severity=high` with
`confidence` reflecting the evidence. The two can no longer be conflated because
they are in different columns.

### 6. The proxy-template allowlist is a first-class table, not a helper function

Watchdog's `_is_proxy_contract` is a helper that suppresses Slither noise on
standard proxy templates. The recovered runs show it was the difference between
usable signal and noise: `BeaconProxy` alone produced 28 findings, and proxy
templates (`ERC1967Proxy`, `TransparentUpgradeableProxy`, `SafeProxy`, `Diamond`,
`UserWallet`) fired on every boilerplate vector.

That is a **detection-suppression policy**, and it belongs in the database where
it can be audited, versioned and overridden — not buried in a function. A new
table:

```
suppression_rules
  id, pattern_kind, pattern_value, detector_id, reason, enabled, created_at
```

with `pattern_kind` in `proxy_template` | `known_template` | `boilerplate`.
A finding that matches a suppression rule is still **stored** — it is marked
suppressed with the rule's id in `evidence_json`, so the suppression is visible
and reversible rather than a silent omission. Deleting the rule brings the
findings back.

This is the mechanism that prevents the original's documented failure mode from
reappearing, and it does so without losing data.

### 7. Workspace scoping

Watchdog's schema has no workspace — it is single-tenant by construction.
CyberStratum's is workspace-scoped throughout, and the commercial multi-tenant
SaaS decision makes that mandatory.

**Decision:** the discovery feed writes into a single, designated **discovery
workspace**, per chain registry. Discovered contracts are not visible to a
customer's workspace until a human promotes one. The promotion path is the
`contract_targets.created_by` column and the existing API.

This keeps the feed from filling every tenant's contract list with contracts
nobody asked for, and it gives the product a natural "here is what we found on
your chain" flow later.

## New tables introduced

| Table | Purpose |
|---|---|
| `feed_cursors` | Per-chain discovery position. Advanced **before** analysis, so a crash never re-fetches. |
| `scan_runs` | One discovery cycle: what was attempted, what succeeded, what was skipped. |
| `suppression_rules` | Auditable, versioned detection-suppression policy. |

## Column changes

| Table | Change |
|---|---|
| `contract_targets` | + `contract_name`, `verified_at`, `compiler_version`, `optimization_used`, `source_object_key`, `discovery_source` |
| `findings` | + `source` discriminator column; `category` gains `audit` / `ml` / `analysis` |
| `chains` | seeded from the 59-chain registry; `rpc_config_ref` points at the Blockscout route for that chain |

## Migration order

1. `0012_add_contract_discovery_columns` — additive, no data movement.
2. `0013_create_feed_cursors_and_scan_runs`.
3. `0014_create_suppression_rules`.
4. `0015_add_finding_source` — backfill `source='analysis'` for existing rows,
   then seed the proxy-template suppression rules.

Every step is additive. Nothing in the existing CyberStratum schema is dropped or
rewritten, so the migration can be applied to a live database without a rewrite
window.
