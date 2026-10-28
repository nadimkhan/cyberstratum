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

### Blockscout PRO API

| Query shape | Chain 1 latency |
|---|---|
| `module=contract&action=listcontracts&items_count=50` | **0.6 s** |
| `+ sort=creation_desc&order=desc` | **0.4 s** |
| `+ filter=verified` | **44.4 s** |
| Watchdog's full query (`filter=verified&sort=creation_desc`) | **78.7 s** (and 24 s / 90 s+ timeout on repeats) |

- No API key -> `402 {"error":"Proceed with API key or make a X402 payment to continue"}`.
- With the key in `watchdog/.env` -> `200` in 0.4 s. The key is valid.
- `filter=verified` is the entire cost. The PRO `listcontracts` result does **not**
  carry `IsVerified` or `VerifiedAt`, so the cheap query cannot be filtered client-side.
- Free tier: 20 credits/call, 100,000 credits/day, 5 RPS -> ~5,000 calls/day.

### Per-chain instances (no key required)

Sampled 18 hosts: **7 OK** (ethereum 1, optimism 10, gnosis 100, zksync 324, celo 42220,
rootstock 30, scroll 534352) at 0.5-1.3 s, 50 items each, and the v2 payload *does*
carry verification fields.

**3 blocked by Cloudflare (403):** polygon 137, arbitrum 42161, base 8453.
**7 with no instance (404):** metis 1088, aurora 1313161554, linea 59144, berachain 80094,
sei 1329, sonic 146, bnb 56.
**1 broken (non-JSON):** fuse 122.

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

The three Cloudflare-blocked chains (polygon, arbitrum, base) are the gap. The
403 is an edge block on httpx's TLS fingerprint, so the fix is impersonation
(`curl_cffi`) rather than a paid tier. **Open item to verify before relying on it.**

Credit accounting and the round-robin cursor are the load-bearing parts:

- The cursor advances and is persisted **before** analysis starts, so a crash or
  timeout mid-analysis never causes re-fetching or data loss.
- A chain that fails degrades that chain only; the run still exits 0.
- A 429 skips the chain for that cycle and logs `rate_limited`.

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
