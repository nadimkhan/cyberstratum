# CyberStratum — Work Tracker

**Purpose:** a single persistent record of what is done and what remains.
Update this file after every completed task. Mark the item done, note the commit,
and update the "Remaining" list so the next session knows exactly where to resume.

**Last updated:** 2026-10-29
**Latest commit:** see `git log -1 --oneline`

---

## 1. Where we are

Canonical repository: `cyberstratum` (branch `master`).
Remote of record: `https://github.com/nadimkhan/cyberstratum.git` (private).
Development environment: **WSL Ubuntu** (Linux-native). See §7.

Product: a commercial multi-tenant smart-contract security platform.
Frontend → Netlify. Backend, PostgreSQL, Redis/worker, ML model → Linux VPS.

---

## 2. Done

### Foundation
- [x] Fork-aware EVM bytecode engine — deterministic disassembly, metadata separation, CFG/reachability, reproducible artifacts. `580167b`
- [x] Engine validated against `evmole` on 7 contracts — 31,504 instructions, 0 instruction mismatches, 0 wrong destinations. `89.2%` static-jump agreement.
- [x] Resolver corrected (top-anchored stack window, DUP/SWAP semantics, path merges). Unresolved CFG edges `199` → `148`. `91e6cd1`
- [x] ML baseline — training-only TF-IDF, family-safe split, one-vs-rest logistic regression, manifests, model cards. `02e4098`
- [x] FastAPI backend — SQLAlchemy models, Alembic, scan pipeline, inline bytecode, Sourcify fallback, RQ worker, routes. `459cffe`, `892b9c8`
- [x] Next.js frontend — dashboard, scans, scan detail, findings, reproducibility. `b491520`
- [x] Server-only API-key boundary enforced (`API_KEY` never `NEXT_PUBLIC_`).
- [x] RQ worker hardening — stale PID cleanup, live-duplicate refusal. `52b0aa7`
- [x] Root one-command launcher — `npm run dev` / `stop` / `logs`. `76399b1`
- [x] Launcher no longer reports success when the worker fails to register. `be49493`
- [x] Ctrl+C console isolation (`0xC000013A` fix, detached supervisor). `492933c`
- [x] **Launcher made cross-platform** — one script now runs on Windows and WSL/Linux. See §8. `bc38687`

### Watchdog merge
- [x] Merge proposal + licensing posture (FastAPI MIT, Slither AGPL-3.0 out-of-process). `5e9cb81`
- [x] Schema reconciliation across both codebases. `67f7a2c`
- [x] Multi-chain Blockscout layer — measured 60-chain registry, 54 working routes, PRO cap 10, instance cap 50, client concurrency cap 3. `e838deb`
- [x] Continuous discovery feed — per-chain isolation, cursors, idempotent persistence, workspace isolation. `f200d94`
- [x] Source acquisition + audit pipeline — Blockscout first, Sourcify second, source as artifact, unified finding provenance. `52c98ab`
- [x] Slither detector coverage — all 122 detectors of Slither 0.11.6 mapped. `52c98ab`
- [x] **Slither no-verdict fix** — a failed engine run is `skipped="engine_error"`, never "clean". `df1f5c6`

### Architecture decisions (ADRs)
- [x] ADR-0012 merge and canonical platform
- [x] ADR-0013 licensing (FastAPI MIT, Slither AGPL boundary)
- [x] ADR-0014 multi-engine portfolio, Mythril manual-only, no-verdict semantics. `ae219df`
- [x] ADR-0015 dataset and model lifecycle. `ae219df`
- [x] ADR-0016 daily update checks vs gated production upgrades. `ae219df`
- [x] ADR-0017 evidence model + source↔bytecode correspondence. `ae219df`
- [x] ADR-0018 authorised scanning and disclosure. `ae219df`
- [x] ADR-0019 deterministic PDF reporting (ReportLab). `ae219df`
- [x] Consolidated plan document. `4e1ee97`

### Verified capabilities (measured, not assumed)
- [x] Source-to-bytecode correspondence proved — Sourcify exact compiler input → byte-identical runtime → source map → PC→line. USDC `807` instructions mapped; Uniswap V3 Factory on solc 0.8.17.
- [x] Immutable-slot masking identified — UniversalRouter `617` constructor-set bytes differ; must be masked, not discarded.
- [x] Mythril proven working in isolation — source mode SWC-107 at line 9; raw-runtime mode SWC-105 High with exploit sequence.
- [x] Mythril cost measured — ~109s small fixture; real USDC runtime produced no verdict within a bounded budget.
- [x] ReportLab deterministic PDF — two renders of identical evidence → byte-identical SHA-256.
- [x] Correspondence proof re-verified end to end as a repo script — `scripts/live_check_correspondence.py`. USDC: executable code byte-identical (2143 bytes), metadata trailer differs only in its 32-byte `bzzr0` hash, 807 instructions, 4/4 interesting opcodes mapped to exact source lines.
- [x] Correspondence proof reproduced natively in WSL — same 807 instructions, same 4/4 opcode-to-source-line mappings. WSL solc `0.4.24` and `0.8.26` installed into the `solc-select` layout so the product's compiler discovery finds them there too (previously WSL had them only in `~/bin`, where discovery could not see them).
- [x] Two Sourcify traps found and documented — the stored `stdJsonInput` has **no** `outputSelection`, so solc emits no bytecode and the check falsely reports "no match"; and the gate must be metadata-aware executable-code equality, not whole-byte equality.

---

## 3. Remaining — ordered by priority

### P0 — dataset ingestion (current focus, per decision)
- [ ] Ingest SmartBugs Curated (Apache-2.0) as the primary evaluation corpus.
- [ ] Ingest DeFiHackLabs (Apache-2.0) for exploit PoCs.
- [ ] Load SWC Registry (MIT) as weakness taxonomy + join key.
- [ ] Audit Web3Bugs per-repository — `not-yet-determined` labels are NOT negatives.
- [ ] Record licence + provenance + redistribution terms per dataset.
- [ ] Label tiers: heuristic / reviewed / unlabelled, kept explicit.
- [ ] Exact + normalised + near-duplicate detection.
- [ ] `family_key` assignment; family-level train/val/test splits (no family leakage).
- [ ] Immutable content-addressed dataset manifests.
- [ ] Model promotion gates (promotion only from reviewed labels).

### P0 — Mythril as a manual action
- [ ] API endpoint to trigger a Mythril run on demand.
- [ ] RQ job with an explicit long budget and its own queue.
- [ ] Frontend button on the scan detail page.
- [ ] Persist Mythril findings with `source=mythril` provenance.
- [ ] Enforce the no-verdict rule for Mythril (`success`/`error` checked before findings).

### P1 — deployment topology
- [x] Netlify config for the Next.js frontend — Next.js runtime, publish `apps/web/.next`. `835ce16`
- [x] Frontend API base URL is public build config; `API_KEY` stays server-only. `835ce16`
- [x] VPS deployment script + hardened systemd units for the API and the worker. `835ce16`
- [x] Alembic migration path verified (`upgrade → downgrade → upgrade`) on WSL. `835ce16`
- [x] CORS for the Netlify origin — `WEB_BASE_URL` + `CORS_EXTRA_ORIGINS`. `835ce16`
- [ ] Model artifact serving on the VPS.
- [ ] Actual Netlify site creation and a real deployment.
- [ ] Actual VPS provisioning and a real deployment.

### P1 — reporting
- [ ] Deterministic PDF report endpoint (ReportLab, `invariant=True`).
- [ ] Evidence rendering: source line, bytecode offset, PC, instruction sequence, CFG path, reachability.
- [ ] Provenance section: tool versions, dataset manifest, model manifest.

### P2 — platform hardening
- [ ] Multi-tenant enforcement — workspace isolation across every query path.
- [ ] Google OAuth for humans + hashed API keys for machine clients.
- [ ] Daily dependency update checks (check only; upgrade through gated CI).
- [ ] Authorised bug-bounty scope ingestion + safe-harbour rules.
- [ ] EVM source↔bytecode correspondence service — the pipeline is proven and scripted
      (`scripts/live_check_correspondence.py`, verified live on both Windows and WSL);
      it still needs to become a service that stores the correspondence proof
      alongside a scan and feeds the PDF report.

---

## 4. Constraints to keep honouring

- Slither is **AGPL-3.0**: out-of-process only, never imported/vendored. Enforced by `tests/unit/test_agpl_boundary.py`.
- Mythril lives **outside** the application Python environment and outside default scans.
- An empty engine result is **never** "clean" without a validated verdict.
- Exact source lines require **proven** correspondence; bytecode findings get bytecode evidence only.
- The unrelated PostgreSQL on `5432` is **out of scope** — never modify or remove it.
- The project must be installed **editable** (`uv pip install -e .`). A
  non-editable install puts a copy of the app package in site-packages that
  shadows the working tree, so the suite certifies stale code. Guarded by
  `tests/unit/test_environment_is_not_stale.py` and `npm run check`.
- Do not start the dev stack unless explicitly asked; the user starts it manually.
- `Watchdog` at `E:/projects/watchdog` stays unchanged as the porting source of truth.

---

## 5. Environment reference

| Component | Location | Port |
|---|---|---|
| Project (WSL) | `~/projects/cyberstratum` | — |
| PostgreSQL 14 (WSL, non-root) | `~/.cyberstratum/pgdata` | 5433 |
| Redis (WSL) | system | 6379 |
| FastAPI (WSL) | uvicorn | 8000 |
| Next.js (WSL) | dev server | 3100 |
| Mythril venv (WSL) | `~/venvs/mythril` | — |
| Linux solc | `~/.solc-select/artifacts/solc-0.8.26` | — |
| Linux solc | `~/.solc-select/artifacts/solc-0.4.24` | — |
| Unrelated PostgreSQL (Windows, out of scope) | `C:\Program Files\PostgreSQL\17` | 5432 |

> **Port clash.** WSL's cluster on `5433` makes Windows create a `wslrelay.exe`
> that holds `127.0.0.1:5433`, so the Windows cluster cannot bind that port.
> The launcher fails loudly rather than pretending it started. Stop the WSL
> side, or give one of them a different port.

Commands (from WSL, project root): `npm run dev` · `npm run stop` · `npm run logs`

---

## 6. Task log

| # | Task | Result | Commit |
|---|---|---|---|
| 1 | EVM engine | built + validated vs evmole | `580167b` |
| 2 | ML baseline | TF-IDF + logistic regression | `02e4098` |
| 3 | FastAPI backend | models, migrations, pipeline, worker | `459cffe` |
| 4 | Next.js frontend | 5 routes, 57 Vitest tests | `b491520` |
| 5 | Resolver correction | unresolved edges 199 → 148 | `91e6cd1` |
| 6 | Launcher | one-command dev stack | `76399b1` |
| 7 | Watchdog merge plan | ADR + licensing | `5e9cb81` |
| 8 | Blockscout layer | 60 chains, 54 routes | `e838deb` |
| 9 | Discovery feed | continuous, isolated | `f200d94` |
| 10 | Source audit pipeline | merged engines | `52c98ab` |
| 11 | Slither no-verdict fix | engine_error skip | `df1f5c6` |
| 12 | Six ADRs | portfolio → PDF | `ae219df` |
| 13 | Git remote | private repo created, pushed | — |
| 14 | WSL environment | PostgreSQL 14 non-root, Node 22, Python 3.12 | — |
| 15 | Cross-platform launcher | verified on Windows and WSL | see §8 |
| 16 | Deployment config | Netlify + systemd + CORS | `835ce16` |
| 17 | Correspondence proof | script + unit tests, live on Windows and WSL | `3ca708d` |
| 18 | Compiler discovery | `SOLC_ARTIFACTS_DIR` honoured; WSL solc installed | `5edaa40` |
| 19 | ADR-0017 corrected | the gate is metadata-aware, not whole-byte | `61f7bb9` |
| 20 | Stale-install guard | a shadowing install now fails the suite and `npm run check` | `ecf1fca`, `9c9e0cf` |
| 21 | Docs | editable-install warning in README + runbook; WSL port clash documented | `9822640` |

---

## 7. Notes on the WSL migration

- The repo now has an off-box remote. **Nothing on Windows is the only copy.**
- The Windows copy at `E:/projects/cyberstratum` is a working duplicate until WSL validation passes.
- Windows cleanup order (only after WSL passes): repo working copy → `E:/tools/pg17` → `E:/tools/redis8`.
- `C:\Program Files\PostgreSQL\17` is the unrelated `5432` install — **never touch it**.
- WSL filesystem: `D:\WSL\Ubuntu\ext4.vhdx`. The project lives on the ext4 volume, not `/mnt/e`, for Linux-native I/O.

---

## 8. The cross-platform launcher

`scripts/dev.mjs` is one script for both operating systems. It no longer assumes
Windows paths, `.exe` suffixes, `netstat`, `taskkill`, `tasklist` or PowerShell.

| Concern | Windows | Linux / WSL |
|---|---|---|
| PostgreSQL binaries | `E:/tools/pg17/pgsql/bin` | `/usr/lib/postgresql/14/bin` |
| PostgreSQL data | `E:/data/cyberstratum/pgdata` | `~/.cyberstratum/pgdata` |
| Redis binaries | `E:/tools/redis8/Redis-8.10.3-Windows-x64-msys2` | `/usr/bin` |
| Port holders | `netstat -ano` | `ss -ltnpH` |
| Process list | PowerShell `Win32_Process` | `ps -eo pid=,ppid=,args=` |
| Killing a tree | `taskkill /T /F` | `kill(-pgid)` then `SIGKILL` |
| Liveness | `tasklist` | `kill(pid, 0)` |
| Web UI bind | `-H 127.0.0.1` | `-H 127.0.0.1` |

Every path is overridable from the environment: `PG_BIN`, `PG_DATA`, `PG_LOG`,
`REDIS_BIN`.

`npm run check` resolves and reports every path without starting anything.

### Defects found and fixed while porting

1. **The sweep killed the `--stop` helper.** The old pattern matched any
   `scripts/dev.mjs`, so a stop run could terminate itself mid-cleanup. The
   pattern now excludes `--stop`.
2. **Next.js bound the IPv6 wildcard**, so a probe against `127.0.0.1` failed
   even though the server was answering on `::1`. The web UI is now pinned to
   `-H 127.0.0.1`, and the probe tries `127.0.0.1`, `localhost` and `::1`.
3. **The Next.js telemetry helper was orphaned.** It holds no port, so the
   port check never found it. It is now matched by `next/dist/`.
4. **A deliberate stop logged "redis exited unexpectedly."** The state file
   now carries a `stopping` flag that the supervisor reads.
5. **PostgreSQL was killed with the supervisor's process group**, so it never
   got a clean shutdown. The infrastructure is now stopped *before* the
   supervisor tree, so `pg_ctl -m fast` runs and no crash recovery is needed.
6. **Redis was shut down even when the launcher did not start it.** In WSL the
   distribution's Redis is a systemd service on 6379. The launcher now only
   stops a Redis it started itself.
7. **Node was not on the WSL PATH**, so `npm` resolved to the *Windows* npm.
   `~/.local/node/bin` is now prepended in `~/.bashrc` and `~/.profile`.

### Verified

- WSL: `npm run dev` → API healthy and web UI `HTTP 200` in 11–24 s; worker
  registered on `cyberstratum:scans`; `npm run stop` → everything stopped, no
  leftovers, PostgreSQL shut down cleanly, the systemd Redis left running.
- Windows: `npm run dev` → all four ports listening, API healthy, web UI
  `HTTP 200`; `npm run stop` → everything stopped, only the unrelated
  PostgreSQL on 5432 left.
- Windows quality gate after the port: Ruff clean, mypy clean across 60
  source files, `414` pytest passed.
- Windows quality gate after the correspondence script: Ruff clean, mypy
  clean across 60 source files, `424` pytest passed, `57` Vitest passed,
  `tsc --noEmit` passed.
- Windows quality gate at the end of this round: Ruff clean, mypy clean
  across 60 source files, `429` pytest passed.
- WSL quality gate at the end of this round: Ruff clean, mypy clean across
  60 source files, `429` pytest passed, correspondence live check 4/4
  opcode-to-source-line mappings.
- WSL re-verified on the committed code (`bc38687`): `npm run dev` → API
  healthy, web UI `HTTP 200`, worker registered; `npm run stop` →
  PostgreSQL stopped cleanly (`pg_ctl: no server running`), the systemd
  Redis and PostgreSQL left active, no leftover project processes.

---

## 12. A compiler failure is not a correspondence failure

The obsolete scratch proof (`prove_real_contract.py`) died on a `solc`
timeout and printed a bare traceback. That exposed a real gap in the
committed script: a compiler that hangs, crashes, or prints something that
is not JSON raised out of the proof as an unhandled exception, and the
caller could not tell "the source does not describe this contract" from
"the check never ran". The second is a false negative, and a security
product must not produce one.

`scripts/live_check_correspondence.py` now separates the three outcomes:

| Exit | Meaning |
|---|---|
| `0` | Correspondence established, or the check was skipped with nothing to learn |
| `1` | The check ran and the source does **not** describe the deployed contract |
| `2` | The check could not be performed — the compiler hung, crashed, or emitted non-JSON |

`RecompileError` carries exit `2`. A non-zero compiler exit, a
`TimeoutExpired`, a `JSONDecodeError` and a missing binary all raise it,
and none of them is ever reported as a mismatch.

Two further hazards are now reported rather than absorbed:

- **Network-fetched sources.** If a source in the stored standard-JSON input
  carries `urls` instead of inline `content`, `solc` fetches it over the
  network. The recompilation then depends on what the URL serves at that
  moment rather than on the verification's own recorded source, and it can
  hang on a slow or blocked network. The proof now prints how many sources
  are affected. USDC is fully inline, so it reports none.
- **The wrong compiler.** The proof requires the exact verified compiler. A
  mismatch is still a mismatch, but a *hang* is never treated as evidence
  against correspondence.

This follows the rule the rest of the product already follows: an engine
that did not produce a verdict is reported as *no verdict / skipped / error*,
never as *clean*. The same rule now applies to the proof itself.

### Tests

`tests/unit/test_correspondence.py` gained five cases: a hung compiler, a
crashing compiler, a compiler that emits non-JSON, a compiler that cannot
be run at all, and a check that the three exit codes stay distinct.

### Verified

- Windows: the live proof still establishes correspondence — 807
  instructions, 4/4 interesting opcodes mapped to exact source lines,
  exit `0`.
- Windows quality gate: Ruff clean, mypy clean across 60 source files,
  `434` pytest passed.
- WSL quality gate on the committed code (`234438b`): Ruff clean, mypy
  clean across 60 source files, `434` pytest passed, correspondence live
  check 4/4 opcode-to-source-line mappings.
- Frontend gate: `57` Vitest tests passed across 7 files, `tsc --noEmit`
  clean.
- Environment restored afterwards: the Windows isolated cluster on 5433
  and the WSL CyberStratum cluster on 5433 are both stopped; the unrelated
  Windows PostgreSQL on 5432 is still `RUNNING` and untouched; the WSL
  systemd PostgreSQL and Redis are both `active` and Redis answers `PONG`.
