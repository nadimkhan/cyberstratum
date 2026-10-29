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

| # | Item | Acceptance criterion |
|---|---|---|
| 1.1.1 | Licence + provenance record per dataset | Every dataset carries an SPDX-ish licence id, licence URL, upstream URL, upstream revision, redistribution terms, and a human note. Known: SmartBugs Curated `Apache-2.0`, DeFiHackLabs `Apache-2.0`, SWC Registry `MIT`. Web3Bugs is representable but flagged `per_repository_audit_required` so it can never be treated as one licence. |
| 1.1.2 | Label tiers | `heuristic` / `reviewed` / `unlabelled`. A missing, unknown, or `not-yet-determined` label is **`unlabelled`, never a negative**. A function states whether a tier may serve as a supervised negative. |
| 1.1.3 | Exact dedup | sha256 over raw bytes. Stable across runs and machines. |
| 1.1.4 | Normalised dedup | Comments stripped, whitespace collapsed, string literals minimally normalised, then hashed. Insensitive to comment/whitespace edits where the exact hash is sensitive. |
| 1.1.5 | Near-duplicate detection | A deterministic similarity signature and clustering at a documented threshold. Must not use `hash()` or unseeded `random` — the hash has to be reproducible on another machine in another year. |
| 1.1.6 | `family_key` | Two variants of the same project share a family key, so they cannot straddle a split. |
| 1.1.7 | Family-level splits | Train/validation/test assigned **by family**. No family appears in two splits. Deterministic for a given seed. Every record lands in exactly one split. An empty split is a clear error, not a silent zero. |
| 1.1.8 | Immutable content-addressed manifest | Manifest hash over a canonical serialisation (sorted keys, fixed separators, sorted record ids). Regenerating from identical inputs yields an identical hash. No wall-clock time, no absolute paths inside the manifest. `verify_manifest` detects a tampered record. |
| 1.1.9 | Promotion gate | Promotion is permitted **only** from `reviewed` labels, and returns a structured decision with a reason string — not a bare bool. Heuristic and unlabelled data may be used for exploratory training but cannot promote a model. |
| 1.1.10 | Actual corpus ingest | Fetch SmartBugs Curated and DeFiHackLabs, load the SWC Registry as taxonomy + join key, and audit Web3Bugs per repository. **Blocked until the licence terms are confirmed for redistribution of derived artifacts — see §4.** The machinery must exist and be exercised against the smoke corpus regardless. |

### 1.2 Mythril as a manual, on-demand action

Mythril is manual-only by decision (ADR-0014): it is slow, and its real-runtime
cost on a production contract exceeded a bounded budget with no verdict. It
must never join the default scan.

| # | Item | Acceptance criterion |
|---|---|---|
| 1.2.1 | Out-of-process runner | Mythril is invoked as an unmodified external executable over a process boundary. Never imported, never added to the app venv. The AGPL boundary guard must still pass. |
| 1.2.2 | **Inverted exit code** | Mythril exits `1` when it finds issues and `0` when it finds none. The verdict comes from the JSON envelope. The exit code is used **only** to detect a process that died without a verdict. A runner that maps non-zero to "failed" discards every genuine result. |
| 1.2.3 | **Creation-vs-runtime trap** | Feeding creation bytecode to `--bin-runtime` returns `{"error": null, "issues": [], "success": true}` with exit `0` — a silent false clean. The action must take runtime bytecode explicitly, detect creation code, and **refuse loudly** with a distinct reason. |
| 1.2.4 | Envelope validated first | `success: false` with empty issues is an **error**, not a clean result. Non-JSON output, a crash, a timeout, and a missing binary are all *no verdict*. Only `success: true` with zero issues is clean. |
| 1.2.5 | Binary name | The console script is `myth`, not `mythril`. Path configurable; a missing binary yields a clear skip reason, not an exception. |
| 1.2.6 | API + own queue | An endpoint to trigger a Mythril run on demand, on a **separate queue** with an explicit long budget. It is never part of a default scan. |
| 1.2.7 | Persisted with provenance | Findings are stored with `source="mythril"` so the unified findings view can distinguish them. The no-verdict rule applies to Mythril exactly as to every other engine. |
| 1.2.8 | Frontend action | A button on the scan detail page, showing the run's state and its verdict — including "no verdict" when that is the truth. |

### 1.3 Deterministic PDF reporting

A disclosure report has to be reproducible: the same evidence must yield the
same document, so a reviewer can confirm the document matches the evidence.

| # | Item | Acceptance criterion |
|---|---|---|
| 1.3.1 | Deterministic renderer | ReportLab with invariant rendering. **Two renders of identical evidence produce a byte-identical SHA-256.** No wall-clock timestamp, hostname, or random id in the output unless explicitly supplied by the caller. Document metadata pinned to constants. |
| 1.3.2 | Evidence rendering | Bytecode evidence (offset/PC, opcode, instruction sequence, CFG path, reachability) and source evidence (path + line) rendered as clearly different kinds. |
| 1.3.3 | Source lines only when proven | A source path and line appear **only** when source-to-bytecode correspondence was actually proven. Otherwise the report says the finding is bytecode-only and claims no source line. |
| 1.3.4 | Per-engine breakdown | Which engines ran and which did not. An engine with no verdict reads as **"no verdict"** — never "clean" or "passed". Skip reasons are shown verbatim. |
| 1.3.5 | Provenance section | Tool versions (parser, ruleset, model, external engines), dataset manifest id/hash, model manifest id/hash, correspondence proof status. A missing value renders as "not available" — never omitted silently, never fabricated. |
| 1.3.6 | Limitations block | The report states that it presents evidence collected by automated analysis, does not assert exploitability, and that absence of findings is not proof of absence of vulnerabilities. |

### 1.4 Source ↔ bytecode correspondence as a stored service

The proof works and is scripted (`scripts/live_check_correspondence.py`,
verified live on both Windows and WSL: USDC, executable code byte-identical over
2,143 bytes, 807 instructions, 4/4 interesting opcodes mapped to exact source
lines). It is not yet part of the product.

| # | Item | Acceptance criterion |
|---|---|---|
| 1.4.1 | Stored proof | The proof is stored alongside the scan, with the compiler version, the executable-byte comparison result, the metadata difference, the instruction count, and the PC→line mapping. |
| 1.4.2 | Three-state outcome | `0` established or skipped · `1` a real mismatch · `2` the check could not be performed (compiler hung, crashed, or emitted non-JSON). Exit `2` is **never** reported as a mismatch. |
| 1.4.3 | Feeds the report | The stored proof feeds §1.3 — it is the reason a source line may or may not be claimed. |
| 1.4.4 | Metadata-aware gate | Equality is judged on **executable code**, not the whole runtime: Solidity's metadata hash legitimately differs. Constructor-set immutables are masked or proven, never silently ignored. |

---

## 2. P1 — deployment

| # | Item | Acceptance criterion |
|---|---|---|
| 2.1 | Model artifact serving on the VPS | The ML model and its manifest are served by the backend, and their hashes appear in the report's provenance section. |
| 2.2 | Real Netlify deployment | A live site on the **Next.js runtime** (not static export — the frontend does server-side live API reads). `NEXT_PUBLIC_API_BASE_URL` set as public build config; `API_KEY` stays server-only and is never renamed to `NEXT_PUBLIC_API_KEY`. |
| 2.3 | Real VPS provisioning | The backend, PostgreSQL, Redis/worker, and ML model running on a Linux VPS via the hardened systemd units. `CORS_EXTRA_ORIGINS` set to the deployed Netlify origin. |
| 2.4 | Alembic on the VPS | `alembic upgrade head` verified on the real database, with a tested downgrade path. |

**Already done:** the Netlify Next.js runtime config, the hardened systemd
units, the VPS deploy script, the Alembic migration path, and the multi-origin
CORS configuration all exist and are verified. Only the *real* deployments
remain, and both are blocked on credentials — §4.

---

## 3. P2 — platform hardening

| # | Item | Acceptance criterion |
|---|---|---|
| 3.1 | Multi-tenant enforcement | Workspace isolation across **every** query path, not just the ones already checked. A scan in workspace A is invisible to workspace B, including through list, detail, findings, and report endpoints. |
| 3.2 | Identity | Google OAuth for humans, hashed API keys for machine clients. |
| 3.3 | Daily update checks | Check-only, every 24 h. Production dependencies are **not** upgraded automatically — upgrades go through gated CI. |
| 3.4 | Authorised scanning scope | Bug-bounty / airdrop scope ingestion with safe-harbour rules, plus responsible-disclosure gating. Public-chain reads may be automated; transactions, exploit execution, and disclosure submission require explicit authorisation. |
| 3.5 | Report as a first-class artifact | The generated PDF is stored as a scan artifact with its own sha256, so a report can be proven to be the one that was issued. |

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

---

## 6. Completed

Moved here as it lands. Each entry names the commit and how it was verified.

| Item | Commit | Verification |
|---|---|---|
| — | — | Pending: the 2026-10-29 round is in flight. |

---

## 7. How this document relates to the others

| Document | Scope |
|---|---|
| `docs/WORK-TRACKER.md` | The running log: what is done, in what order, with what result. |
| `docs/NEXT-ROUND-PLAN.md` | The narrative plan for the round that followed the original build. |
| `docs/runbook.md` | How to operate the thing: commands, ports, the manual Mythril workflow, the correspondence check. |
| `docs/adr/` | Decisions and their reasons. Each ADR is immutable once landed; corrections amend the ADR in place with a note. |
| `docs/PENDING.md` (this file) | What is left, with acceptance criteria. |
