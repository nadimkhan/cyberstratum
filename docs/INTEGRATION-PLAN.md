# Watchdog -> CyberStratum Integration Plan

**Status:** proposed, awaiting sign-off. See [ADR-0012](adr/0012-merge-watchdog-into-cyberstratum.md).

## 1. What is being ported, and from where

| Asset | From | To | Notes |
|---|---|---|---|
| 59-chain registry | `watchdog/chains.py` | `packages/evm_analysis` -> new `packages/chains` | Re-derive from the Blockscout `chainscout` registry JSON so it can be refreshed, not hand-maintained |
| Blockscout client | `watchdog/fetcher.py` | `apps/api/app/services/blockscout.py` | Rewrite: the current query shape is 44-79 s per chain (measured) |
| Slither runner | `watchdog/analyzer.py` | `apps/api/app/services/slither.py` | Port the solc-version detection, proxy detection and timeout handling as-is |
| Proxy-template allowlist | `watchdog/analyzer.py` `_is_proxy_contract` | `apps/api/app/services/proxy_templates.py` | First-class, because it was the documented cause of the original false-positive storm |
| Cursor semantics | `docs/RECOVERY-NOTES.md` | `apps/api/app/services/discovery.py` | Cursor advances **before** analysis; per-chain isolation |
| Discovery pipeline | `.hermes/plans/2026-10-12_010000-continuous-scanning-pipeline.md` | `apps/api/app/services/discovery.py` + worker queue | Round-robin batches, rate-limit backoff, re-scan on re-verification |
| Google OAuth + session | `watchdog/api/auth.py` | `apps/api/app/api/auth.py` | Needed for a multi-user hosted product; CyberStratum's API keys stay for machine clients |
| Frontend shell | `watchdog/frontend` | `apps/web` | Merge the marketing/auth route groups into CyberStratum's App Router app |
| Chain + findings views | `watchdog/frontend/app/(auth)/chains` | `apps/web/app/chains` | Extend with per-chain coverage and scanner staleness |

## 2. Measured constraints (2026-10-28, live probes)

The full per-chain table, with the probes that produce it, is in
[`BLOCKSCOUT-ROUTES.md`](BLOCKSCOUT-ROUTES.md). Re-run them with
`scripts/probe_blockscout.py` and `scripts/pro_map.py`.

### Blockscout PRO API

| Query shape | Chain 1 latency |
|---|---|
| `module=contract&action=listcontracts&items_count=10` | **0.6-0.7 s** |
| `+ sort=creation_desc&order=desc` | **0.4 s** |
| `+ filter=verified` | **12.6 s** |
| Watchdog's full query (`filter=verified&sort=creation_desc`) | **44.4-78.7 s** |

- **The endpoint is `/v2/api?module=contract&action=listcontracts`, not
  `/api/v2/smart-contracts`.** Probing the v2 shape with a `chainid`
  parameter returns `404 Network not supported`, which reads like a broken
  key but is the wrong URL.
- No API key -> `402 {"error":"Proceed with API key or make a X402 payment to continue"}`.
- With the key in `watchdog/.env` -> `200` in 0.4 s. The key is valid.
- `filter=verified` is the entire cost. The PRO `listcontracts` result does **not**
  carry `IsVerified` or `VerifiedAt`, so the cheap query cannot be filtered client-side.
- **A PRO page holds at most 10 items.** `items_count` of 10, 50 and 100 all
  return exactly 10. Paging is the only way to cover more.
- **PRO limits concurrency, not throughput.** Four simultaneous calls succeed,
  six answer 429, eight sequential calls with no delay all succeed. The client
  therefore needs *two* controls: a rate limiter for the rate and a semaphore
  for the in-flight count.
- Free tier: 20 credits/call, 100,000 credits/day, 5 RPS -> ~5,000 calls/day.
- PRO answers **402** for chains its plan does not cover (137 Polygon, 324
  zkSync, 8453 Base) and **404** for chains it does not support (1088 Metis,
  101010 Stability, 1313161554 Aurora). Both are ordinary per-chain outcomes,
  not errors.

### Per-chain instances (no key required)

**54 of the 60 chains answer.** An earlier, smaller sample suggested 7 of 18;
that sample guessed host names and was wrong. Deriving the hosts from the
authoritative Blockscout registry instead found instances for chains that had
been written off entirely -- Metis runs on `andromeda-explorer.metis.io` and
Aurora on `explorer.mainnet.aurora.dev`, and Gnosis, OP Mainnet, Mode, World
Chain and 40+ others run on hosts that are not `blockscout.com` subdomains.

All of them serve the same Blockscout v2 schema, so one parser covers every
host.

**Blocked or down (6):** polygon 137, arbitrum 42161, robinhood 4663,
arc 5042, base 8453 (Cloudflare 403), matchain 698 (503).

- The 403 is **not** user-agent-based: three user agents (none, a descriptive
  one, a browser one) all returned 403. There is nothing to gain from
  impersonating a browser, so the client sends an honest user agent.
- An instance answers **HTTP 422** for `items_count` above 50.

### Slither cost

~4.7 s per contract in the original runs; the run timed out at a 300 s cap twice.
This is a throughput problem, and it is the reason the discovery pipeline must be
decoupled from analysis and run in the background.

## 3. Target discovery architecture

Two access routes, chosen per chain at runtime and recorded per chain so the choice
is never re-litigated:

- **Route A - per-chain v2 instance.** No key, fast, rich payload with
  `is_verified` / `verified_at`. Preferred where it works.
- **Route B - PRO API.** `sort=creation_desc` only, never `filter=verified`.
  Verification is then resolved per address with `getsourcecode`, which costs
  1 call (20 credits) per candidate. Affordable at ~5,000 calls/day.

Combining both routes, **58 of the 60 chains are reachable**. Only **137
(Polygon)** and **8453 (Base)** have no route at all: Cloudflare blocks the
instance *and* PRO's plan gate refuses the chain. They need a paid PRO plan or
a different data source (direct RPC discovery, or an Etherscan-family API), and
they are recorded as unreachable rather than retried forever.

An instance host is a **cache, not a guarantee**: a dead host falls back to
PRO, so a broad list is safe and a narrow list just wastes credits.

Credit accounting and the round-robin cursor are the load-bearing parts:

- The cursor advances and is persisted **before** analysis starts, so a crash or
  timeout mid-analysis never causes re-fetching or data loss.
- A chain that fails degrades that chain only; the run still exits 0.
- A 429 is retried with exponential backoff and is **not** billed.

## 4. Phases

| Phase | Work | Exit criterion |
|---|---|---|
| P0 | Chain registry + Blockscout client with Route A/B selection and credit accounting | Live fetch of a verified contract from 10 chains |
| P1 | Discovery pipeline: cursor, round-robin, per-chain isolation, 429 backoff, re-scan on re-verification | One cycle over 59 chains, cursor durable across a forced kill |
| P2 | Slither runner port + proxy allowlist | Slither findings for a known contract, matching Watchdog's output |
| P3 | Unified schema: `contracts`, `findings.source`, `scan_runs`, `feed_cursors` + Alembic migration | Both engines write into one findings table |
| P4 | Frontend merge: chains, runs, feeds, unified findings, OAuth | Both view sets render live data |
| P5 | Wire the TF-IDF baseline into `run_scan` | Every scan carries ML scores alongside rule findings |
| P6 | Continuous scheduling (Task Scheduler / cron) | A scheduled cycle runs unattended |

P0-P3 are the merge. P4-P6 are the product.

## 5. Open decisions

1. **Canonical repo** — CyberStratum absorbing Watchdog is proposed in ADR-0012.
2. **Auth model** — Google OAuth for humans, API keys for machine clients (both).
3. **Commercial intent** — determines whether Slither's AGPL-3.0 is acceptable
   (see ADR-0013).
