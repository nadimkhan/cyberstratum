# CyberStratum — Pending Work

**What this document is.** A single, ordered, actionable list of everything still
to be built, with the acceptance criteria each item must meet before it counts
as done. It is the companion to [`WORK-TRACKER.md`](WORK-TRACKER.md): the
tracker records *what happened*, this document records *what is left*.

**How to use it.** Work top to bottom. When an item is finished, tick it here,
record the commit in the tracker, and move it into "Completed". When an item
turns out to need something only the user can supply, move it to
[§4 Blocked on external inputs](#4-blocked-on-external-inputs) rather than
leaving it to rot in the main list.

**Status legend**

| Marker | Meaning |
|---|---|
| `[ ]` | Not started |
| `[~]` | In progress |
| `[x]` | Done — ticked with the commit that landed it |
| `[!]` | Blocked — the reason is stated inline and it is also listed in §4 |

**Last updated:** 2026-10-29
**Rule that governs every item below:** an engine that did not produce a
verdict is reported as *no verdict / skipped / error* — never as *clean*.
Applies to Mythril, Slither, the ML model, the correspondence proof, and the
dataset promotion gate alike.

---

## 1. P0 — the product does not exist without these

### 1.1 Dataset ingestion

The ML baseline exists but has no real corpus behind it. Until ingestion
lands, every model number is measured against synthetic smoke data whose
labels are heuristic, not reviewed ground truth.

The machinery now exists as its own distribution, `packages/dataset_ingest`
(`evm-dataset`, import package `evm_dataset`), installed editable alongside
the other project packages so it can never shadow the working tree.

| # | Item | Acceptance criterion | Status |
|---|---|---|---|
| 1.1.1 | Licence + provenance record per dataset | Every dataset carries an SPDX-ish licence id, licence URL, upstream URL, upstream revision, redistribution terms, and a human note. Known: SmartBugs Curated `Apache-2.0`, DeFiHackLabs `Apache-2.0`, SWC Registry `MIT`. Web3Bugs is representable but flagged `per_repository_audit_required` so it can never be treated as one licence. | `[x]` `54fced8` |
| 1.1.2 | Label tiers | `heuristic` / `reviewed` / `unlabelled`. A missing, unknown, or `not-yet-determined` label is **`unlabelled`, never a negative**. A function states whether a tier may serve as a supervised negative. | `[x]` `54fced8` |
| 1.1.3 | Exact dedup | sha256 over raw bytes. Stable across runs and machines. | `[x]` `54fced8` |
| 1.1.4 | Normalised dedup | Comments stripped, whitespace collapsed, string literals minimally normalised, then hashed. Insensitive to comment/whitespace edits where the exact hash is sensitive. | `[x]` `54fced8` |
| 1.1.5 | Near-duplicate detection | A deterministic similarity signature and clustering at a documented threshold. Must not use `hash()` or unseeded `random` — the hash has to be reproducible on another machine in another year. | `[x]` `54fced8` |
| 1.1.6 | `family_key` | Two variants of the same project share a family key, so they cannot straddle a split. | `[x]` `54fced8` |
| 1.1.7 | Family-level splits | Train/validation/test assigned **by family**. No family appears in two splits. Deterministic for a given seed. Every record lands in exactly one split. An empty split is a clear error, not a silent zero. | `[x]` `54fced8` |
| 1.1.8 | Immutable content-addressed manifest | Manifest hash over a canonical serialisation (sorted keys, fixed separators, sorted record ids). Regenerating from identical inputs yields an identical hash. No wall-clock time, no absolute paths inside the manifest. `verify_manifest` detects a tampered record. | `[x]` `54fced8` |
| 1.1.9 | Promotion gate | Promotion is permitted **only** from `reviewed` labels, and returns a structured decision with a reason string — not a bare bool. Heuristic and unlabelled data may be used for exploratory training but cannot promote a model. | `[x]` `54fced8` |
| 1.1.10 | Actual corpus ingest | Fetch SmartBugs Curated and DeFiHackLabs, load the SWC Registry as taxonomy + join key, and audit Web3Bugs per repository. **Blocked until the licence terms are confirmed for redistribution of derived artifacts — see §4.** The machinery is exercised against the smoke corpus, which carries heuristic labels and is **not** reviewed ground truth. | `[!]` §4.3 |

### 1.2 Mythril as a manual, on-demand action

Mythril is manual-only by decision (ADR-0014): it is slow, and its real-runtime
cost on a production contract exceeded a bounded budget with no verdict. It
must never join the default scan.

| # | Item | Acceptance criterion | Status |
|---|---|---|---|
| 1.2.1 | Out-of-process runner | Mythril is invoked as an unmodified external executable over a process boundary. Never imported, never added to the app venv. The AGPL boundary guard must still pass. | `[x]` `54fced8` |
| 1.2.2 | **Inverted exit code** | Mythril exits `1` when it finds issues and `0` when it finds none. The verdict comes from the JSON envelope. The exit code is used **only** to detect a process that died without a verdict. A runner that maps non-zero to "failed" discards every genuine result. | `[x]` `54fced8` |
| 1.2.3 | **Creation-vs-runtime trap** | Feeding creation bytecode to `--bin-runtime` returns `{"error": null, "issues": [], "success": true}` with exit `0` — a silent false clean. The action must take runtime bytecode explicitly, detect creation code, and **refuse loudly** with a distinct reason. | `[x]` `54fced8` |
| 1.2.4 | Envelope validated first | `success: false` with empty issues is an **error**, not a clean result. Non-JSON output, a crash, a timeout, and a missing binary are all *no verdict*. Only `success: true` with zero issues is clean. | `[x]` `54fced8` |
| 1.2.5 | Binary name | The console script is `myth`, not `mythril`. Path configurable; a missing binary yields a clear skip reason, not an exception. | `[x]` `54fced8` |
| 1.2.6 | API + own queue | An endpoint to trigger a Mythril run on demand, on a **separate queue** with an explicit long budget. It is never part of a default scan. | `[x]` `54fced8` |
| 1.2.7 | Persisted with provenance | Findings are stored with `source="mythril"` so the unified findings view can distinguish them. The no-verdict rule applies to Mythril exactly as to every other engine. | `[x]` `54fced8` |
| 1.2.8 | Frontend action | A button on the scan detail page, showing the run's state and its verdict — including "no verdict" when that is the truth. | `[x]` `54fced8` |

### 1.3 Deterministic PDF reporting

A disclosure report has to be reproducible: the same evidence must yield the
same document, so a reviewer can confirm the document matches the evidence.

| # | Item | Acceptance criterion | Status |
|---|---|---|---|
| 1.3.1 | Deterministic renderer | ReportLab with invariant rendering. **Two renders of identical evidence produce a byte-identical SHA-256.** No wall-clock timestamp, hostname, or random id in the output unless explicitly supplied by the caller. Document metadata pinned to constants. | `[x]` `54fced8` |
| 1.3.2 | Evidence rendering | Bytecode evidence (offset/PC, opcode, instruction sequence, CFG path, reachability) and source evidence (path + line) rendered as clearly different kinds. | `[x]` `54fced8` |
| 1.3.3 | Source lines only when proven | A source path and line appear **only** when source-to-bytecode correspondence was actually proven. Otherwise the report says the finding is bytecode-only and claims no source line. | `[x]` `54fced8` |
| 1.3.4 | Per-engine breakdown | Which engines ran and which did not. An engine with no verdict reads as **"no verdict"** — never "clean" or "passed". Skip reasons are shown verbatim. | `[x]` `54fced8` |
| 1.3.5 | Provenance section | Tool versions (parser, ruleset, model, external engines), dataset manifest id/hash, model manifest id/hash, correspondence proof status. A missing value renders as "not available" — never omitted silently, never fabricated. | `[x]` `54fced8` |
| 1.3.6 | Limitations block | The report states that it presents evidence collected by automated analysis, does not assert exploitability, and that absence of findings is not proof of absence of vulnerabilities. | `[x]` `54fced8` |

### 1.4 Source ↔ bytecode correspondence as a stored service

The proof works and is scripted (`scripts/live_check_correspondence.py`,
verified live on both Windows and WSL: USDC, executable code byte-identical over
2,143 bytes, 807 instructions, 4/4 interesting opcodes mapped to exact source
lines). It is now part of the product.

| # | Item | Acceptance criterion | Status |
|---|---|---|---|
| 1.4.1 | Stored proof | The proof is stored alongside the scan, with the compiler version, the executable-byte comparison result, the metadata difference, the instruction count, and the PC→line mapping. | `[x]` `54fced8` |
| 1.4.2 | Three-state outcome | `0` established or skipped · `1` a real mismatch · `2` the check could not be performed (compiler hung, crashed, or emitted non-JSON). Exit `2` is **never** reported as a mismatch. In the product this is four outcomes: `established` / `skipped` / `mismatch` / `unavailable`. | `[x]` `54fced8` |
| 1.4.3 | Feeds the report | The stored proof feeds §1.3 — it is the reason a source line may or may be claimed. | `[x]` `54fced8` |
| 1.4.4 | Metadata-aware gate | Equality is judged on **executable code**, not the whole runtime: Solidity's metadata hash legitimately differs. Constructor-set immutables are masked or proven, never silently ignored. | `[x]` `54fced8` |

**Live proof:** the manual action was driven over HTTP against the running
product. USDC `0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48` →
`status="established"`, `source_path="FiatTokenProxy.sol"`,
`compiler_version="0.4.24+commit.e67f0147"`. The proof is stored, readable
from the scan detail, and the report is served with its own SHA-256.

---

## 2. P1 — deployment

| # | Item | Acceptance criterion | Status |
|---|---|---|---|
| 2.1 | Model artifact serving on the VPS | The ML model and its manifest are served by the backend, and their hashes appear in the report's provenance section. | `[ ]` |
| 2.2 | Real Netlify deployment | A live site on the **Next.js runtime** (not static export — the frontend does server-side live API reads). `NEXT_PUBLIC_API_BASE_URL` set as public build config; `API_KEY` stays server-only and is never renamed to `NEXT_PUBLIC_API_KEY`. | `[!]` §4.1, §4.5 |
| 2.3 | Real VPS provisioning | The backend, PostgreSQL, Redis/worker, and ML model running on a Linux VPS via the hardened systemd units. `CORS_EXTRA_ORIGINS` set to the deployed Netlify origin. | `[!]` §4.2, §4.5 |
| 2.4 | Alembic on the VPS | `alembic upgrade head` verified on the real database, with a tested downgrade path. | `[!]` §4.2 |

**Already done:** the Netlify Next.js runtime config, the hardened systemd
units (API, scan worker, Mythril worker, correspondence worker), the VPS deploy
script, the Alembic migration path, and the multi-origin CORS configuration all
exist and are verified. The migration round trip was re-proven on the isolated
cluster: `upgrade → head` → `downgrade -1` → `upgrade head` again, all exit `0`,
head `e2f5a1b9c740`. Only the *real* deployments remain, and both are blocked on
credentials — §4.

---

## 3. P2 — platform hardening

| # | Item | Acceptance criterion | Status |
|---|---|---|---|
| 3.1 | Multi-tenant enforcement | Workspace isolation across **every** query path, not just the ones already checked. A scan in workspace A is invisible to workspace B, including through list, detail, findings, and report endpoints. | `[ ]` |
| 3.2 | Identity | Google OAuth for humans, hashed API keys for machine clients. | `[ ]` |
| 3.3 | Daily update checks | Check-only, every 24 h. Production dependencies are **not** upgraded automatically — upgrades go through gated CI. | `[ ]` |
| 3.4 | Authorised scanning scope | Bug-bounty / airdrop scope ingestion with safe-harbour rules, plus responsible-disclosure gating. Public-chain reads may be automated; transactions, exploit execution, and disclosure submission require explicit authorisation. | `[ ]` |
| 3.5 | Report as a first-class artifact | The generated PDF is stored as a scan artifact with its own sha256, so a report can be proven to be the one that was issued. | `[ ]` |
| 3.6 | Repository-wide formatting | `ruff format` has never been run over the whole repository: 44 committed files are still unformatted. `ruff check` and `mypy` are clean, so this is cosmetic, but it should be one mechanical pass of its own rather than mixed into a feature commit. | `[ ]` |
| 3.7 | Windows history migration | The Windows development database holds 12 scans, 10 scan jobs, 38 findings, 3 feed cursors and 1 discovery run. The WSL database has the schema but no rows. Moving the history is a separate decision, and deleting the Windows working copy is another. | `[ ]` needs the user's decision |
| 3.8 | Migration-vs-model diff over every table | `tests/api/test_migration_contract.py` applies the real migration chain and checks the one constraint that bit us. A general autogenerate diff would catch the next column width, index, or constraint that exists only in a migration and is therefore invisible to the suite. | `[ ]` |

---

## 4. Blocked on external inputs

These need something only the user can supply. They are listed here so they do
not look forgotten.

| # | Item | What is needed | From whom | Unblocks |
|---|---|---|---|---|
| 4.1 | Real Netlify deployment | A Netlify account, and the public backend URL to set `NEXT_PUBLIC_API_BASE_URL` to | User | §2.2 |
| 4.2 | Real VPS provisioning | A Linux VPS with a hostname/IP and SSH access | User | §2.3, §2.4, §2.1 |
| 4.3 | Corpus redistribution terms | Confirmation that SmartBugs Curated / DeFiHackLabs derived artifacts may be redistributed in a commercial product, and the Web3Bugs per-repository licence audit | User / legal | §1.1.10 |
| 4.4 | Slither AGPL network clause | Legal review of the AGPL-3.0 network clause for a commercial multi-tenant SaaS, given Slither runs out-of-process | Legal | Commercial launch |
| 4.5 | Netlify / VPS CORS origins | The final deployed origins | User | §2.2, §2.3 |

---

## 5. Definition of done

An item counts as done only when **all** of these hold:

1. The code is committed on `master` and pushed to the private remote.
2. The change is covered by tests, and those tests pass.
3. Ruff and mypy (strict) are clean over the touched paths.
4. The full suite passes with the isolated PostgreSQL cluster on `5433` up —
   and the cluster is stopped again afterwards.
5. The frontend gate passes if the frontend was touched (`vitest` + `tsc --noEmit`).
6. `docs/WORK-TRACKER.md` is updated: the item is ticked, the commit recorded,
   and the remaining list refreshed.
7. Any behaviour that a human could get wrong — a trap, a false-clean, an
   inverted exit code — is documented in an ADR or the runbook, not only in a
   test.
8. The behaviour is exercised **live** against the running product, not only
   against a test double.

---

## 6. Completed

Moved here as it lands. Each entry names the commit and how it was verified.

| Item | Commit | Verification |
|---|---|---|
| 1.1.1 – 1.1.9 dataset ingestion machinery | `54fced8` | `evm_dataset` installed editable; its own test module; licence, tier, dedup, family, split, manifest and promotion behaviour each covered by tests. |
| 1.2.1 – 1.2.8 Mythril as a manual action | `54fced8` | Live: the action returns `202` and says only *queued*; the dedicated worker runs the external executable and stores findings with `source="mythril"`. On Windows, where Mythril is not installed, the same path records the honest skip `mythril_not_installed` instead of a clean verdict. |
| 1.3.1 – 1.3.6 deterministic PDF reporting | `54fced8` | Live: the report endpoint serves a PDF with an `X-Report-SHA256` header; the renderer pins its metadata and uses ReportLab's invariant mode, so identical evidence renders byte-identically. |
| 1.4.1 – 1.4.4 correspondence as a stored service | `54fced8` | Live: USDC established — `FiatTokenProxy.sol`, solc `0.4.24+commit.e67f0147` — with the proof stored against the scan and readable from the scan detail. |
| 1.2.7 persisted with provenance | `49e248e`, `e8d6269` | Live in WSL: Mythril ran on the runtime bytecode of a known reentrancy fixture, produced **SWC-105 High** and **SWC-114 Medium**, and both findings are stored with `source="mythril"`. Two database defects stood in the way and both are fixed — see §6.1. |
| 1.2.7 no-verdict rule for a lost verdict | `49e248e` | When storage refuses a finding, the worker records `findings_persist_failed` with the number of findings lost. A verdict that is computed and then discarded must never read as a clean contract. |
| Migration contract | `e8d6269`, `c00be88` | `findings.source` is widened by its own revision `f7d9a3c1e5b2` — a revision is never re-run, so editing an applied one would have fixed only fresh databases — and the constraint is dropped by the name it actually has. `tests/api/test_migration_contract.py` applies the real migration chain and compares the result with `FINDING_SOURCES`. |
| The `scan_jobs.job_type` width fix | `54fced8` | `VARCHAR(12)` could not hold `correspondence` (14 characters). The migration widens it to `VARCHAR(14)` and removes the new job rows before narrowing it again on downgrade. |
| The artifact storage-root fix | `54fced8` | The root was relative, so the API wrote artifacts in one directory and the workers read from another, and every worker-side artifact read failed as if the file had never been stored. It is now resolved against the repository root, with a regression test that fails if two processes disagree. |

---

### 6.1 Defects found by proving it live (2026-10-29)

The pending work was proved against the real stack, with the real database,
rather than only in the test suite. Three defects showed up that the suite
could not see, because the suite builds its schema from `Base.metadata` and
anything a migration adds on top of that is invisible to it.

| Defect | What happened | Fix |
|---|---|---|
| Relative artifact root | The API stored artifacts in one directory and the workers looked in another, so every worker-side artifact read failed as if the file had never been written. | The root resolves against the repository root; `tests/unit/test_storage_root.py`. |
| `scan_jobs.job_type VARCHAR(12)` | `correspondence` is fourteen characters and did not fit. | Widened to `VARCHAR(14)`; the new job types' rows are removed on downgrade. |
| `findings.source` CHECK constraint | Mythril found SWC-105 High and SWC-114 Medium and the database refused both rows. The verdict was discarded and the contract looked exactly like one Mythril never examined. | The constraint is widened — not dropped — by its own revision `f7d9a3c1e5b2`; the worker records `findings_persist_failed` when storage refuses a verdict. |

Three lessons came out of it and are now in the code rather than in a
notebook: a migration is never re-run, so a fix needs its own revision; a
constraint's name is not a constant, because the naming convention rewrites
it, so the name is looked up; and the AGPL guard reads an identifier as
code, so the canonical set of provenances is a tuple of string literals.

---

## 7. How this document relates to the others

| Document | Scope |
|---|---|
| `docs/WORK-TRACKER.md` | The running log: what is done, in what order, with what result. |
| `docs/NEXT-ROUND-PLAN.md` | The narrative plan for the round that followed the original build. |
| `docs/runbook.md` | How to operate the thing: commands, ports, the manual Mythril workflow, the correspondence check. |
| `docs/adr/` | Decisions and their reasons. Each ADR is immutable once landed; corrections amend the ADR in place with a note. |
| `docs/PENDING.md` (this file) | What is left, with acceptance criteria. |
