# CyberStratum — Work Tracker

**Purpose:** a single persistent record of what is done and what remains.
Update this file after every completed task. Mark the item done, note the commit,
and update the "Remaining" list so the next session knows exactly where to resume.

**Last updated:** 2026-11-13
**Latest commit:** `e05c78b` — *feat: every finding now carries the advice that says what to do about it*
**Feature commit:** `54fced8` — *feat: manual Mythril, correspondence proof service, dataset ingestion, deterministic reports*

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
- [x] Mythril's two remaining traps measured: exit `1` means *findings*, not failure; creation bytecode analysed as runtime returns a silent false clean. Binary is `myth`, not `mythril`. Documented in ADR-0014 and the runbook section 6.3.
- [x] ReportLab deterministic PDF — two renders of identical evidence → byte-identical SHA-256.
- [x] Correspondence proof re-verified end to end as a repo script — `scripts/live_check_correspondence.py`. USDC: executable code byte-identical (2143 bytes), metadata trailer differs only in its 32-byte `bzzr0` hash, 807 instructions, 4/4 interesting opcodes mapped to exact source lines.
- [x] Correspondence proof reproduced natively in WSL — same 807 instructions, same 4/4 opcode-to-source-line mappings. WSL solc `0.4.24` and `0.8.26` installed into the `solc-select` layout so the product's compiler discovery finds them there too (previously WSL had them only in `~/bin`, where discovery could not see them).
- [x] Two Sourcify traps found and documented — the stored `stdJsonInput` has **no** `outputSelection`, so solc emits no bytecode and the check falsely reports "no match"; and the gate must be metadata-aware executable-code equality, not whole-byte equality.

### Pending-list completion — 2026-10-29 (`54fced8`)
- [x] **Dataset ingestion machinery** — a separate licence-clean distribution
      `packages/dataset_ingest` (`evm-dataset` / `evm_dataset`), installed
      editable. Licence + provenance records, label tiers
      (`heuristic`/`reviewed`/`unlabelled`, and an unknown label is never a
      negative), exact + normalised + near-duplicate detection, `family_key`,
      family-level splits, immutable content-addressed manifests, and a
      promotion gate that only accepts reviewed labels.
- [x] **Mythril as a manual action** — out-of-process runner with the exit-code
      inversion and the creation-vs-runtime false clean handled explicitly; its
      own queue, worker and systemd unit; a `202`-only API endpoint; a button on
      the scan detail page; findings persisted with `source="mythril"`; a run
      that learned nothing records a skip reason and is never presented as clean.
- [x] **Correspondence proof as a stored service** —
      `apps/api/app/services/correspondence.py`: Sourcify standard-JSON input,
      metadata-aware executable-code comparison, source-map expansion. Its own
      queue, worker and systemd unit, a `202`-only endpoint, a button, and a
      first-class `correspondence_proofs` table linked to the scan. Four
      outcomes — `established` / `skipped` / `mismatch` / `unavailable`.
- [x] **Deterministic PDF reporting** — ReportLab in invariant mode, evidence
      kinds kept apart, source lines only where correspondence is proven,
      per-engine verdicts that read as "no verdict" when that is the truth, and a
      limitations block. Served by the API and proxied through a Next.js server
      route so the API key stays server-only.
- [x] **Migration** — `e2f5a1b9c740` adds the Mythril status columns and the
      `correspondence_proofs` table, and widens `scan_jobs.job_type` from
      `VARCHAR(12)` to `VARCHAR(14)` because `correspondence` is 14 characters.
      Round trip proven on the isolated `5433` cluster: upgrade → head →
      downgrade `-1` → upgrade head again, every step exit `0`.
- [x] **Two real defects found by proving it live** — see §11.

### Live-proof round — 2026-10-29 (`49e248e`, `e8d6269`, `c00be88`)
Proving the pending work end to end, rather than only in tests, found three
defects that the suite could not see. All three are fixed and all three are
now covered by a test that fails without the fix.

- [x] **Artifact root** — a relative `OBJECT_STORAGE_ROOT` was resolved
      against each process's working directory, so the API wrote artifacts
      one place and the workers looked in another. Every worker-side
      artifact read failed as if the file had never been stored. Now
      resolved against the repository root; `tests/unit/test_storage_root.py`.
- [x] **`scan_jobs.job_type VARCHAR(12)`** could not hold `correspondence`,
      which is fourteen characters. Widened to `VARCHAR(14)`, with the rows
      that use the new job types removed on downgrade.
- [x] **`findings.source` CHECK constraint** allowed only `rule`, `slither`
      and `ml`. Mythril ran, found SWC-105 **High** and SWC-114 **Medium**,
      and the database refused to store either one. The engine's verdict was
      discarded and the contract looked exactly like one Mythril never
      examined. The constraint is widened — not dropped — by its own
      revision `f7d9a3c1e5b2`, and the worker now records
      `findings_persist_failed` instead of losing a verdict silently.
- [x] **The constraint's name is not the same everywhere** — one database
      has it as `source`, another as `ck_findings_source`, because the
      project's naming convention rewrites it. The revision looks the name up
      in `pg_constraint` and drops what is actually there.
- [x] **A migration is never re-run** — the first attempt edited a revision
      that had already been applied to the development databases, so the
      fix would have existed only on a database built from scratch. The
      change has a revision of its own.
- [x] **The migration contract is now a test** —
      `tests/api/test_migration_contract.py` applies the real migration
      chain to the test database and compares the resulting constraint with
      the set of provenances the code writes (`FINDING_SOURCES`).

### Deployment configuration (done earlier, `835ce16`)
- [x] Netlify config for the Next.js frontend — Next.js runtime, publish `apps/web/.next`.
- [x] Frontend API base URL is public build config; `API_KEY` stays server-only.
- [x] VPS deployment script + hardened systemd units for the API and the worker.
- [x] Alembic migration path verified (`upgrade → downgrade → upgrade`) on WSL.
- [x] CORS for the Netlify origin — `WEB_BASE_URL` + `CORS_EXTRA_ORIGINS`.

---

## 3. Remaining — ordered by priority

### P0 — dataset corpus
- [ ] Ingest SmartBugs Curated (Apache-2.0) as the primary evaluation corpus.
      **The machinery is done; the fetch and the redistribution terms are not.**
- [ ] Ingest DeFiHackLabs (Apache-2.0) for exploit PoCs.
- [ ] Load SWC Registry (MIT) as weakness taxonomy + join key.
- [ ] Audit Web3Bugs per-repository — `not-yet-determined` labels are NOT negatives.
- [x] Record licence + provenance + redistribution terms per dataset.
- [x] Label tiers: heuristic / reviewed / unlabelled, kept explicit.
- [x] Exact + normalised + near-duplicate detection.
- [x] `family_key` assignment; family-level train/val/test splits (no family leakage).
- [x] Immutable content-addressed dataset manifests.
- [x] Model promotion gates (promotion only from reviewed labels).
- [!] The actual corpus fetch is blocked on the redistribution terms — see `docs/PENDING.md` §4.3.

### P0 — deployment for real
- [ ] Model artifact serving on the VPS.
- [ ] Actual Netlify site creation and a real deployment. **Blocked on the account and the public backend URL.**
- [ ] Actual VPS provisioning and a real deployment. **Blocked on a host and SSH access.**

### P1 — platform hardening
- [x] Multi-tenant enforcement — workspace isolation across every query path
      (2026-11-05: 27 isolation tests, every route enumerated from the OpenAPI
      schema; conventions in `docs/PENDING.md` §3.1.1).
- [ ] Google OAuth for humans + hashed API keys for machine clients.
      **ADR-0020 written; the implementation is in flight.**
- [x] Daily dependency update checks (check only; upgrade through gated CI)
      (2026-11-05: `python -m app.cli.update_check` + a systemd timer at 03:17).
- [ ] Authorised bug-bounty scope ingestion + safe-harbour rules.
- [ ] Store the generated PDF as a scan artifact with its own sha256, so a report
      can be proven to be the one that was issued.
- [ ] A migration-vs-model diff over **every** table. The contract test now
      covers the one constraint that bit us; a general autogenerate diff
      would catch the next column width, index, or constraint that exists
      only in a migration.

### P2 — housekeeping
- [ ] `ruff format` over the whole repository. 44 committed files are still
      unformatted; `ruff check` and `mypy` are clean, so this is cosmetic, but it
      wants to be one mechanical pass of its own.
- [ ] Move the Windows development history (12 scans, 10 scan jobs, 38 findings,
      3 feed cursors, 1 discovery run) into WSL, and decide what happens to the
      Windows working copy. Both need the user's decision; neither is urgent.
      The dump/load scripts are prepared (`scratch/wsl/dump_history.sh`,
      `scratch/wsl/load_history.sh`).

### Done in the 2026-11-06 round
- [x] The PDF report is a first-class scan artefact — stored under a
      deterministic key, recorded with its size and digest, and cited by
      `X-Report-SHA256` and `X-Report-Artifact`. The report's own artefact
      row is excluded from the provenance table it prints, so the same
      evidence still renders byte-identically; `tests/api/test_report_artifact.py`
      asserts that, plus that the filed bytes are the served bytes and that
      downloading twice does not accumulate rows.
- [x] `GET /api/v1/models/manifest` — **404** when no model is installed,
      **200** with the manifest and its SHA-256 when one is readable, **503**
      when a model is configured but its manifest cannot be read. A broken
      installation is never reported as an absent model.
- [x] The identity suite no longer depends on a running Redis. The
      revocation list is reached from two call sites — the API's own store
      and the security layer's default store — and the test fake is now
      installed at the Redis client, so both doors open onto one in-memory
      store. Before this, the suite passed with Redis up and failed with
      Redis down, which is a test of the environment, not of the code.
- [x] Repository knowledge graph (Graphify, AST-only, no LLM key needed):
      4,593 nodes, 23,150 edges over 240 source files, with
      `.graphifyignore` keeping virtualenvs, caches, build output and
      runtime data out of the index. The report and the raw graph are
      committed; the extraction cache is not.
- [x] **The graph was describing the project's own test runs.** 3,804 of
      the first graph's 8,351 nodes — 45% — came from `var/`, because the
      application resolves a relative artifact root against the repository
      root, so `var/artifacts` holds real scans and `var/test-artifacts`
      holds the last test run's scans, and the ignore file excluded
      `artifacts/` but not the `var/` tree that contains it. A graph whose
      largest subject is its own output is a graph of nothing.
      `.graphifyignore` now excludes `var/`, and the rebuild left 240
      files and zero runtime artifacts. `graphify update . --force` is
      needed for this: an ordinary update only adds files, and refuses to
      overwrite a graph that came out smaller.
- [x] The skill's own query helper read the Graphify 0.4.x layout
      (`file`, `edges`, `metadata`, a stored `degree`), so against the
      installed 0.8.x graph every count came back zero and every search
      missed. It now reads both layouts, derives degree and communities
      from the graph when they are not stored, and labels communities from
      `.graphify_labels.json`.
- [x] **The product decisions that shape the next round are recorded**:
      every newly verified contract is scanned automatically (not a
      sample); the ML labels come from human triage inside CyberStratum;
      the data sources stay Blockscout-only; and nothing paid is bought.
      The consequences are specific: chain expansion has to be found by
      probing, the queue needs its own limits, and the labels need a
      review surface before any model can be trained on them.
- [x] **The chain list is being widened by probing, because the paid
      Blockscout instance registry answers 402.** `scripts/probe_blockscout_hosts.py`
      reads the public chain registry, derives candidate hosts and asks
      each one, once, a second apart, with a descriptive User-Agent.
      Redirects are followed, `403` is recorded as *unknown* rather than
      *dead*, `429` is honoured, and no credential is ever sent. The
      first batch of 260 hosts found one chain we did not have
      (`rootstock-testnet.blockscout.com`, chain 31) and two of our own
      routes answering `403` from a WAF (`gnosisscan.io`,
      `explorer.immutable.com`) -- recorded, not hidden, because a route
      that is blocked today is a route that fails silently tomorrow.
- [x] **The feed's ordering was measured rather than assumed.** The
      per-chain instance API answers newest-first, with a stable cursor
      (`smart_contract_id`) and one overlapping item between pages. So
      page 1 of each chain catches every new verification, and the older
      tail needs a cursor walk -- two different modes, not one.
- [x] **The analysis fork is now decided, not assumed.** `scans.fork` was
      hard-coded to `cancun`, which is wrong on zkSync, on Fantom and on
      every chain that predates Shanghai, and a wrong fork does not fail
      loudly -- it reports real opcodes as invalid. The bytecode itself
      now bounds the fork: `evm_analysis.fork_inference` computes the
      earliest fork that could execute the code (`PUSH0` -> shanghai,
      `TSTORE` -> cancun, a `PUSH1 0x5f` immediate is not a `PUSH0`), and
      `app.services.fork_resolution` applies the policy: an explicit
      request is honoured even when it is older than the code, because
      asking for an older fork is a deliberate question -- but the
      disagreement is recorded on the scan and printed in the report.
      Revisions `a2c4e6f8b190` (`fork_source`, `fork_conflict`) and
      `b3d5f7a9c281` (`scans_queued`) carry it.
- [x] **The feed now finishes the job it starts.** `app.services.promotion`
      queues a scan for every newly verified contract, skips the ones
      already analysed, looks again only when a contract was re-verified
      (the source may have changed under the same address), and keeps the
      queue inside two limits: a per-cycle cap and a cap on how many
      scans may be waiting. The scans are filed in the product's own
      discovery workspace; promoting a contract into a tenant's workspace
      stays a human decision.
- [x] **The chain list grew by measurement, and two of its entries were
      wrong.** The probe ran 2,460 hosts across two batches at one
      request a second. It found six live Blockscout deployments we did
      not have, and it proved that two we *did* have -- Gnosis and
      Immutable -- answer 403 to every user agent tried, which is the
      same condition as the six chains already documented as blocked.
      Those two were moved to the blocked list rather than left to fail
      quietly at discovery time. The registry now holds 64 chains: 56
      with a working instance, 6 reachable only through PRO, and 2 with
      no route at all. The client also stopped sending
      `python-httpx/0.28.1` as its agent: it now says what it is and
      why it is asking, which changes nothing for the blocked hosts
      (they answer the same either way) and is the right thing to do
      for the ones that do answer.
- [x] **The review surface exists, which is where the labels come
      from.** `POST /api/v1/findings/{id}/review` records the verdict,
      the reviewer, the time and the reason. A false-positive verdict
      without a reason is refused: it cannot be told apart from a
      mistaken verdict, and neither is usable as ground truth. `new` is
      refused too, because it is not a verdict. The reviewer is the
      person behind the key -- the administrative service key has no
      user behind it, so a review made with it records no reviewer
      rather than inventing one. Another tenant's finding is answered
      with 404, so the endpoint never confirms that it exists. Revision
      `c4e6a8b0d392` carries the attribution, with `ON DELETE SET NULL`
      on the reviewer so that deleting a user does not delete the
      record of a judgement they made.
- [x] **The labels now have a screen to be recorded on.** The `/triage`
      queue shows the findings nobody has settled -- new, in triage, or
      waiting for more evidence -- and a confirmed or false-positive
      finding leaves it, because both are finished work. The verdict
      controls say what each verdict means, and the false-positive
      verdict says that a reason is required. The page is server-rendered
      and the controls are a client component, so the service key stays
      on the server and the session cookie stays in the browser.
- [x] **A review that was only flushed was not a review.** The API's
      request-scoped session is *closed*, not committed, when a request
      ends, so the review endpoint's flush was thrown away: the response
      said "confirmed" and the database still said "new". The test suite
      could not see it, because the test session is bound to a
      transaction that is rolled back afterwards, so an
      unflushed-but-visible state looks exactly like a committed one. The
      endpoint now commits, and the new test watches the commit itself --
      it was checked against a deliberate break, failing without the
      commit and passing with it. The end-to-end path is proven against
      the running stack: scan queued, rules report a DELEGATECALL,
      verdict posted through the Next.js proxy, database holding it.
- [x] **The loop closes: a reviewed verdict becomes a training label.**
      `app.services.label_export` turns reviewed findings into a dataset
      the machine learning package can load, and the rules are the point
      of it. A category is true when a finding in it was confirmed and
      false when the findings in it were reviewed as false positives. A
      category with an *unreviewed* finding is unknown, and an unknown
      category keeps the contract out of the training set -- not looked
      at yet is not not vulnerable, and assuming that in the training
      data would be absurd for this product. A detector outside the label
      vocabulary (a stack-depth anomaly, an unresolved jump) is ignored
      rather than disqualifying, so it cannot empty the dataset for no
      gain. The family is the runtime bytecode digest, so exact clones
      group together; the manifest says that near clones do not group
      yet, because a manifest that hides its own weakness is worse than
      no manifest. Proven end to end: a scan queued, two findings
      reviewed (one confirmed, one a false positive with a reason), and
      the export produces a dataset the package loads as one sample with
      `unchecked_call` positive and the reviewed false positive negative.
- [x] **A model may not ship unless its categories earn it.** The
      training pipeline computed precision for every category and wrote
      it into a report; a report is not a decision. `evm_ml.gates` now
      decides, per category, on the validation split: *ship* when the
      precision is at or above the floor with enough evidence to believe
      it, *abstain* when the category is too noisy -- the weights stay in
      the artifact but the model must not speak about that category --
      and *insufficient data* when there are not enough positives to
      measure it, which is not the same as abstaining. The gate also
      chooses a threshold per category: the most conservative one that
      still reaches the floor, which recovers the most recall within it
      while promising the fewest false positives. It is wired into the
      run, not left as a separate step: the manifest records the
      verdict, the model card renders it as a table, and the CLI exits
      non-zero when the model may not be promoted. A run with no
      validation split records "nothing was judged", which is not
      passing. Training against today's reviewed-label dataset therefore
      refuses to promote, and the manifest says exactly why.
- [x] **A finding now says what to do about it.** A detector reports a
      pattern; what a developer needs is what the pattern means, why it
      matters, what to change, and -- the part that saves a reviewer an
      afternoon -- when it is not a problem at all. A model can rank
      findings; it cannot tell a developer how to fix a contract, and it
      must not pretend to. So the solution is its own thing:
      `app.services.knowledge` serves per-detector guidance from a
      versioned data file, so the guidance ships with the code that uses
      it and there is no table to fall out of step. The false-positive
      half is the point: `delegatecall` and `tx.origin` are patterns, not
      bugs, and recording when the pattern is expected is what lets the
      product say "this is expected here" instead of crying wolf. It
      reaches the reader three ways: the PDF report prints a "What this
      means" section per finding, the API serves it at
      `/api/v1/knowledge`, and the tests pin that a detector with no
      guidance gets none -- advice with a missing half is worse than
      silence.
- [x] **The rules now ask what a pattern is used for.** The rules that
      reported the presence of an opcode were the noisiest thing this
      product did: DELEGATECALL is the expected shape of an upgradeable
      proxy, and TX.ORIGIN is harmless in a log line. Reporting either
      without asking what the value is *for* fills a reviewer's queue
      with patterns and teaches them to ignore the tool -- and the one
      true finding in the noise goes with it. `app.services.context`
      tracks, per basic block, where a value came from: a known
      constant, the transaction origin, or something outside the
      contract's control. A DELEGATECALL to a *proven* constant target
      is the expected proxy pattern and is no longer reported; a target
      the analysis cannot resolve -- from calldata, from storage, or
      from an argument frame that underflowed -- is still reported. The
      narrowing is one-sided on purpose. TX.ORIGIN is reported
      confidently when an authorisation-shaped use is located (a
      comparison, or a use as a call target), and with a lower
      confidence, and a limitation that says so, when the use cannot be
      established: a per-block analysis cannot prove a value is not
      compared elsewhere, and dropping those findings would be a false
      negative, which is the worse mistake in a security product. The
      e2e suite caught one such false negative in the narrowing itself:
      an underflowed argument frame was being read as a constant target,
      which would have turned a stack underflow into a false all-clear.
- [x] **The chain registry now has a committed justification.** The
      registry is hand-maintained code; the survey that says which
      instances actually answer was run output living only in gitignored
      runtime space. `docs/chain-probe/survey.json` records the hosts
      that carry a decision, `docs/chain-probe/README.md` explains the
      method and what each outcome means -- a 403 is an instance
      refusing our agent, which is "unknown", not "dead" -- and
      `scripts/summarise_chain_probe.py` regenerates the record and
      cross-checks it against the registry in both directions. The
      cross-check is now a test, so the registry cannot drift away from
      what was probed without failing the suite. It immediately found a
      real gap: Rootstock Testnet had been found live in the first probe
      batch and never added to the registry. The registry now holds 66
      chains -- 58 with a working instance, 6 PRO-only, 2 with no route
      -- and every one of the 58 is confirmed live by the survey.
- [x] **A scan that is gone is information, not an error.** The worker
      logged `scan_not_found` at error level and let the job complete as
      a success. A missing scan is the expected result of a cascade
      delete -- it is what a removed workspace leaves behind -- and
      logging it as an error trains everyone who reads the logs to
      ignore errors. It is now logged at info, and if a job row is still
      standing it is recorded as failed, because the work did not happen
      and the audit trail should not claim otherwise.
- [x] **The working copy is WSL only.** The Windows copy at
      `E:/projects/cyberstratum` is frozen as a fallback and is no longer
      edited: two copies of a live database and two test environments
      produced two different answers to the same question, which is more
      expensive than it looks. Everything from here is committed, tested
      and pushed in `~/projects/cyberstratum`.
- [x] `scripts/wsl/grant_test_privileges.sh` — the schema gate needs
      `CREATEDB` and ownership of the `public` schema, and a cluster this
      project did not initialise grants neither. On WSL the five
      migration-contract tests failed with `permission denied to create
      database` and `must be owner of schema public`: an environment
      fault that read as a code fault, and that the Windows copy hid
      because there the application role had initialised the cluster
      itself. The script uses the isolated cluster's own superuser role,
      which that cluster trusts locally, so it needs neither sudo nor a
      password, and it touches nothing but this project's cluster on 5433.
- [x] A trap worth naming: **a WSL script run as `bash script.sh` is not a
      login shell**, so `~/.local/node/bin` is missing from `PATH`, `npm`
      resolves to the *Windows* npm under `/mnt/d/Program Files/nodejs`, and
      every npm-based gate fails with `WSL 1 is not supported`. The gate is
      fine; the shell was wrong. Run WSL work as `bash -lc 'bash <script>'`
      or export the native Node path first. The same trap is recorded in
      the `background-process-gates` skill. The fix is now executable, not
      just written down: `scripts/wsl/gate.sh` puts the native Node first
      itself, takes each step's exit code from the step rather than from a
      pipe, keeps the logs under `.dev-logs/gate/`, and reports the Ruff
      *format* drift as advisory so it cannot mask a real failure. Run
      from Windows with
      `wsl.exe -d Ubuntu -- bash ~/projects/cyberstratum/scripts/wsl/gate.sh`.
      Proven from a non-login shell with the stack up: lint, type check,
      730 Python tests, 96 web tests and the launcher check all green.

### Done in the 2026-11-05 round
- [x] Workspace isolation across every tenant-sensitive query path.
- [x] Check-only dependency update monitor + daily timer.
- [x] Production deployment material: `deploy/vps/deploy.sh` (193 lines, verifies
      it deployed), `deploy/vps/Caddyfile` (TLS + reverse proxy),
      `deploy/vps/app.env.example` (production template, no secrets), the
      update-check unit and timer, `docs/DEPLOYMENT.md` (the full runbook).
- [x] Netlify rehearsal: `next build` succeeds in WSL and every data page is
      `force-dynamic` with `no-store`, so nothing is baked at build time and a
      static export would have shipped an empty dashboard.
- [x] ADR-0020 (human identity via Google OAuth, hashed keys for machines).

### Done in the 2026-10-29 round
- [x] Mythril as a manual action — API, own queue and worker, own systemd unit,
      frontend button, `source="mythril"` provenance, no-verdict rule enforced.
- [x] Source↔bytecode correspondence as a stored service — own queue and worker,
      own systemd unit, frontend button, stored proof, four honest outcomes.
- [x] Deterministic PDF report endpoint + the Next.js server proxy.
- [x] Dataset ingestion machinery as its own installable distribution.

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
| 22 | Pending-list implementation | manual Mythril, correspondence service, dataset ingestion, deterministic reports | `54fced8` |
| 23 | Live-proof defects | artifact root, job type width, provenance constraint, constraint naming, own revision | `49e248e`, `e8d6269` |
| 24 | Migration contract test | the migrated schema must accept every provenance the code writes | `c00be88` |
| 25 | Workspace isolation | every tenant-sensitive query path scoped; 27 isolation tests; cross-tenant reads answer 404 | pending |
| 26 | Dependency update monitor | check-only CLI + daily systemd timer; verified against live PyPI/npm | pending |
| 27 | Production deployment material | `deploy.sh`, Caddyfile, env template, update-check unit, `docs/DEPLOYMENT.md` | pending |
| 28 | Netlify rehearsal | `next build` clean; every data page `force-dynamic` + `no-store` | pending |
| 29 | Human identity | ADR-0020 written; implementation in flight | pending |

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

## 9. Mythril's exit code and input are both traps

A stale background probe against `~/mythws` turned up two empty output
files. They were empty because the probe had run three minutes *before* the
bounded Mythril job wrote them, not because anything failed. But the files
themselves carried a result worth pinning down: a `success: true` with zero
issues on a contract with a textbook reentrancy pattern.

Re-running the fixture with a correctly prepared input settled it.

| Run | Exit | `success` | Issues |
|---|---|---|---|
| Runtime bytecode of the reentrancy fixture | `1` | `true` | 2 (SWC-105 High, SWC-114 Medium) |
| Creation bytecode of the same contract | `0` | `true` | 0 |

**Trap A: the exit code is inverted.** Mythril exits `1` when it finds
issues and `0` when it finds none. A runner that maps a non-zero exit to
"engine failed" discards every genuine result and reports the contract as
never analysed. The verdict lives in the JSON envelope; the exit code only
says whether the process died.

**Trap B: creation bytecode analysed as runtime yields a silent false
clean.** The stored `v.hex` was creation code (910 hex characters) rather
than runtime code (854). Fed to `--bin-runtime` it produced
`{"error": null, "issues": [], "success": true}` with exit `0`: right
shape, wrong answer, no signal. The manual action must be handed the
runtime and must fail loudly if it was handed creation code.

**The console script is `myth`, not `mythril`.**
`~/venvs/mythril/bin/mythril` does not exist; `~/venvs/mythril/bin/myth`
is the executable.

The earlier "no verdict within a bounded budget" reading of the USDC proxy
run is unchanged and remains the reason Mythril is manual-only. What
changed is that the raw-runtime path is now known to work correctly on a
fixture, in 19 seconds, with two findings.

### Verified

- Mythril v0.24.8, WSL, solc `0.8.26`: SWC-105 High and SWC-114 Medium on
  the reentrancy fixture, `success: true`, exit `1`, 19 s.
- The same contract's creation bytecode: `success: true`, zero issues,
  exit `0`.

---

## 10. A compiler failure is not a correspondence failure

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

---

## 11. What the live proof found that the tests could not

The suite builds its schema from `Base.metadata`. Everything a migration
adds on top of that — a CHECK constraint, an index, a column width — is
invisible to it. The proof below was run against the real stack, with the
real database, and it found three defects that way. Each one is now
covered by a test that fails without the fix.

### 11.1 The artifact root was per-process

`OBJECT_STORAGE_ROOT` was relative, so it resolved against each process's
working directory. The API stored artifacts in one directory and the
workers looked in another, so every worker-side artifact read failed as if
the file had never been written. The Mythril job reported
`bytecode_artifact_missing` while the artifact was sitting in the database
and on disk. The root is now resolved against the repository root, and
`tests/unit/test_storage_root.py` checks that the configuration resolves
the same way from the repository root and from `apps/api`.

### 11.2 A job type that could not be stored

`scan_jobs.job_type` was `VARCHAR(12)`. `correspondence` is fourteen
characters, so the job type the correspondence worker writes did not fit.
The column is widened to `VARCHAR(14)`; the rows that use the new job
types are removed on downgrade, because they cannot exist in the older
schema.

### 11.3 A verdict the database threw away

`findings.source` carries a CHECK constraint that allowed only `rule`,
`slither` and `ml`. In WSL, Mythril ran against the runtime bytecode of a
known reentrancy fixture and produced **SWC-105 High** and **SWC-114
Medium** — and the database refused both rows with a `CheckViolation`.

This is the worst shape of failure the product has: the engine did its
work, the work was correct, and the contract then looked exactly like one
Mythril never examined. The constraint is widened, not dropped: an unknown
provenance still cannot be written by accident. The worker also records
`findings_persist_failed`, with the number of findings lost, when storage
refuses the verdict.

### 11.4 Three lessons that outlive the defects

**A migration is never re-run.** The first fix edited the revision that had
already been applied to the development databases. The widening would have
existed only on a database built from scratch, and the environments where
the failure was actually found would have kept the narrow constraint. The
change has a revision of its own, `f7d9a3c1e5b2`.

**A constraint's name is not a constant.** One database has it as
`source` and another as `ck_findings_source`, because the project's naming
convention (`ck_%(table_name)s_%(constraint_name)s`) rewrites it. A
migration that drops a constraint by a hard-coded name fails on whichever
database disagrees, and a migration that fails halfway leaves a schema
that matches no code at all. The revision looks the name up in
`pg_constraint` and drops what is actually there.

**The AGPL guard reads identifiers as code.** `FINDING_SOURCES` is a tuple
of string literals for exactly that reason. An enum member called `SLITHER`
was flagged by `tests/unit/test_agpl_boundary.py` as Slither being used
in-process. The guard was right: a mention of an engine inside a string is
data, and a mention inside an identifier is code.

### 11.5 What the proof now shows

Live in WSL, on the committed code: the scan is created, the manual
Mythril action returns `202` and says only *queued*, the dedicated worker
runs the external executable, the job reaches `finished`, the two findings
are stored with `source="mythril"`, `mythril_ran` is `true` and
`mythril_skipped` is `null`. The manual correspondence action returns
`202`, the job finishes, and the outcome is `unavailable` — correct for a
fixture with no verified source, and deliberately *not* `mismatch`. The
The report endpoint serves a PDF with its `X-Report-SHA256` header. The stack
stops cleanly afterwards.

### 11.6 The WSL round closes

The final gate, run in WSL against the pushed code:

| Gate | Result |
|---|---|
| Ruff | All checks passed! |
| mypy | no issues found in 86 source files |
| pytest, full and uncapped | 730 passed, 16 warnings in 79.00s |
| Vitest | 11 files, 96 tests passed |
| `npm run check` | exit 0 — every path resolves |

The stack was then stopped with `npm run stop`, and the boundaries were
verified from outside the launcher:

| Service | State after the stop | Owner |
|---|---|---|
| PostgreSQL 5433, isolated | down | this project, stopped |
| PostgreSQL 5432, system | up | Ubuntu, untouched |
| Redis 6379 | up, `PONG` | Ubuntu, untouched |
| API 8000 | down | this project |
| Frontend 3100 | down | this project |

No application process was left behind. Redis was cleaned of the 14
`rq:*` keys the live testing created; the 16 `module:*` keys belonging to
the trading bot were left alone, so Redis ended at `DBSIZE 16` and
`PONG`. What is still open is not engineering: it is the production
inputs for the deployment.

### 12.1 The tracked-asset spine, and the three defects it exposed

The product's two modes — the autonomous scan of newly verified contracts
and the developer's own scan — had nothing in common in the database.
Both wrote scans, but nothing recorded *which address* a scan was about,
so "did my fix work?" could not be answered from the data.

`tracked_assets` is that spine: one row per (workspace, chain, address),
classified `owned`, `watched` or `discovered`, carrying the date the
address was first seen. Every scan attaches to it through `scans.asset_id`
(`ON DELETE SET NULL`, so stopping the tracking never deletes evidence).
The progress numbers are *computed* from the scans and findings that
exist, never cached, because a cached counter can disagree with the rows
it claims to count.

With the spine in place, three defects that had been hiding in plain
sight showed up in the first live discovery cycle.

**Defect 1: a verified contract could not be analysed at all.** The
bytecode was fetched from the chain's public RPC, and from Sourcify when
the RPC was unreachable. A chain whose public RPC endpoints are
unreachable from a small server, and whose contracts Sourcify has not
indexed, produced a *failed* scan — even though the contract was
verified on that chain's own explorer, which is where it had just been
discovered. Every Blockscout instance proxies the Ethereum JSON-RPC API
at `/api/eth-rpc`, so the explorer that answered the discovery query can
also serve the contract's bytecode. That is now the third route, and it
is what makes the autonomous path work on the long tail of chains whose
RPC endpoints do not answer.

**Defect 2: "partial" was a shrug.** A scan was marked partial when the
disassembly warned or the control-flow graph could not be fully
resolved, but nothing recorded *what* was missed. The status was
decoration. `scans.limitations` now records the disassembly warnings,
the number of unresolved control-flow edges and their ratio, and the PDF
report renders them under "Coverage limitations". A partial scan now
says what it could not analyse.

**Defect 3: the progress history read backwards, and its order was
random.** The timeline was newest-first, which is a list, not a log. It
is now chronological. The tie-break needed care: `created_at` is a
database `now()`, which is the *transaction* timestamp, so two scans
created in one transaction share it, and the scan id is a random UUID
that says nothing about order. The ordering therefore falls through to
`queued_at`, which the application stamps per call and which is
therefore the real creation order.

### 12.2 The scheduler

`app.cli.discovery_cycle` queues one discovery cycle, and the systemd
units (`cyberstratum-discovery.service` and `.timer`, hourly, with
`Persistent=true` so a missed run happens after a reboot) call it. The
cycle is *queued* rather than run in-process so that there is exactly one
execution path — the same code the API and the worker use — and so that a
cycle waits patiently for the worker instead of dying half-way through a
sweep of sixty chains.

### 12.3 What the live run produced

One cycle, two chains, against the real Blockscout feed:

| Stage | Result |
|---|---|
| Discovery | 100 contracts found, 100 new, 0 chains failed |
| Tracked assets | 100 rows, `kind=discovered` |
| Scans queued | 100, all drained by the workers |
| Findings | baseline (bytecode), slither (source) and mythril findings in one scan set |
| Artifacts | 37 |

A contract that had failed with `sourcify_unavailable` was re-scanned
after the fix and came back `partial` with two findings and an honest
limitations document; the asset's history then showed both scans with
their dates, and the open-finding count moved from 0 to 1.

### 12.4 The gate

| Gate | Result |
|---|---|
| Ruff | All checks passed! |
| mypy | no issues found in 106 source files |
| pytest, full and uncapped | 864 passed, 28 warnings in 151.79s |
| Vitest | 12 files, 100 tests passed |
| `npm run check` | exit 0 — every path resolves |

## 13. The coverage round — a measurement is not a gap

### 13.1 What was wrong

A contract compiled from ordinary Solidity came back `partial`, with three
reasons that were not defects:

* `invalid opcode at offset 448` — Solidity's deliberate `0xFE` guard
  byte, placed immediately before the CBOR metadata trailer;
* `solidity metadata detected at offset 449` — the trailer itself, which
  is data and was never code;
* six unresolved control-flow edges — the runtime-computed jumps the
  Solidity function dispatcher is built out of, which no static analysis
  can follow.

Because almost every real contract trips all three, "partial" carried no
information at all. The word had been doing the job of a measurement.

### 13.2 What changed

| Where | Change |
|---|---|
| `packages/evm_analysis/.../disassembler.py` | `Disassembly.notes` was added. The metadata trailer and the guard byte in front of it are notes. An invalid opcode anywhere else is still a warning. |
| `packages/evm_analysis/.../cfg.py` | Dynamic jumps moved from `cfg.warnings` to `cfg.notes`. The edge itself is still `UNRESOLVED`. |
| `apps/api/app/services/pipeline.py` | A scan is `partial` when the disassembly or the control-flow graph has a warning, or when the source audit could not actually run. `BENIGN_SOURCE_SKIPS` separates "there was no source to audit" from "the audit could not be done". |
| `apps/api/app/db/models/scans.py` | Every scan records a `coverage` measurement: instructions decoded, executable/code/metadata bytes, control-flow edges, dynamic jumps and their ratio, unreachable blocks, and the notes taken on the way. |
| `apps/api/app/schemas/scans.py`, `apps/api/app/services/report.py` | The measurement is exposed through the API and rendered in the PDF as **Static coverage**, next to the limitations that are still limitations. |
| `apps/web/...` | The scan page renders the same measurement. |

Migrations `b5d9f3a7c1e2` (coverage) and `c6e1a4b8d2f3` (model scores) were
applied to the isolated PostgreSQL on `5433`; the Alembic head is
`c6e1a4b8d2f3`.

### 13.3 The evidence

`tests/unit/test_scan_coverage.py` pins the distinction: the trailer is a
note, the guard byte is a note, an invalid opcode elsewhere is a warning, a
dynamic jump is a note, and the report renders the measurement as sentences.
The two pipeline tests that asserted a source-fetch failure was a *complete*
scan now assert `partial` with the reason recorded — a gap is a gap.

---

## 14. The learning loop — reviewed labels in, a gated model out

### 14.1 What was missing

The ML baseline existed as a library: it could train, evaluate and gate
itself. But nothing in the product ever called it. No scan used a model,
`risk_score` did not exist in the API, and the reviewed findings that
people had been recording never reached a dataset. The loop was open at
both ends.

### 14.2 What changed

| Where | Change |
|---|---|
| `apps/api/app/services/ml_ranking.py` | Loads the installed model and keeps three states apart: none (`None`), readable, and broken (raised, never silently treated as "no model"). `annotate_findings()` attaches `ml_score` and `ml_category` to a finding's evidence **and changes nothing else** — not the severity, not the confidence, not the review status. |
| `apps/api/app/services/pipeline.py` | The model is applied when `ENABLE_EXPERIMENTAL_ML` is on. The scan records `model_version` and `model_scores`. A broken installation is recorded as a limitation, not hidden. |
| `apps/api/app/cli/learning_cycle.py` | The missing loop: export the reviewed labels → write the dataset with its provenance header → train with the family-level split → **install only if the precision gate passes**. A model that failed the gate is written for inspection and never installed. The command exits `1` when there is nothing reviewed to learn from and `2` when the gate refuses promotion. |
| `apps/api/app/services/report.py`, `apps/web/...` | The PDF and the scan page show the model's ranking under a heading that says what it is: a triage aid, not a verdict. |

### 14.3 Why the model is not allowed to decide

A model is trained on reviewed labels, and the label it was trained to
predict is *"a person confirmed this"*, not *"this is a vulnerability"*.
So it contributes a number and nothing else. The reviewer still decides,
and the gate still refuses to install a model whose false positives have
not been measured.

### 14.4 The evidence

`tests/unit/test_ml_ranking.py` (the score is attached, the verdict is
not), `tests/unit/test_learning_cycle.py` (a model that fails the gate is
not installed; a model that passes is; the dataset says where its labels
came from) and a pipeline-level test in
`tests/api/test_pasted_source_scan.py` that runs a real scan with a model
attached and asserts the score reached the finding while the review status
stayed `new`.

### 13.5 The live run

The stack was restarted through the canonical launcher and a contract was
compiled from pasted Solidity and scanned for real:

| Field | Value |
|---|---|
| Status | `completed` (it was `partial` before the change) |
| Limitations | `None` |
| Coverage | 294 instructions, 449 executable bytes, 53 metadata bytes, 46 edges, 6 dynamic jumps (13.04 %), 1 unreachable block |
| Notes | the metadata trailer, the guard byte in front of it, and each dynamic jump, by offset |
| Findings | 5 |

The scan before the change is still in the database with its old, honest-
but-wrong record: `partial`, `invalid opcode at offset 448`, six unresolved
edges.

### 14.5 The live run

The learning cycle was run against the live database:

```
$ python -m app.cli.learning_cycle --dry-run
GATE: the model may not be installed: there is no validation split, so no
category could be judged; a model needs at least a few distinct families
{"records": 1, "promotable": false, "installed": false, ...}
```

That is the correct outcome, and it is the outcome the safety invariant
demands. The live database holds 114 scans and 417 findings, of which
**two** have been reviewed — one confirmed and one false positive — so
exactly one contract has a settled category. One contract cannot be
split into a training set, a validation set and a test set, so no
category can be judged, so no model may be installed.

The machinery is therefore complete and the corpus is not. The gate is
what turns a thin corpus into a refusal rather than into a confident
model, which is the whole point of having it.

### 15 The selfdestruct round — a rule that must follow the fork

`SELFDESTRUCT` changed what it does in Cancun: under EIP-6780 the
contract's code survives and only the balance is forwarded. The rule was
still saying "the contract can destroy itself" on every chain, which on a
modern chain states something the chain no longer does.

The rule now narrows with the fork:

| Fork | Severity | Confidence | What it says |
|---|---|---|---|
| before Cancun | medium | 0.60 | the contract can destroy itself and forward its balance |
| Cancun and later | low | 0.45 | the code survives; the balance can still be swept |
| unknown | medium | 0.60 | the old wording, because an unknown fork is not "at least" anything |

The narrowed finding carries the fork in its evidence and says in its
limitation that the one remaining case — a contract created in the same
transaction — cannot be shown from runtime bytecode.

The guidance catalogue entry was rewritten to match (version 2): what it
means, why it matters, how to fix it and when it is expected are all
now fork-aware.

Four tests pin the narrowing, including that a later fork still narrows
and that the opcode offset is still reported.

### 16 The key round — a machine client belongs to one tenant

An API key was a machine client with no tenant of its own: it was
resolved to its owner's *earliest* workspace membership, because the
``api_keys`` table carried no workspace column. A key whose owner was in
several workspaces therefore acted in whichever one they happened to
join first, and nothing in the product could say which one was meant.

Three things changed:

* **`api_keys.workspace_id`** (migration `d8f2a4c6b901`) binds every
  key to the workspace it acts in. Existing keys were backfilled to the
  workspace of their owner's earliest membership -- the only workspace
  they could have been used in -- and a key with no workspace still
  falls back to that, so nothing that worked before stops working.
* **Expiry is enforced.** `expires_at` was stored but never checked, so
  an expired key kept working for ever. It is now refused.
* **`python -m app.cli.issue_key`** mints a key for a workspace. Nothing
  could mint one before: keys were inserted by hand, so machine clients
  had no way in. The command prints the plaintext once and stores only
  its SHA-256 digest, refuses a user who is not a member of the
  workspace named, and can set an expiry.

The live run:

| Key | Workspace | Assets it can see |
|---|---|---|
| issued for `default` | the tenant | 2 (the developer's own contracts) |
| issued for `discovery` | the discovery workspace | 100 (the discovered contracts) |
| an unknown key | — | refused |

One address, `0xbbcb4485…`, appears in both lists: each workspace keeps
its own row for it, which is what the asset registry is for.

### 17 The backfill round — the history of the chain, not only its newest page

The feed lists contracts newest first, and the cycle read page one and
stopped there. So the newest contracts were found over and over while
everything older was never seen at all: the product was watching the
tip of the feed and nothing behind it.

* **`feed_cursors.next_page`** (migration `e1f3b5d7a902`) records where a
  chain's walk has reached. A cycle reads `pages` pages from there, and
  when the walk runs off the end of the feed it returns to page one --
  which is where the next new contract appears.
* **`python -m app.cli.discovery_cycle --pages N`** sets how deep a cycle
  reads. One page is the tip; more pages walk into the history.
* **The promotion cap no longer strands a contract.** The sweep offers
  the contracts it touched *and* everything of that chain that has never
  been scanned, so a contract the cap left alone is offered again in a
  later cycle instead of sitting in the database for ever.
* **The promotion budget belongs to the cycle, not to each chain.** Fifty
  scans per cycle, as the limit always claimed; the old code allowed
  fifty per chain, which was more than it said.

The live run, on Ethereum:

| | Before | After |
|---|---|---|
| contracts found by one cycle | 100 (the tip, twice) | 150 (three pages, of which 100 were older) |
| contracts known | 106 | 256 |
| scans | 114 | 164 |
| the cursor | none | `next_page=4, seen=200` |

The 100 contracts the cap left alone were persisted and are offered
again by the next cycle rather than dropped.

### 18 The fetch round — a glitch is not a fact about a contract

Twenty-eight scans had failed with `sourcify_unavailable`, and the
message blamed the contract. The real causes were three ordinary
glitches:

* the single default Ethereum RPC (`eth.llamarpc.com`) answers **525**;
* the chain's own explorer answered **429** when a cycle queued fifty
  scans at once, and a rate limit was treated as a final answer;
* a JSON-RPC error body — which some endpoints return with status 200 —
  was read as "the address holds no code".

* **Several default endpoints per chain.** Probing found free, keyless
  hosts that answer `eth_getCode` today: `publicnode`, `drpc`,
  `mevblocker` and `blastapi` for Ethereum, and the equivalents for
  Optimism, BSC, Polygon, Arbitrum, Avalanche and Sepolia. One dead
  host is no longer the end of the fetch.
* **A rate limit is retried.** A 429 or a 5xx is a fact about the
  moment, so the request is tried again after a short wait; a 404 is
  an answer and is not retried.
* **A JSON-RPC error is a failed endpoint**, not an empty contract, so
  the next route is tried.
* **A transient failure is a debt, and debts are paid first.** The
  sweep now offers, before anything else, the contracts whose most
  recent scan failed for a transient reason; they were promised an
  analysis and did not get one. The retries are bounded (three), so a
  broken endpoint is never hammered.

The live proof, on the three contracts that had failed:

| Contract | Before | After |
|---|---|---|
| `0xbbcb4485…` | failed — sourcify_unavailable | 242 bytes fetched, scan **partial** with findings |
| `0x3919c228…` | failed — sourcify_unavailable | 663 bytes fetched, scan **partial** with findings |
| `0xbf2a0214…` | failed — sourcify_unavailable | 5275 bytes fetched, scan **partial** with findings |

The old failures stay in the history: they happened, and the history
must not be rewritten.
### 19 The advice round — a finding that does not say what to do is half a finding

The corpus was producing findings from **30 different detectors**. The
knowledge seed carried advice for **6** of them. The other 24 arrived as
a detector id, a severity, and a title — and a reviewer had to go and
research the pattern from scratch. Worse, the advice that *did* exist was
in the PDF and nowhere else: the web UI, which is where a reviewer
actually works, showed the finding and not the answer to it.

* **Every emitted detector now has advice.** The seed went from 6 entries
  to 32: the six baseline detectors, the 24 Slither detectors the corpus
  has produced, and the two Mythril detectors. Each entry was written
  from what the pattern actually is, not from a shared template — what it
  means, why it matters, what to change, and **when it is not a problem**,
  which is the half that keeps a product from crying wolf.
* **The advice travels with the finding.** A "What this means, and what to
  do about it" panel is rendered under every finding that has guidance, on
  the scan page and on the findings page. It is fetched on the server, so
  the API key stays where it belongs.
* **The advice is where the label is born.** The triage queue -- where a
  reviewer settles a finding, and where the label the model learns from
  is written -- carries the advice too. A reviewer can see what the
  detector means, and when the pattern is expected, before deciding
  whether the finding is real. The advice panel is one component, used
  in both places, so the two never drift apart.
* **A test pins the coverage.** Every detector the product emits must have
  guidance; every severity must be one the product uses; every id must
  appear once. A new detector without advice now fails the suite.

The live proof:

| Check | Before | After |
|---|---|---|
| Guidance entries | 6 | **32** |
| Advice panels over 200 findings on `/findings` | 0 | **200** |
| Advice on the scan detail page | none | rendered inline ✓ |

The one detector the corpus had produced that the seed was still missing
— `slither.reentrancy_unlimited_gas` — was found by the coverage test
rather than by a list, and was written: a re-entrant call that forwards
all the remaining gas hands the callee the decision of how much gas to
use, so the re-entrant path can be driven into an out-of-gas in the
middle of the caller's own work.

**What still remains.** Slither ships more detectors than the corpus has
ever exercised, and those still have no advice — the catalogue is
complete for what the product has seen, not for what Slither can emit.
### 20 The catalogue gap, measured

The advice round left a number nobody had measured: Slither ships **101**
detectors, and the seed answered **24** of them. The gap was a sentence in
a document; now it is a number the build can see.

* **The catalogue is a versioned snapshot.**
  `apps/api/app/data/slither_detectors.json` records every detector
  Slither 0.11.6 ships -- its id, its title, its impact and its
  documentation link -- with the original check id kept beside the
  product's name, so the two can always be matched.
* **The gap is measured by a command.**
  `python -m app.cli.guidance_audit` prints the coverage and names the
  detectors that have no advice; `--strict` turns a gap into a non-zero
  exit, so a build gate can insist on it.
* **A typo can no longer hide.** The audit also names guidance entries
  that name no known detector. A misspelt id would otherwise sit in the
  seed looking like advice for something.
* **The next batch of advice is written.** 24 more detectors now have
  guidance: the re-entrancy family (including the benign one), the
  unchecked-call family, the uninitialised-state family, the
  caller-controlled delegatecall and array-length families, weak
  randomness, the return bomb, the `encodePacked` collision, the
  unprotected upgrade, and Ether accepted on a path that did not expect
  it.

| Coverage | Before | After |
|---|---|---|
| Slither detectors with advice | 24/101 | **48/101** |

### 21 The bulk round — one verdict for a whole group of findings

The reviewed corpus was empty for a reason that was not the model's: a
reviewer who has read one `slither.naming_convention` finding and
decided that it is a style question has decided the same thing about
the other sixty-six of its kind, but the product gave them no way to
say so except sixty-seven separate decisions. The label is the
expensive part, so the action had to be made once.

**What was built.**

* `POST /api/v1/findings/review-bulk` settles every open finding of one
  detector with one verdict, under the rules of a single verdict: `new`
  is not a verdict, a false positive needs a reason, and a finding that
  has already been settled is never overwritten — it is counted and left
  alone. Each finding it touches gets its own audit event, and the
  action commits rather than only flushing.
* `GET /api/v1/workspaces` names the workspaces a caller may act in and
  how many findings in each are still open. A bulk verdict belongs to
  one tenant, so the reviewer says whose findings they are settling, and
  the action is refused when that is not known.
* The web UI: a workspace picker on every group in `/triage`, the reason
  box, and two buttons. The rules live in one client-safe module, so
  the browser and the server cannot disagree about them.

**The mistake, and the undo.** The first live proof called the endpoint
with the administrative service key — the key that acts across every
tenant — and settled **67 real findings** as false positives. That is
fabricated ground truth, and the corpus was wrong until it was put
right. Every one of the 67 was restored to `new` with its reviewer,
time and reason cleared, and their 67 audit events were deleted; the
corpus was then measured back to its previous state (1 413 new, 1
confirmed, 1 false positive, the two original reviews intact). The
lesson is now a rule in the code rather than a memory: a bulk action is
keyed by detector id, and a detector id is not a tenant, so the action
may not run without a named workspace. The service key is refused with
`403` unless it names one.

**A credential bug found on the way.** The web front end presented the
service key *and* the session token together on every call. The backend
refuses a request carrying both — a request that presents two
credentials has no defined subject — so every signed-in page was one
step away from a `401`. The front end now presents exactly one: the
session when there is one, the service key otherwise.

| | Before | After |
|---|---|---|
| Verdicts a reviewer can record on a group of findings | 1 per finding | **1 for the whole group** |
| Ways for a bulk action to reach another tenant | unbounded | **refused (403) without a named workspace** |
| Backend tests for the bulk action | 0 | **13** |
| Front-end tests for the shared verdict rules | 0 | **4** |
| Reviewed findings in the live corpus after the proof | 2 | **2 (the 67 were restored)** |

### 22 The catalogue gap, closed

The gap the audit measured -- 48 of Slither's 101 detectors answered -- is
now closed. The remaining 53 detectors now carry the same four-part
entry as the rest: what the pattern means, why it matters, what to
change, and when it is *not* a problem. The last of them are the quiet
ones, and they are worth having precisely because they are quiet: a
right-to-left override character in a token name, `msg.value` counted
once per iteration, a state variable that shadows another one, a
constructor that was never implemented.

* **The audit now reports full coverage.**
  `python -m app.cli.guidance_audit` prints `101/101`, an empty
  `missing` list and an empty `unknown` list, and `--strict` exits
  zero. The number that was a sentence in a document is now a number
  the build can see, and it is the number the build wants.
* **The advice is served and rendered.** The knowledge endpoint answers
  with **109** entries -- the 101 Slither detectors, the six baseline
  detectors and the two Mythril ones -- and the same advice appears
  under the finding in the scan page, in the findings list and in the
  triage queue.
* **Writing it was work, not filler.** Each entry says what the
  pattern is in the contract, what an attacker gains, what to change,
  and the case where the pattern is expected. The false-positive half
  is the half that saves a reviewer their afternoon, so it was written
  for every entry rather than left as a generic disclaimer.

| Coverage | Before | After |
|---|---|---|
| Slither detectors with advice | 48/101 | **101/101** |
| Guidance entries served by `/api/v1/knowledge` | 56 | **109** |
| `guidance_audit --strict` exit code | 1 | **0** |

### 23 The whole walk, in one command

Every part of this product has been proved on its own -- discovery, the
fetch, the scan, the coverage, the advice, the review. What was missing
was a single command that walks the whole thing on the running stack,
so that "it works" is a thing you can run rather than a thing you
remember.

`scripts/wsl/e2e_full_workflow.py` does that, in ten steps:

| Step | What it proves | The answer it gave |
|---|---|---|
| 1 | The stack answers | api 200, web 200 |
| 2 | The corpus is there and tenant-shaped | `default` 40 open, `discovery` 1373 open, 1415 findings |
| 3 | Every finding carries advice | 109 entries served, none of the detectors in the first page unanswered |
| 4 | The scan queue produced scans | the latest scan and its limitations are readable |
| 5 | A reviewer settles a finding and a group | one verdict: 200; one verdict for the group: applied 1, skipped 1 |
| 6 | A settled finding is not settled twice | applied 0, skipped 2 |
| 7 | The service key cannot act across tenants | 403, with the reason in words |
| 8 | The proof leaves nothing behind | 0 findings left behind |
| 9 | The labels are the ones that count | 2 reviewed findings in the live corpus |
| 10 | The model refuses itself | the learning cycle exits **2**: `promotable: false`, `records: 1` |

The review in step 5 happens in a workspace the script creates and
deletes. A reviewed label is a human decision, and the script is not a
human; what it proves is that the *mechanism* records a decision
correctly, not that any particular finding deserves the label.

Step 10 is the important one. The corpus has two reviewed findings
from one settled contract, and the learning cycle says so and stops:
there is no validation split, so no category can be judged. That
refusal is the product working, not failing.

### 24 The line, and the code it points at

A finding that says "`tx.origin` at line 17" is half a finding until the
reader can see line 17. The product knew the line -- the source map
proved it -- but the code was nowhere on the screen: the source was
stored as a scan artifact, and there was no way to read an artifact
back. The developer who pasted a contract was told where the problem
was and then had to go and find their own file.

* **`GET /api/v1/scans/{scan_id}/source`** returns the source that was
  analysed, file by file, with the compiler version, the language, the
  verification state and the address it came from. It is scoped to the
  tenant like every other read, and a scan of deployed bytecode with no
  source says so in words -- `available: false` and a reason -- rather
  than returning an empty list that reads like "there was nothing
  there".
* **The scan page now shows the source**, with line numbers, and the
  lines the findings name are marked. The panel sits under the findings
  table, so the reader's eye goes from the finding to the code without
  leaving the page.
* **The finding carries its line into the browser.** `source_line` and
  `source_file` were in the evidence all along and were being flattened
  into a list of signal names on the way out; they are now fields of
  their own.

The live proof is the developer's own workflow: paste the contract,
and the page shows the `tx.origin` finding pointing at line 17 of the
contract that was pasted, with line 17 marked in the source underneath.

| The proof | Before | After |
|---|---|---|
| The source of a scan | stored, unreachable | `available: true`, the file, the compiler that made it |
| The line of a finding | in the evidence, flattened away | a field, and a marked line in the source |
| A scan with no source | -- | `available: false`, and the reason in words |

### 25 Twenty chains in one cycle

Discovery had been running on two chains. The cursor machinery was
right -- never-seen chains sort first -- but the rotation had never
been given anything to rotate over, so the sweep kept re-reading the
same two feeds and the rest of the chain set stood still.

A cycle with twenty chains and two pages each settled it:

| | |
|---|---|
| Chains covered | **18** (2 failed, and said why) |
| Contracts found | **1570** |
| Contracts new | **1485** |
| Scans queued | **50** -- the cycle-wide budget, unchanged |
| Cursors | 2 → **22** |
| Time | 31 seconds |

The two failures are the two chains whose Blockscout instance needs a
paid plan: Gnosis and Polygon PoS answer "BLOCKSCOUT_API_KEY is not
set". The run is reported as **partial**, not as a success with a
footnote, because two of the twenty did not answer.

The rest of the rotation is now automatic: the next cycle takes the
chains that were touched longest ago, and the ones it has never seen
come before any it has. Sixty chains are reachable; the sweep works
through them in rounds rather than in one long run.

### 26 The discovery, on a page

The autonomous half of the product had no page. The API could say how
far each chain's feed had been read and what each cycle had found, and
the web application never asked. From the outside, CyberStratum looked
like a tool that scans whatever you give it -- which is the half a
competitor can copy. The part that reads the chains on its own, keeps
its place in the history of each chain, and comes back for more was
working and invisible.

`/discovery` now shows:

- **the chains** -- every chain the feed has read, how many contracts
  it has seen, which page the next read starts from, and when it was
  last read;
- **the cycles** -- what each cycle covered, how many contracts it
  found and how many were new, and the chains it could not reach,
  named.

A cycle that could not reach every chain is shown as `partial` with the
reasons attached, not as a success with a footnote. The two chains
that need a paid Blockscout plan are the ones that say
`BLOCKSCOUT_API_KEY is not set` -- the product says what is missing
instead of going quiet.

The page reads the same two endpoints the rest of the application
uses; it adds no new API surface beyond the cursor's next page, which
the cursor route did not previously expose.

### 27 What we find most, and where

The summary said how bad the findings were and how many were still
undecided. It did not say *which* issues the catalogue keeps raising,
nor which chains they come from -- so the number on the overview was a
number and not a list of work.

The summary now carries two more breakdowns:

| Breakdown | Live (1,483 findings) |
|---|---|
| `by_detector` | 20 detectors named -- `baseline.delegatecall` 219, `slither.assembly` 217, `baseline.unresolved_jumps` 177, `slither.solc_version` 155 |
| `by_chain` | Chain 1 1145, OP Mainnet 290, Astar 30, Rootstock 18 |

Both are honest about the corpus they describe: the detector list is
capped at twenty (the whole list stays available through the findings
list itself) and the chain list names every chain the findings came
from.

The findings list can now be narrowed by detector and by chain, and
the overview links into it with the filter already applied:

- `/findings?detector=baseline.delegatecall` -- 219 findings, all of
  them from that detector;
- `/findings?chain_id=1` -- the 1,145 findings from that chain;
- a chain with nothing on it answers `0`, not an error.

The filters compose: the severity filter is kept when the detector or
chain filter is applied, so narrowing by one does not silently drop
the other. The chain filter walks finding -> scan -> target -> chain,
because a finding does not know its chain itself.

This is what makes the catalogue usable rather than merely complete.
A detector that fires two hundred times on one chain is a different
problem from a detector that fires twice on forty chains, and the
number alone cannot tell them apart.

### 28 The model, and why it is not there yet

The model was the part of the product nobody could see. The scan page
said a model had not been installed; the learning cycle printed a
refusal into a terminal. Neither said what had been reviewed, or why
the refusal happened, in the place where a person would look.

The learning cycle now leaves its verdict where the product can read
it, and a page reads it:

- `GET /api/v1/learning/status` -- the reviewed corpus, the installed
  model, and the last cycle's outcome. Tenant-scoped; it needs a
  credential like everything else.
- `/learning` -- the same state, in words.

Live, after the first cycle of this round:

| What the page says | Value |
|---|---|
| Reviewed findings | 2 |
| Confirmed | 1 |
| False positives | 1 |
| Contracts settled | 1 |
| Issue categories | 2 |
| The model | No model is installed |
| The last learning cycle | 1 contract exported, not promotable |
| The gate reason | *there is no validation split, so no category could be judged; a model needs at least a few distinct families* |

That last line is the point of the page. A product that cannot show
its own reason for not having a model will be asked for one anyway,
and the honest answer belongs where the numbers are.

The page also states what the model would do if it were there: it
ranks findings, it does not decide a verdict, and every finding still
gets its severity and its evidence from the rules whether a model is
installed or not.

What the model needs next is not code. It needs decisions: a few
hundred reviewed findings across a few dozen distinct families, each
one a person's judgement in triage. The bulk review, the guidance and
the source panel exist so that a person can make those decisions
quickly. Fabricating them would make the number go up and the model
worse.

### 29 The whole repository, formatted once

`ruff format` had never been run over the whole tree: 87 committed
files were unformatted, and the gate had been treating that as
noise. It was time to make it a commit of its own rather than let it
drift.

The pass is mechanical and behaviour-free. What it bought:

- `ruff format --check` now reports **every file formatted** (215
  files), so the gate has one fewer thing to shrug at.
- The diff is small because the files keep the line endings the
  repository stores: 399 insertions and 623 deletions across 87
  files, not a whole-tree rewrite.

The gate after the pass: lint clean, typecheck clean, **987 Python
tests passed**, the frontend suite green, `npm run check` green.

While the pass was being made, the pending record was reconciled with
what has actually landed, because a record that is wrong is worse
than no record:

| Item | Was | Now |
|---|---|---|
| 3.2 Identity | `[ ]` implementation not started | `[x]` `70ef088`, `515fa89` |
| 3.5 Report as a first-class artifact | `[ ]` | `[x]` `b6ac6f9` |
| 3.6 Repository-wide formatting | `[ ]` | `[x]` `c11d2fb` |
| 3.8 Migration-vs-model diff | `[ ]` | `[x]` `70ef088` |

### 30 The authorisation a scan was made under

Commit `e24fe31`. Migration `f5a7c3e91b04`.

Until now the product said what it found and how confident it was. It
never said whether the workspace was *allowed* to look. That is the
other half of a security product's job, and it is the half that gets
people sued.

The authorised scope is now a declarative registry. A workspace declares
what is in bounds — a programme, a chain, or a specific contract — and
the product records, at the moment a scan is queued, what that
declaration said about the target.

The rule is deliberately simple and deliberately honest. There are three
answers and only three:

| Answer | When |
|---|---|
| `in_scope` | a live grant of this workspace covers the target |
| `out_of_scope` | this workspace has declared scope, and the target is not in it |
| `unknown` | this workspace has declared no scope at all |

`unknown` is the answer that matters. A workspace that has said nothing
has not been refused and has not been permitted, and a product that
cannot tell those apart is lying about one of them. `unknown` is never
quietly read as permission — the report says the analysis is not
authorised for disclosure, and the scan page says the same.

What landed:

- `ScopeGrant` and `scans.scope_status`, migration `f5a7c3e91b04`.
- `evaluate_scope()` in `app/services/scope.py` — the three answers, and
  the sentence each one speaks.
- `GET/POST /api/v1/scope/grants` and `GET /api/v1/scope/status`.
- The intake records the authorisation when the scan is queued, so the
  answer is a fact about that scan, not a fact about the workspace now.
- The PDF report carries the statement. A report about a target that was
  never in scope must not read like a report about something the
  workspace was welcome to examine.
- The scan page shows it: `ScopePanel`, with `unknown` rendered as
  "Scope unknown — this is not permission".

Every scope operation is workspace-scoped, and the administrative key
must name the workspace it acts in: a scope that applies to every
workspace at once is not a scope, and one that touches another tenant's
scope without saying so is worse.

Two things this is **not**, on purpose. It does not crawl programme
scope files, and it does not send requests, execute exploits, or submit
disclosures — those require explicit authorisation, which no registry
can grant by being filled in.

Proved live: a grant was created in a throwaway workspace, read back,
and the three answers came out distinct — `in_scope` for the declared
contract, `out_of_scope` for another, `unknown` for a workspace with no
declaration. The administrative key without a workspace was refused with
`403`. A scan of a real verified contract was queued and recorded
`in_scope`; the PDF carried the scope statement; the page rendered
"Authorised scope" and "In scope". The proof workspace and its grant
were removed afterwards.

### 31 The scope, declared in the product

The registry landed as an API first, which made it true but not usable:
there was nowhere in the product to declare a scope, and nowhere to read
one back. A declaration that can only be made with `curl` is a
declaration most workspaces will never make, and a workspace that never
declares one stays `unknown` forever.

So the scope is now a page. `/scope` shows what a workspace has
declared, and lets it declare more. The workspace is chosen, not
assumed — a declaration belongs to one tenant, and an operator who does
not say whose scope they are reading is reading the wrong one.

The form refuses what the registry would refuse, and says why before
the request is made: a kind it does not know, a value with nothing in
it, a chain grant with no chain id, a contract grant whose address is
not an address. The refusals live in a shared module so the browser
and the tests say the same thing.

The browser posts to a server-side proxy, so the service key stays out
of the client bundle and the session cookie stays in the browser. The
proxy refuses a declaration with no workspace named, and passes the
reviewer's choice through untouched — the same rule the backend
enforces, in the same words.

Proved live: a declaration made through the browser-facing proxy was
stored, and the page showed it — the address, the workspace it belongs
to, and that the safe harbour had been accepted. A declaration with no
workspace named was refused with `422`. The proof workspace and its
grant were removed afterwards.
