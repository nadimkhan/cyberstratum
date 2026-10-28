# Blockscout Routes — the measured capability table

Everything in this document was measured against the live Blockscout
ecosystem on **2026-10-28**, not assumed. The probes are committed and
re-runnable:

| Script | What it measures |
|---|---|
| `scripts/probe_blockscout.py` | Every chain's per-chain instance: status, payload shape, latency |
| `scripts/pro_map.py` | Every chain's PRO route: status, latency, item count |

Run them with:

```bash
node scripts/py.mjs scripts/probe_blockscout.py --emit
node scripts/py.mjs scripts/pro_map.py
```

The API key is read from `BLOCKSCOUT_API_KEY` or `.env`; it is never printed
and never written to the probe output.

---

## Two routes, two different APIs

They share a brand and a payload schema, but they are **different APIs**:

| | Per-chain instance | Unified PRO |
|---|---|---|
| Base URL | `https://{host}/api/v2/smart-contracts` | `https://api.blockscout.com/v2/api` |
| Selects a chain by | the host itself | `chainid=` parameter |
| Auth | none | `apikey=` parameter |
| Cost | free | 20 credits per call |
| Ordering | by contract id | by creation date (`sort=creation_desc`) |
| Carries `created_at` | no | no |
| Carries `is_verified` | yes, nested under `address` | no — inferred from the `ABI` field |

Both expose the same Blockscout v2 response schema, so **one parser covers
every host in the table below** — including the ones that are not
`blockscout.com` subdomains.

> The per-instance shape is `/api/v2/<resource>`. The PRO shape is the legacy
> `module`/`action` form under `/v2/api`. Probing the PRO route at
> `/api/v2/smart-contracts?chainid=1` returns `404 Network not supported`,
> which looks like a broken key but is actually the wrong endpoint.

---

## The four limits that shape the client

### 1. PRO pages are capped at 10 items

| Requested | Returned |
|---|---|
| `items_count=10` | 10 |
| `items_count=50` | 10 |
| `items_count=100` | 10 |

The cap is server-side. Asking for more does not get more; it just hides the
cap. The client clamps its PRO requests to 10 and pages instead.

### 2. PRO limits concurrency, not throughput

| Concurrent calls | Result |
|---|---|
| 2 | 2 × 200 |
| 4 | 4 × 200 |
| 6 | 1 × 200, 5 × **429** |
| 8 | 8 × **429** |
| 8 **sequential**, no delay | 8 × 200 |

The limit is on how many requests are *in flight*. Eight sequential calls
with no pause all succeed, so there is no per-minute quota being hit — the
free tier's credit allowance is what it is, and the concurrency ceiling is a
separate control.

The client therefore uses **two** controls, not one: a rate limiter for the
request rate and a semaphore (3) for the number in flight. A 429 is retried
with exponential backoff and is *not* billed.

### 3. `filter=verified` is ruinously expensive

| Query | Time |
|---|---|
| `listcontracts&items_count=10` | 0.4 – 0.7 s |
| `...&sort=creation_desc&order=desc` | 0.4 s |
| `...&filter=verified` | 12.6 s |
| `...&filter=verified&sort=creation_desc` | 44.4 – 78.7 s |

The filter is the entire cost of the query, and it cannot be replaced by a
client-side filter: the PRO `listcontracts` payload carries no `IsVerified`
and no `VerifiedAt`. **The filter is never used.**

The consequence: a PRO listing contains a mix of verified and unverified
contracts, and verification has to be resolved per contract afterwards.

### 4. Instance page size caps at 50

Instances honour `items_count` up to 50; above that they answer **HTTP 422**.
Several instances ignore the parameter entirely and always return 50.

---

## Per-chain capability

### Per-chain instances — 54 of 60 answer

The hosts are **not** all `blockscout.com` subdomains, and filtering on the
domain would silently discard working instances:

| Chain | Host | Note |
|---|---|---|
| 1 Ethereum | `eth.blockscout.com` | |
| 10 OP Mainnet | `explorer.optimism.io` | redirects from `optimism.blockscout.com` |
| 30 Rootstock | `rootstock.blockscout.com` | |
| 61 Ethereum Classic | `etc.blockscout.com` | |
| 100 Gnosis | `gnosisscan.io` | redirects from `gnosis.blockscout.com` |
| 122 Fuse | `explorer.fuse.io` | `fuse.blockscout.com` serves non-JSON |
| 130 Unichain | `unichain.blockscout.com` | |
| 177 HashKey | `hsk.blockscout.com` | |
| 239 TAC | `explorer.tac.build` | |
| 291 Orderly | `explorer.orderly.network` | |
| 314 Filecoin VM | `filecoin.blockscout.com` | |
| 324 zkSync Era | `zksync.blockscout.com` | |
| 360 Shape | `shapescan.xyz` | |
| 42220 Celo | `celo.blockscout.com` | |
| 4326 MegaETH | `megaeth.blockscout.com` | |
| 480 World Chain | `worldchain-mainnet.explorer.alchemy.com` | Alchemy's explorer |
| 488 BXN | `blackfortscan.com` | |
| 592 Astar | `astar.blockscout.com` | |
| 714 Eden | `eden.blockscout.com` | |
| 747 Flow | `evm.flow.com` | |
| 869 World Mobile | `explorer.worldmobile.io` | |
| 957 Derive | `explorer.derive.xyz` | |
| 102030 Creditcoin | `creditcoin.blockscout.com` | |
| 1135 Lisk | `blockscout.lisk.com` | honours `items_count` |
| 1729 Reya | `explorer.reya.network` | |
| 1829 Playblock | `explorer.playblock.io` | |
| 1868 Soneium | `soneium.blockscout.com` | |
| 1890 LightLink | `phoenix.lightlink.io` | |
| 2020 Ronin | `explorer.roninchain.com` | |
| 2288 Moca Chain | `scan.mocachain.org` | |
| 2366 KiteAI | `kitescan.ai` | |
| 34443 Mode | `explorer.mode.network` | |
| 42170 Arbitrum Nova | `arbitrum-nova.blockscout.com` | |
| 42793 Etherlink | `explorer.etherlink.com` | |
| 529375 LayerK | `explorer.layerk.com` | |
| 57073 Ink | `explorer.inkonchain.com` | |
| 6497 Awaji | `awaji.blockscout.com` | |
| 6498 Mizuhiki | `mizuhiki.blockscout.com` | |
| 7000 ZetaChain | `zetascan.com` | |
| 8021 Numine | `numine.blockscout.com` | |
| 97741 Pepe Unchained | `pepuscan.com` | |
| 98866 Plume | `explorer.plume.org` | |
| 13371 Immutable zkEVM | `explorer.immutable.com` | |
| 1514 DATA Network | `www.datanetscan.io` | |
| 190415 HPP | `explorer.hpp.io` | |
| 245022934 Neon | `neon.blockscout.com` | |
| 612055 Cross | `www.crossscan.io` | |
| 685689 Gensyn | `gensyn-mainnet.explorer.alchemy.com` | Alchemy's explorer |
| 97477 Doma | `explorer.doma.xyz` | |
| 101010 Stability | `explorer.stabilityprotocol.com` | |
| 32769 Zilliqa 2 | `zilliqa.blockscout.com` | |
| 1088 Metis | `andromeda-explorer.metis.io` | |
| 1313161554 Aurora | `explorer.mainnet.aurora.dev` | |
| 534352 Scroll | `scrollscan.com` | redirects from `scroll.blockscout.com` |

### Instances that are blocked or down — 6

| Chain | Host | Response | PRO fallback |
|---|---|---|---|
| 137 Polygon | `polygon.blockscout.com` | 403 (Cloudflare) | **402 — no route** |
| 42161 Arbitrum One | `arbitrum.blockscout.com` | 403 (Cloudflare) | 200 ✓ |
| 4663 Robinhood | `robinhoodchain.blockscout.com` | 403 (Cloudflare) | 200 ✓ |
| 5042 Arc | `explorer.arc.io` | 403 (Cloudflare) | 200 ✓ |
| 698 Matchain | `matchscan.io` | 503 (down) | 200 ✓ |
| 8453 Base | `base.blockscout.com` | 403 (Cloudflare) | **402 — no route** |

The 403s are **not** user-agent-based: three different user agents (none, a
descriptive one, and a browser one) all returned 403. There is nothing to
gain from pretending to be a browser, so the client sends an honest
`cyberstratum/0.1` user agent.

`explorer.blockscout.com` — the Blockscout project's own multichain
explorer — returns HTTP 200 for *any* address including ones that do not
exist. It can never be used to confirm that a contract exists, so it is only
ever used as a link target, never as a source of truth.

### PRO route status per chain

| Status | Chains | Meaning |
|---|---|---|
| **200** | 54 | supported and covered by the key's plan |
| **402** | 137, 324, 8453 | "Featured chain requires one of the following plans: Builder, Business, Pro" |
| **404** | 1088, 101010, 1313161554 | not supported by PRO at all |

---

## The conclusion that matters

Combining both routes, **58 of the 60 chains are reachable**:

| Category | Count | Chains |
|---|---|---|
| Instance works | 54 | — |
| Instance blocked, PRO works | 4 | 42161, 4663, 5042, 698 |
| **No route at all** | **2** | **137 (Polygon), 8453 (Base)** |

Polygon and Base are the two chains where Cloudflare blocks the instance
*and* PRO's plan gate refuses the chain. They need either a paid PRO plan or
a different data source (a direct RPC-based discovery job, or an
Etherscan-family API). They are recorded in the registry as unreachable
rather than being silently retried forever.

zkSync, Metis, Stability and Aurora each fail on exactly one route and work
on the other — which is the whole argument for having two routes at all.

---

## What the client does with this

1. **Prefer the instance.** It is free, unkeyed and unmetered.
2. **Fall back to PRO** when the instance fails, is blocked, or has no host.
3. **Never use `filter=verified`.** Take the cheap listing and resolve
   verification per contract.
4. **Degrade per chain, never per batch.** One unreachable chain costs that
   chain; the sweep continues.
5. **Clamp page sizes per route** — 10 for PRO, 50 for instances.
6. **Bound PRO concurrency to 3** and retry a 429 with backoff.
7. **Never spend credits on a call that failed** — a refused call is refunded.

The registry records which route each chain can use, and the route that was
actually taken is stored on every discovered contract, so a sweep can always
be audited after the fact.
