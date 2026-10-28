# Next round: engine portfolio, datasets, updates, mainnet scanning, and disclosure reports

Status: **Design decided, nothing implemented yet.** This document answers the
four questions and records what was measured to answer them.

Decision records: ADR-0014 (engines), ADR-0015 (datasets and model lifecycle),
ADR-0016 (update policy), ADR-0017 (evidence model and correspondence),
ADR-0018 (scanning and disclosure), ADR-0019 (PDF reporting).

---

## 1. "The system is fully dependent on Slither — we need Mythril and more"

**First, the premise is wrong: the platform is not dependent on Slither.**
CyberStratum's own bytecode engine already produces six findings classes with
zero Slither involvement — call-then-storage-write, delegatecall, selfdestruct,
tx.origin, dynamic jumps, stack underflow — and it is the licence-clean
primary path. Slither is a second opinion on verified source, not the detector.

That said, the request is right that one source-level engine is thin. Slither
is pattern-oriented; it cannot prove an exploit path, and it cannot analyse an
unverified deployment at all.

### What was measured

| Engine | Licence | Verdict |
| --- | --- | --- |
| **Slither 0.11.6** | AGPL-3.0 | Already integrated, out-of-process, 122/122 detectors mapped |
| **Mythril 0.24.8** | MIT | **Admitted** — first symbolic engine |
| Echidna / Halmos / Medusa / Manticore | varies, some AGPL | Deferred — different class (property/fuzzing), needs harnesses + corpora |
| Aderyn / Wake / Solhint / Semgrep | MIT / LGPL rules | Rejected for the analysis path — duplicate coverage, no incremental value |
| Your bytecode engine | ours | The primary path. Not a dependency on anything |

### Mythril, concretely

- **It cannot run in the app's Python 3.14 environment.** Its
  `z3-solver<=4.12.5.0` pin has no clean 3.14 path. It is isolated in WSL
  Ubuntu at `~/venvs/mythril` and invoked out-of-process, exactly like Slither.
- **Output shape is `{"error", "issues", "success"}`** — *not* the older
  `vulnerabilities` key. Easy to get wrong.
- **Source mode** returns `swc-id`, `title`, `severity`, `filename`, `lineno`,
  `function`, and the offending source text. Verified on a live fixture:
  `swc-id 107`, `lineno 9`, `function withdraw(uint256)`.
- **Raw-runtime mode** (`-c <hex> --bin-runtime`) analyses **unverified
  deployed bytecode** and returns the same shape plus a `tx_sequence` proving
  the exploit path. Verified on a real compiled runtime: it found
  *Unprotected Ether Withdrawal* (SWC-105, High) with a full exploit sequence.
- **Cost is the real constraint.** A 40-line fixture in source mode took
  **109 seconds**. Real USDC runtime bytecode in raw mode ran **past 850
  seconds** without producing output. Mythril on production contracts needs a
  hard time budget, an execution sandbox and cancellation — it is an
  on-demand deep analysis, **not** a default scan step.

### The rule that prevents tool bloat

Every engine must clear six gates before it ships: licence, runtime,
determinism, resource ceiling, **measurable incremental coverage on the same
labelled corpus**, and normalisation into the shared finding model. Popularity
is not evidence. An engine that finds nothing new on our corpus does not get
an engine slot.

### One contract for all engines

Each engine exposes `engine_id`, `engine_version`, `mode` (source/bytecode),
`command`/`toolchain`, normalised findings, `status`
(`completed`/`skipped`/`failed`/`timeout`), and `limits`. Engines never import
into the app and never write to the database. Missing tool, failed compile,
malformed output and timeout are **explicit skips**, never silent failures —
that behaviour already exists in the Slither runner and Mythril plugs into it.

---

## 2. Datasets, ML model updates, and library updates

### Datasets — measured licences and roles

| Source | Licence | Role |
| --- | --- | --- |
| **SmartBugs Curated** | Apache-2.0 | **Primary evaluation corpus.** Pre-labelled, SWC+CWE IDs, stable `vulnerabilities.json` schema |
| **DeFiHackLabs** | Apache-2.0 | Real exploit PoCs — recall measurement + regression fixtures |
| **SWC Registry** | MIT | Weakness taxonomy and canonical join key |
| **Web3Bugs** | mixed per repo | Only after per-repo licence + label audit. `not-yet-determined` rows are **not** negatives |
| **solidity-advisories** | — | Severity priors and descriptions, not a labelled set |
| Our own findings | — | The long-term moat — unreviewed findings quarantined, never auto-promoted |

### Ingestion rules

Pin the commit SHA (never a branch) → record the licence per source file →
parse into one canonical schema → deduplicate (exact, then normalised, then
near-duplicate) → **assign `family_key` → split by family, never by record** →
write an immutable content-addressed manifest.

A family split is the whole game. If a variant of a training exploit lands in
the test set, the reported accuracy is fiction and a customer will find out on
their own data.

### Label tiers

- `reviewed` — human-confirmed. Trainable and evaluable.
- `heuristic` — transparent rule-derived. Trainable with the rule recorded,
  **never** evaluation ground truth. The current smoke dataset sits here and
  is explicitly not a benchmark.
- `unreviewed` — quarantined. Not trainable, not evaluable.

### "The model should be updated regularly"

Daily retraining on unreviewed findings is rejected — the model would chase
its own noise, and a model that changes daily cannot be referenced in a
reproducible report or defended to a customer. Instead:

- **Daily** — ingest into quarantine, produce a *candidate* dataset and
  *candidate* model, do not promote.
- **Weekly** — scheduled retrain from the reviewed corpus.
- **Event-triggered** — retrain when a reviewed batch lands above a threshold
  (e.g. 50 new reviewed records or a whole new family set).
- **Promotion gate** — a candidate becomes the served model only if it beats
  the current model on the held-out family-split set, regresses on no
  previously passing class, and the evaluation is reproducible from the
  manifest.

Every model carries a **model manifest**: dataset manifest SHA, feature schema
version, hyperparameters, seed, train metrics, eval metrics, code revision.

### "All libraries updated every 24 hours"

**Check daily, upgrade through CI.** The daily job reads release metadata and
writes a report; it never mutates the environment.

Verified working endpoints:
- PyPI `https://pypi.org/pypi/{package}/json` → `latest`, `requires_python`,
  licence expression
- npm `https://registry.npmjs.org/{package}` → `dist-tags.latest`
- solc release list at `binaries.soliditylang.org`

**A licence-expression change escalates immediately** — a dependency silently
becoming AGPL is a legal event, not a routine bump.

Why auto-upgrade was rejected: an automatic Slither bump changes the detector
set and silently invalidates our 122-detector mapping and every customer-visible
finding; a Mythril transitive bump can break the Z3 build and take out the
symbolic engine; a bump that shifts disassembly output breaks the
reproducibility of every stored artifact; and an automatic upgrade that breaks
the worker at 03:00 takes down every customer's scan queue with no rollback.

Upgrades go through: branch → full quality gate → **engine output diffing**
(same corpus, before/after finding-set comparison; any disappearance or
severity change is a breaking change that blocks the merge) → model
revalidation → bytecode-artifact reproducibility check → merge with the
last-known-good version pinned for rollback. Production versions stay pinned.

---

## 3. Mainnet / airdrop / bounty scanning — and "code or bytecode?"

### The two kinds of work

- **Reading public chain state** — public, permissionless, already published.
  Scanning it is analysis. The discovery feed already does this across 60
  chains (54 with a usable route).
- **Sending transactions** — writing to a chain, i.e. interacting with
  somebody else's system. Not covered by "the data is public".

Programmes publish scope, in-scope assets, rules of engagement and a
safe-harbour statement. Safe harbour is conditional on **both** staying in
scope *and* following the reporting procedure. Programmes also typically
require a working proof of concept, not just scanner output — an
undemonstrated automated finding is noise, and submitting noise burns
credibility with that programme. Airdrops additionally commonly prohibit test
traffic, and automated interaction can forfeit eligibility.

**Decision:** continuous read-only discovery and read-only scanning are in
scope now. Automated submission is out — a human reviews and sends every
report. Sending transactions to live projects to test findings is out. Fuzzing
or PoC execution against live mainnet is out; our analysis is static and does
not need to touch a live contract. Airdrop participation is not a scanning
strategy and we will not probe airdrop infrastructure.

The airdrop goal, read properly, is *find vulnerabilities in projects that have
airdrops*. We can serve that by scanning those projects' contracts; the
airdrop itself is irrelevant to the analysis, and its ban on test traffic is
exactly why we stay read-only.

### "Either through code or through the bytecode" — it is **both**, in a defined order

| Contract state | Paths run | Evidence produced |
| --- | --- | --- |
| Verified, correspondence chain completes | Source **and** bytecode, cross-checked | `source_line` **and** `bytecode_offset` **and** `source_bytecode_correlation` |
| Verified, correspondence chain fails | Source only | `source_line`, with the limitation stated |
| Unverified | Bytecode only | `bytecode_offset`, `bytecode_pc`, `cfg_edge` |

The bytecode pass always runs — it analyses what is actually *deployed* and
catches what the source view misses (proxy/admin issues, immutable values,
source-vs-deployment divergence). The source pass adds the line numbers. The
correspondence chain, when it completes, lets us state that the deployed bytes
*are* the compiled form of the line we are pointing at.

### The correspondence chain — all five links, proven live

1. Fetch verified source **and the exact compiler input** from Sourcify
   (compiler version, optimiser settings, `evmVersion`, literal source).
2. Recompile with **that exact compiler**.
3. Require byte-for-byte equality with the deployed runtime. **This is the
   gate** — if it fails, the source does not describe the deployment and
   **no source line may be claimed**.
4. Source map → instruction index (entries are instruction-indexed; empty
   entries inherit the previous range).
5. PC/offset → file and line.

**Measured on live USDC (`0xa0b8…eB48`, Ethereum):**

- On-chain runtime **2186 bytes** from a public RPC.
- Sourcify match 1532018, compiler `0.4.24+commit.e67f0147`, source
  `FiatTokenProxy.sol`.
- Recompiled with local `solc-0.4.24`: **code identical** — 2143 bytes,
  byte-for-byte — once the metadata trailer is stripped.
- The **only** difference is the metadata trailer's IPFS hash. This is exactly
  why the platform separates metadata from executable code: the metadata hash
  embeds the compiler build and source hash, so it can differ between two
  otherwise identical builds. A naive whole-hex comparison would produce a
  **false negative** on real deployments.
- 807 instructions disassembled from the on-chain runtime, mapping to source
  positions.

**Where it legitimately fails:** contracts using Solidity `immutable` embed
constructor-set values in the runtime, so a recompile differs in the immutable
slots — measured **617 differing bytes** on the Uniswap V3 UniversalRouter
runtime. The correct handling is to mask immutable slots and say so in the
evidence, not to silently drop the finding.

### Evidence types are explicit

`source_line` · `bytecode_offset` · `bytecode_pc` · `cfg_edge` ·
`source_bytecode_correlation`.

A bytecode-only finding **cannot** be given a source line. Doing so would be a
fabrication, and in a disclosure email that is precisely the failure that
destroys credibility. Severity and confidence stay separate fields, and every
finding carries a `limitations` string stating what the evidence does and does
not establish — no claim of exploitability, no claim of certainty, no claim of
production reachability.

---

## 4. PDF reports

**ReportLab 5.1.0** — BSD licence, pure Python, imports cleanly on Python
3.14, no browser dependency.

Determinism is verified: `canvas.Canvas(..., invariant=True)` with stable
metadata produced **two byte-identical PDFs with the same SHA-256**. The
generation timestamp is passed in from the persisted scan record rather than
embedded from the wall clock, so the same evidence always yields the same
bytes and the PDF's hash can be recorded next to the finding.

WeasyPrint (Pango/cairo/GTK), xhtml2pdf, fpdf2 and Playwright were evaluated
and rejected — system dependency weight, or a full browser per report.

The report is generated from persisted evidence only, and never recomputes or
guesses. Sections: summary · scope (which engines ran, which were skipped and
why, whether correspondence completed) · contract identity (address, chain,
block, runtime hash, compiler, metadata compiler, verification state) ·
findings with severity, confidence, evidence type, exact location, offending
source or instruction sequence, producing tool and version, and limitations ·
reproduction commands · correspondence proof · disclosure status.

Architecture: a pure `ReportModel` (data only) → a ReportLab renderer, so the
content rules are testable without rendering and can later drive HTML or JSON
without duplicating them.

---

## Implementation order (for when we proceed)

1. **Engine plugin contract** — refactor the Slither runner into the generic
   external-engine contract; add Mythril as the first non-Slither engine with
   WSL isolation, a hard time budget and cancellation.
2. **Correspondences service** — Sourcify fetch → exact compiler → recompile →
   byte-equality (metadata-aware, immutable-aware) → source map → PC/line.
   Persist the proof; add `source_bytecode_correlation` as a finding evidence
   type.
3. **Report service** — `ReportModel` + ReportLab renderer +
   `GET /api/v1/scans/{id}/report.pdf`, with the artifact hash stored.
4. **Dataset ingestion** — manifest builder, licence recording, family
   grouping, family-split, immutable manifests; SmartBugs first.
5. **Update monitor** — the daily read-only report job (PyPI/npm/GitHub/solc),
   with licence-change escalation.
6. **Discovery at scale** — schedule the existing feed across the 54 working
   chains; add the per-programme scope registry.
7. **Model promotion pipeline** — candidate training, held-out evaluation,
   promotion gate, model manifests.

Nothing above has been implemented. The services you started are untouched.
