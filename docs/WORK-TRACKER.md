# CyberStratum — Work Tracker

**Purpose:** a single persistent record of what is done and what remains.
Update this file after every completed task. Mark the item done, note the commit,
and update the "Remaining" list so the next session knows exactly where to resume.

**Last updated:** 2026-10-29
**Latest commit:** `c00be88` — *test: prove the migrated schema accepts every provenance the code writes*
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

