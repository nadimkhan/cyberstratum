# The discovery feed

The discovery feed is the "Watchdog" half of CyberStratum: a continuous
sweep that finds newly verified contracts across many EVM chains so they
can be analysed. It is the counterpart to the scan pipeline, not part of
it.

| | Discovery cycle | Scan |
|---|---|---|
| Reads | many chains | one contract |
| Analyses | nothing | everything |
| Writes | contracts, cursors, a run row | instructions, CFG, findings, artifacts |
| Cost | one HTTP request per chain | the full bytecode analysis |
| Failure | isolated per chain | fails the scan |

Keeping them apart matters. A sweep that touches 60 chains has a
per-chain failure rate; a scan that fails once should not take the feed
down with it.

## Running a cycle

```bash
node scripts/py.mjs --cwd . -m scripts.live_check_discovery_feed
```

That runs one real cycle against the real Blockscout routes and prints
what happened. From the API:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/discovery/runs \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"batch_size": 10}'
```

The route returns `202` with a job id. The cycle itself runs on the RQ
worker, on the `cyberstratum:discovery` queue -- a separate queue from
scans, so a slow sweep cannot delay a user's scan.

Other routes:

| Route | Purpose |
|---|---|
| `GET /api/v1/discovery/runs` | The cycle history, newest first |
| `GET /api/v1/discovery/contracts` | What the feed has found |
| `GET /api/v1/discovery/cursors` | How far each chain has been read |

## The four properties that make it safe to run unattended

**A failing chain costs that chain, not the cycle.** Base is a paid
"featured" chain on Blockscout PRO and answers `402` with the current
free key. A live cycle reports:

```
chains covered : 2
chains failed  : 1
per-chain failures
  chain 8453: Blockscout unavailable for Base (8453): the PRO API answered 402
```

The other two chains were swept normally.

**The cursor advances before the analysis.** The cursor records how far a
chain has been read. It is written and flushed *before* the contracts are
persisted, so a crash costs at most one contract rather than causing the
same contract to be fetched on every cycle forever.

**Discovery is idempotent.** A contract is unique per
`(workspace, chain, address)`. The same contract found twice is one row.
The second sighting only records a change: a newer `verified_at` means
the source may have changed and the contract is worth re-analysing, which
is reported as `contracts_updated`.

**Discovered contracts do not land in a tenant's list.** They go to the
discovery workspace (`kind = 'discovery'`), which is created on first use.
A customer promotes a contract deliberately; it never appears in somebody
else's contract list.

## Round-robin across chains

A cycle covers `batch_size` chains, not all 60. Which chains is chosen by
the cursor: the chains whose cursors were touched longest ago go first,
and chains that have never been swept go before any that have. That gives
a round-robin sweep without needing a separate rotation counter.

The chains that are never swept are the ones whose cursor is oldest -- so
nothing is starved as long as the cycle runs often enough.

## Schema

`apps/api/alembic/versions/b1e7c4a9d206_unify_discovery_schema.py`
implements the decisions in `docs/SCHEMA-RECONCILIATION.md`.

| Table | Purpose |
|---|---|
| `discovery_runs` | One row per cycle: counters, status, per-chain errors |
| `feed_cursors` | Per chain: how far it has been read |
| `proxy_template_allowlist` | The auditable replacement for Watchdog's hard-coded set |

And on the existing tables:

| Change | Why |
|---|---|
| `workspaces.kind` | Separates a tenant workspace from the discovery workspace |
| `findings.source` | `rule`, `slither` or `ml` -- one findings table, three engines |
| `contract_targets.source_object_key` | Source code is an artifact, not a `TEXT` column |
| `contract_targets.discovery_*` | The provenance of a discovered contract |
| `uq_contract_target_scope` | A contract is unique per (workspace, chain, address) |

The migration has been applied and its full `upgrade -> downgrade ->
upgrade` cycle verified against the development database.

## Measured behaviour

A live cycle over three chains (Ethereum, OP Mainnet, Base):

```
run id             : 72913eb5-c95e-421c-9e2c-db9b0aa70716
status             : partial
chains covered     : 2
chains failed      : 1
contracts found    : 100
contracts new      : 100
contracts updated  : 0

cursors
  chain      1 Chain 1                seen=50   last=0xb51a932c...ac04
  chain     10 OP Mainnet             seen=50   last=0x5d462f61...dbad
  chain   8453 Base                   seen=0    last=None
```

50 contracts per chain is the per-instance page cap
(`docs/BLOCKSCOUT-ROUTES.md`).

## What is not done yet

- The feed does not queue scans for the contracts it finds. Promotion from
  the discovery workspace into a tenant's workspace, and the scan that
  follows it, are not implemented.
- There is no scheduler. The cycle is triggered by hand or by the API;
  nothing runs it on a timer yet.
- There is no pagination. A cycle reads one page per chain.
- The feed does not fetch source code. It records where the source lives
  (`source_uri`) and the verification state; fetching and storing the
  source as an artifact is the next step.
