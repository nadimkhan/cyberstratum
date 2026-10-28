# CyberStratum — Product Requirements

**Derived from:** `CyberStratum_Product_Technical_Design_Documentation.md`
(v1.0, 28 October 2026).
**Purpose:** a distilled, non-contradictory requirements list. Where the design
document contradicts itself, the resolved position (see
[`docs/adr/`](adr/README.md)) is recorded here and the conflicting section is
noted in the traceability table.

**Scope statement:** this document covers the **MVP only**. P1 and P2 items
from the design document are listed in §7 as explicitly out of MVP scope, not
as requirements.

---

## 1. Personas

Derived from design-doc §3.1 (Roles) and §1.1 (Product outcomes).

| Persona | Role | Primary goal | What they need from the product |
|---|---|---|---|
| **Security Researcher** | `researcher` | Find and validate candidate vulnerabilities in contract bytecode | Paste/upload bytecode, get a disassembly, a CFG, prioritised candidate findings with evidence and byte offsets, and a way to reproduce a finding locally |
| **Reviewer** | `reviewer` | Decide whether a candidate finding is real | Evidence with offsets and blocks, severity and confidence as separate fields, explicit limitations, and an audited decision trail |
| **ML Engineer** | (admin-gated) | Improve detection quality and understand model behaviour | Versioned datasets, model registry, evaluation runs with per-category metrics, calibration and thresholds, drift monitoring |
| **Operator / DevOps** | (admin-gated) | Keep the system healthy | Queue depth, worker heartbeats, database status, error rates, scan-stage failures, structured logs |
| **Workspace Owner / Admin** | `owner`, `admin` | Manage the workspace, its members, policy, and retention | Member and role management, chain/RPC integration configuration, scan defaults and resource limits, retention and deletion controls, API key issuance and revocation |
| **Read-only Viewer** | `viewer` | See approved scans, findings, and metrics | Filterable scan and finding lists, the dashboard, and reports — with no ability to mutate |

### 1.1 Permission principles (design doc §3.2)

- Enforce RBAC **server-side on every API**. The frontend must never be the
  authorisation boundary.
- Isolate tenants at the **workspace** level; every target, scan, finding, and
  report is workspace-scoped.
- Require explicit approval before exporting a disclosure report or running a
  sandbox reproduction.
- Keep signing keys out of the application database. The MVP requires no
  private keys at all.
- Log privileged actions and configuration changes to an append-only audit log.

---

## 2. Functional requirements

Priority follows design-doc §4. **P0 = must ship in the MVP.**

### 2.1 Identity and workspaces

| ID | Requirement | Priority | Design doc |
|---|---|---|---|
| FR-1.1 | Users authenticate with email + password, or an OIDC provider. | P0 | §3, §11.2, §25.3 |
| FR-1.2 | Passwords are hashed with a modern password-hashing algorithm (argon2 is available). | P0 | §7.3 |
| FR-1.3 | Workspaces exist; every user belongs to one or more with a role. | P0 | §3.1, §9.1 |
| FR-1.4 | Roles are: Owner/Admin, Researcher, Reviewer, ML Engineer, Operator, Read-only Viewer. | P0 | §3.1 |
| FR-1.5 | API keys can be issued, shown once, rotated, and revoked. | P0 | §11.16 |
| FR-1.6 | Invitation acceptance shows the workspace name and the invited role. | P0 | §11.2 |

### 2.2 Contract target intake

| ID | Requirement | Priority | Design doc |
|---|---|---|---|
| FR-2.1 | A target is created from pasted bytecode, an uploaded artifact, or a contract address for retrieval. | P0 | §2.3, §11.4 |
| FR-2.2 | Bytecode type is recorded as **runtime** or **init**; the two are never mixed silently. | P0 | §6.1 |
| FR-2.3 | The original artifact is stored and a cryptographic hash computed. | P0 | §5.1 step 3 |
| FR-2.4 | Provenance is recorded (source URI, retrieval method, authorization status). | P0 | §6.1, §9.1 |
| FR-2.5 | The add-target flow shows a validation preview: byte length, hash, parser compatibility, truncation warning. | P0 | §11.4 |
| FR-2.6 | A mainnet target shows a warning; analysis stays read-only. | P0 | §11.4 |
| FR-2.7 | Scanning bytecode **must not** request a wallet connection. | P0 | §11.4 |

### 2.3 Disassembly

| ID | Requirement | Priority | Design doc |
|---|---|---|---|
| FR-3.1 | Bytecode is tokenized into **decoded instructions**, not raw hex bytes. | P0 | §6.2 |
| FR-3.2 | `PUSH1`–`PUSH32` immediates are consumed as data and never decoded as opcodes. | P0 | §6.1 |
| FR-3.3 | A truncated `PUSH` at the end of the code is reported as malformed and handled deterministically. | P0 | §6.1, §14.1 |
| FR-3.4 | An opcode that does not exist in the target fork is reported as unknown for that fork, not decoded. | P0 | §6.1, §6.3 |
| FR-3.5 | Each instruction exposes byte offset, opcode byte, canonical name, immediate bytes, size, stack effect, and containing block. | P0 | §6.3 |
| FR-3.6 | Disassembly is **fork-aware**: the opcode set depends on the target EVM fork. | P0 | §6.1, §8.2 |
| FR-3.7 | Solidity metadata (CBOR) trailers are detected, not decoded as instructions, and the original bytes are never modified. | P0 | §6.2 |
| FR-3.8 | N-grams are generated over opcode **names** with configurable N; default N = 3. | P0 | §6.2 |
| FR-3.9 | Raw and normalised features (PUSH width, constants, addresses, compiler metadata) are kept separate. | P0 | §6.2 |

### 2.4 Control-flow graph

| ID | Requirement | Priority | Design doc |
|---|---|---|---|
| FR-4.1 | Basic blocks are identified at terminators, branch targets, and valid `JUMPDEST` locations. | P0 | §6.3 |
| FR-4.2 | The CFG is a general directed graph. **Acyclicity is never assumed.** | P0 | §6.3, §18.4 |
| FR-4.3 | Edge confidence is tracked as **resolved**, **inferred**, or **unresolved**. | P0 | §6.3, §9.1 |
| FR-4.4 | Dynamic jump targets are tracked and reported, not guessed. | P0 | §6.3 |
| FR-4.5 | Cycles are detected and reported. | P0 | §6.4 |
| FR-4.6 | Unreachable regions are identified and their byte size reported. | P0 | §11.5 (warnings) |

### 2.5 Feature extraction

| ID | Requirement | Priority | Design doc |
|---|---|---|---|
| FR-5.1 | Opcode counts and opcode frequencies are computed per contract. | P0 | §6.2, §6.4 |
| FR-5.2 | N-gram frequencies are computed (default N = 3). | P0 | §6.2 |
| FR-5.3 | Block size, instruction mix, branch count, unresolved-jump count, and cycle count are computed. | P0 | §6.4 |
| FR-5.4 | `CALL`/`STATICCALL`/`DELEGATECALL`/`CREATE`/`CREATE2` locations are recorded. | P0 | §6.4 |
| FR-5.5 | `SLOAD`/`SSTORE` locations are recorded. | P0 | §6.4 |
| FR-5.6 | Call-to-storage-write ordering is recorded as a signal. | P0 | §6.4, §6.5 |
| FR-5.7 | The feature schema is versioned and stored with the scan. | P0 | §6.2, §9.1 |
| FR-5.8 | Feature extraction is deterministic: the same bytecode and fork produce the same feature vector. | P0 | §15 |

### 2.6 Detection

| ID | Requirement | Priority | Design doc |
|---|---|---|---|
| FR-6.1 | A deterministic rule engine runs on every scan. | P0 | §5.1 step 7, §4 P0.7 |
| FR-6.2 | Reentrancy detection is **multi-signal**; a `CALL` before an `SSTORE` is a heuristic only, never proof. | P0 | §6.5 |
| FR-6.3 | MVP reentrancy wording is "Potential reentrancy pattern — manual validation required". | P0 | §6.5 |
| FR-6.4 | Detections map to bytecode offsets and basic-block IDs. | P0 | §6.5, §6.6 |
| FR-6.5 | Severity and confidence are **separate fields** and are never conflated. | P0 | §6.6, §11.9 |
| FR-6.6 | Every finding carries detector ID, detector version, evidence, and limitations. | P0 | §6.6 |
| FR-6.7 | Findings are deduplicated and mapped to evidence ranges and blocks. | P0 | §5.1 step 8 |

### 2.7 ML scoring

| ID | Requirement | Priority | Design doc |
|---|---|---|---|
| FR-7.1 | The scanner runs **with ML disabled** and remains fully functional. | P0 | §23.2 |
| FR-7.2 | An optional ML model returns calibrated scores and candidate labels through a model-adapter interface. | P0 | §4 P0.7, §23.2 |
| FR-7.3 | The baseline model is scikit-learn TF-IDF over opcode n-grams plus the deterministic numeric features. | P0 | §6.2, §23.1, ADR-0006 |
| FR-7.4 | The TF-IDF vocabulary is fit only on the training corpus, persisted, versioned, and reused for inference. | P0 | §6.2 |
| FR-7.5 | Train/test splits are at contract/project/family level, never random bytecode fragments. | P0 | §6.2, §13.1 |
| FR-7.6 | Model-based results are labelled **experimental** until the release gate is met. | P0 | §12, §18.14 |
| FR-7.7 | A GNN is **not** an MVP requirement. | P0 | §6.4, §24.1, ADR-0006 |

### 2.8 Scan execution and orchestration

| ID | Requirement | Priority | Design doc |
|---|---|---|---|
| FR-8.1 | A scan is queued and runs **asynchronously**; the API returns `202 Accepted` with a scan ID and status URL. | P0 | §5.1, §10.1 |
| FR-8.2 | The scan lifecycle exposes each pipeline stage: validation → disassembly → blocks/CFG → features → rules → ML → normalisation → complete. | P0 | §11.7, §11.8 |
| FR-8.3 | A scan ends as **completed**, **partial**, or **failed**, with a reason. | P0 | §5.1 step 9 |
| FR-8.4 | Jobs are idempotent and retryable; no silent result loss. | P0 | §15 |
| FR-8.5 | Job creation routes support request IDs and idempotency keys. | P0 | §10.1 |
| FR-8.6 | Scan creation and uploads are rate-limited. | P0 | §10.1 |
| FR-8.7 | Each scan records the parser, ruleset, feature-schema, and model versions, plus the input hash. | P0 | §15, §18.5 |
| FR-8.8 | The sandbox reproduction is a **separate, explicitly approved action** — never a default part of a scan. | P0 | §4 P0.9, §11.6 |

### 2.9 Finding review and feedback

| ID | Requirement | Priority | Design doc |
|---|---|---|---|
| FR-9.1 | The review workflow is `New → Triage → Confirmed / False Positive / Needs More Evidence → Report Draft → Reviewer Approved → Exported`. | P0 | §5.2 |
| FR-9.2 | A finding must **not** be called confirmed solely because a classifier score crosses a threshold. | P0 | §5.2 |
| FR-9.3 | Reviewer decisions are recorded with actor, decision, comment, and timestamp. | P0 | §9.1, §11.10 |
| FR-9.4 | The UI shows a finding as a **candidate** until reviewed, and explains that ML scores are prioritisation signals, not proof. | P0 | §5.2, §12 |

### 2.10 Reporting

| ID | Requirement | Priority | Design doc |
|---|---|---|---|
| FR-10.1 | Report types: internal scan summary, finding technical report, responsible-disclosure draft, executive summary. | P0 | §11.12 |
| FR-10.2 | A report includes scope, target hashes, tool versions, methodology, limitations, evidence, reproduction details, and remediation suggestions. | P0 | §11.12 |
| FR-10.3 | Internal notes and secrets are redacted from reports. | P0 | §11.12, §18.11 |
| FR-10.4 | A responsible-disclosure report requires **reviewer approval** before export. | P0 | §11.12, §18.8 |
| FR-10.5 | No automatic submission to any bounty or disclosure platform. | P0 | §11.12 |

### 2.11 Sandbox reproduction

| ID | Requirement | Priority | Design doc |
|---|---|---|---|
| FR-11.1 | Static analysis is the default and never executes target code on a public network. | P0 | §7.1 |
| FR-11.2 | Dynamic execution happens only in an isolated local EVM, controlled fork, or explicitly authorised environment. | P0 | §7.1 |
| FR-11.3 | The sandbox has no outbound network by default, strict CPU/memory/wall-clock limits, an ephemeral filesystem, and no host secrets. | P0 | §7.1, §4 P0.9 |
| FR-11.4 | PoC generation produces test code for review; execution requires a human approval gate. | P0 | §7.1 |
| FR-11.5 | No automatic asset transfer, mainnet signing, or private-key use in the MVP. | P0 | §7.1, §3.2 |

### 2.12 Audit log

| ID | Requirement | Priority | Design doc |
|---|---|---|---|
| FR-12.1 | Audit events record timestamp, actor, action, resource type, resource, outcome, and request ID. | P0 | §11.15, §9.1 |
| FR-12.2 | Target creation, scan requests, report exports, permission changes, model releases, sandbox approvals, and authentication events are logged. | P0 | §11.15 |
| FR-12.3 | Sensitive metadata is redacted before storage. | P0 | §7.3, §11.15 |
| FR-12.4 | The audit log is append-only from the application's perspective. | P0 | §7.3 |

### 2.13 UI/UX

| ID | Requirement | Priority | Design doc |
|---|---|---|---|
| FR-13.1 | The interface is a security operations console: deep-charcoal / neon-green palette, restrained and legible, using the specified design tokens. | P0 | §11.1 |
| FR-13.2 | Status is never conveyed by colour alone; semantic colour plus text/icon is used. | P0 | §11.1 |
| FR-13.3 | The global shell has a left sidebar (logo, workspace switcher, primary navigation), a top bar (breadcrumb, environment badge, search, notifications, profile), and a main content area with a page title, subtitle, and right-aligned primary CTA. | P0 | §11.1 |
| FR-13.4 | Navigation covers Overview, Contract Targets, Scans, Findings, CFG Explorer, Reports, Model Lab, Infrastructure, Audit Log, Settings. | P0 | §11.1 |
| FR-13.5 | The disassembly table is virtualised, searchable by offset/opcode, and selecting a row highlights the corresponding CFG node and finding evidence. | P0 | §11.5 |
| FR-13.6 | The CFG Explorer distinguishes unresolved edges visually and textually, and supports slicing, lazy rendering, and a text/list alternative. Thousands of nodes are never rendered at once. | P0 | §11.11 |
| FR-13.7 | Major workflows have explicit loading, empty, partial, failed, and success states. | P0 | §18.12 |
| FR-13.8 | Empty states provide one clear next action. | P0 | §12 |
| FR-13.9 | Timestamps display in the user's locale and are stored in UTC. | P0 | §12 |
| FR-13.10 | Every chart has a title, time range, legend, and accessible text alternative. | P0 | §12 |
| FR-13.11 | The desktop is the primary target; tablet and mobile degrade to readable summaries with a list view. | P0 | §11.18 |

### 2.14 API contract

| ID | Requirement | Priority | Design doc |
|---|---|---|---|
| FR-14.1 | All routes are under `/api/v1` and require authentication unless explicitly public. | P0 | §10 |
| FR-14.2 | Workspace membership and RBAC are enforced server-side on every route. | P0 | §10, §3.2 |
| FR-14.3 | Standard HTTP status codes with a consistent error envelope. | P0 | §10.1 |
| FR-14.4 | Stack traces, RPC credentials, filesystem paths, and secrets are never exposed. | P0 | §10.1 |
| FR-14.5 | Cursor pagination is used for large result sets. | P0 | §10.1 |
| FR-14.6 | API response contracts and feature schemas are versioned. | P0 | §10.1, §15 |
| FR-14.7 | `/health` returns liveness/readiness with restricted detail. | P0 | §10 |

### 2.15 Documentation and developer setup

| ID | Requirement | Priority | Design doc |
|---|---|---|---|
| FR-15.1 | The repository has a README covering setup, running the API/worker/web app/tests, and troubleshooting. | P0 | §4 P0.12, Appendix B.10 |
| FR-15.2 | A runbook documents local startup, migrations, tests, and troubleshooting. | P0 | §19.3, §22 |
| FR-15.3 | Architecture decisions are recorded as ADRs. | P0 | §17 Phase 0, §27 |

---

## 3. Non-functional requirements

Derived from design doc §15, §7.3, §14, §19.

### 3.1 Reliability

| ID | Requirement | Design doc |
|---|---|---|
| NFR-R1 | Jobs are idempotent and retryable; no silent result loss. | §15 |
| NFR-R2 | A failed scan records a machine-readable error code and a redacted message. | §9.1, §11.7 |
| NFR-R3 | The scanner remains usable with local fixtures when an external provider is unavailable. | §26 |
| NFR-R4 | Database metadata and artifact storage are backed up independently, and a restore drill is performed. | §7.3, §19.3 |

### 3.2 Scalability and performance

| ID | Requirement | Design doc |
|---|---|---|
| NFR-P1 | Queue workers scale independently of web/API processes. | §15 |
| NFR-P2 | Queue wait time is reported separately from execution duration. | §15, §11.7 |
| NFR-P3 | Numeric SLOs are set **after** profiling and deployment constraints are known; no scan-latency promise is made before benchmark data exists. | §15 |
| NFR-P4 | Hard application limits exist on bytecode size, scan concurrency, retry count, report exports, and sandbox resources. | §26 |

### 3.3 Observability

| ID | Requirement | Design doc |
|---|---|---|
| NFR-O1 | Structured logs with request IDs. | §15, §23.1 |
| NFR-O2 | Metrics for API request count/error rate/latency percentiles, queue depth, oldest job age, retries, scan stage duration, parser warnings, unresolved-jump rate, ML latency, DB pool and query latency, artifact failures. | §19.1 |
| NFR-O3 | Alerts on queue backlog, missing worker heartbeat, repeated parser/ML failures, elevated 5xx or latency, DB/storage unavailability, sandbox outbound-network attempts, and unusual export or permission-change activity. | §19.2 |
| NFR-O4 | Operational runbooks exist for stuck scans, dead-letter recovery, version rollback, credential rotation, backup restore, session revocation, sandbox shutdown, and incident response. | §19.3 |

### 3.4 Security

| ID | Requirement | Design doc |
|---|---|---|
| NFR-S1 | OWASP-aligned secure coding, CSRF protection where applicable, input validation, rate limits, secure headers. | §7.3 |
| NFR-S2 | Secrets are managed through environment/secret manager and never committed. | §7.3 |
| NFR-S3 | Sensitive data is encrypted in transit and at rest. | §7.3 |
| NFR-S4 | Private artifacts are served through signed, expiring URLs; object keys are never in public URLs. | §7.3, §23.1 |
| NFR-S5 | Database access is tenant-scoped, with cross-tenant access tests. | §7.3, §14.2 |
| NFR-S6 | Dependency scanning, SBOM generation, and pinned production dependencies. | §7.3 |
| NFR-S7 | No secrets appear in logs, error messages, or exported reports. | §18.11, §14.3 |

### 3.5 Maintainability and reproducibility

| ID | Requirement | Design doc |
|---|---|---|
| NFR-M1 | Typed API contracts, versioned migrations, linting, formatting, and CI. | §15 |
| NFR-M2 | Every scan stores parser/rules/model/feature versions and the input hash, so results are reproducible from stored facts. | §15, §18.5 |
| NFR-M3 | UI, API, parser, rules, model inference, and sandbox sit behind explicit module interfaces. | §23.2 |
| NFR-M4 | A model adapter allows scikit-learn and any future GNN to be swapped without changing API contracts. | §23.2 |
| NFR-M5 | An object-storage adapter lets local storage and a cloud bucket share one interface. | §23.2 |
| NFR-M6 | Environment variables drive configuration, validated at startup. | §23.2 |
| NFR-M7 | Dependency versions are pinned and the lockfile committed. | §23.4 |
| NFR-M8 | CI passes lint, type checking, unit tests, integration tests, and production build. | §18.13 |

### 3.6 Explainability and accessibility

| ID | Requirement | Design doc |
|---|---|---|
| NFR-X1 | Every candidate finding links to evidence and limitations. | §15, §6.6 |
| NFR-X2 | Every finding shows severity, confidence, detector version, and byte offsets. | §18.6 |
| NFR-X3 | Keyboard support, WCAG AA contrast, semantic labels, and non-colour-only status indicators. | §15, §11.1 |
| NFR-X4 | All primary actions work with a keyboard and a screen reader. | §11.18 |

### 3.7 Portability

| ID | Requirement | Design doc |
|---|---|---|
| NFR-PT1 | Local development runs on native PostgreSQL 17.11 and Redis 8.10.3 with documented startup commands. **No Docker.** | ADR-0003 |
| NFR-PT2 | The environment configuration is documented and validated at startup. | §16, §25, Appendix B.1 |
| NFR-PT3 | Local development uses only free-tier resources; no paid service is required to run the project. | §24, §26 |

---

## 4. Severity taxonomy

Design doc §6.6 requires severity and confidence to be separate fields. The
`Severity` enum is implemented in `apps/api/app/db/enums.py`; the frontend
mirrors it in `apps/web/src/lib/types.ts` as `SEVERITY_ORDER`.

| Level | Meaning | Examples of the kind of candidate it covers |
|---|---|---|
| `critical` | Candidate with direct, plausible loss of funds or total control, with concrete evidence | Unprotected `selfdestruct` on a live, funded implementation; arbitrary `delegatecall` to an attacker-controlled address |
| `high` | Candidate with a realistic path to fund loss or privilege escalation | Reentrancy pattern with a state write after an external call; missing access control on a privileged function |
| `medium` | Candidate with a plausible impact that requires additional conditions | Unchecked external call return value; `tx.origin` authentication |
| `low` | Candidate with limited impact or strong preconditions | Missing event emission; gas inefficiency |
| `info` | Observation with no direct security impact | Unused code paths; informational compiler notes |

**Rules that apply to every level:**

1. Severity describes the **candidate's plausible impact**. Confidence
   describes **how sure the detector is**. They are stored in separate columns
   and must never be derived from one another.
2. A finding is a **candidate** until a reviewer acts on it. §5.2 forbids
   calling a finding "confirmed" solely because a classifier score crosses a
   threshold.
3. Every finding must state its **limitations**. A detector that cannot
   establish exploitability says so: "Static pattern only; exploitability has
   not been confirmed."
4. Every finding maps to byte offsets and basic-block IDs so the evidence can
   be inspected in the disassembly and CFG views.
5. Model-based findings carry the **experimental** label until the §13.3
   release gate is satisfied.
6. The taxonomy must not be used to imply a financial value. A `critical`
   finding is not "worth" anything; see
   [ADR-0008](adr/0008-no-airdrop-bounty-or-campaign-promises.md).

---

## 5. Explicitly out of scope for the MVP

Each item names the design-doc section that mentions it, and the reason it is
not an MVP requirement.

| Item | Design doc | Why out of scope |
|---|---|---|
| **Campaign tracking of any kind** — campaigns, tasks, wallet labels, activity ledger, reward records | §1, §4 P1, §5.3, §9.2, §11.17, §18.15, §20 | [ADR-0007](adr/0007-campaign-tracking-out-of-mvp-scope.md). Also the highest compliance-risk surface in the document: §7.2 records anti-Sybil evasion, proxy rotation, and bot-bypass concerns that must not exist in the product. |
| **Any airdrop, allocation, token-value, or campaign-reward promise or metric** | §1, §1.2, §2, §11.3, §20, Appendix A | [ADR-0008](adr/0008-no-airdrop-bounty-or-campaign-promises.md). The product makes no revenue or reward promise and carries no such telemetry. |
| **Guaranteed bounty income or guaranteed vulnerability discovery** | §1.2, §18 | §1.2 non-goal. |
| **Automatic submission to bounty or disclosure platforms** | §11.12 | §11.12 states it directly. |
| **A Graph Neural Network** | §6.4, §17 Phase 4, §23.1, §24.1 | [ADR-0006](adr/0006-scikit-learn-tfidf-baseline-gnn-deferred.md). Requires labelled graph-level data that does not exist, plus a compute budget that does not depend on an unverified free tier. |
| **Symbolic execution** | §4 P1, §11.6 | P1. Referenced in the scan wizard as an optional module "if available". |
| **Differential bytecode comparison; proxy/implementation resolution** | §4 P1, §11.5 | P1. |
| **Call-graph and cross-contract relationship views** | §4 P1, §11.5 | P1. |
| **Model registry, calibration, and drift monitoring UI** | §4 P1, §11.13 | P1. The registry is a §9.1 table, not an MVP surface. |
| **Scheduled scans for authorised targets** | §4 P1 | P1. |
| **Multi-chain adapters beyond the first EVM network** | §4 P2 | P2. |
| **Team analytics and customer workspaces** | §4 P2 | P2. |
| **Protocol-authorised testnet task automation** | §4 P2 | P2, and gated behind a new ADR. |
| **Enterprise SSO, advanced retention, private deployment** | §4 P2 | P2. |
| **Mainnet transaction execution or autonomous asset movement** | §1.2, §7.1 | Non-goal. |
| **Anti-Sybil evasion, bot-detection bypass, identity concealment** | §1.2, §7.2 | Non-goal, and not built. |
| **Docker / containerised local development** | §8.2, §16, §23.1, §24.1, §24.4, §27, Appendix B.1 | [ADR-0003](adr/0003-no-docker-native-postgres-and-redis.md). |
| **Prisma ORM and a Node/TypeScript backend** | §8.1, §23.3, §27, Appendix B.2 | [ADR-0001](adr/0001-python-backend-over-node-prisma.md). |
| **BullMQ as the task queue** | §8.2, §23.1, §23.4 | [ADR-0001](adr/0001-python-backend-over-node-prisma.md). RQ is used instead. |
| **`pyevmasm` as the production parser** | §8.2, §21.3 | [ADR-0004](adr/0004-custom-vendored-opcode-table.md). Stale: it lacks `PUSH0` and other modern opcodes. |
| **`evmole` in the production scan path** | §8.2, §21.3 | [ADR-0005](adr/0005-evmole-as-cross-validation-oracle.md). It is a validation oracle only. |
| **A Finance / Outcomes dashboard** | §20 | Explicitly "Optional, Not MVP Core". |
| **Any claim that free-tier services are "production-ready at no cost"** | §26 | §26 requires a current official source and a clear explanation of limits. |

---

## 6. Traceability

Each requirement maps to the design-document section it came from. Where a
section was corrected, the ADR that governs it is named.

| Design doc section | Requirements derived | ADR / note |
|---|---|---|
| §1, §1.1 | Personas (§1), NFR-X1 | — |
| §1.2 | §5 out-of-scope table | ADR-0008 |
| §2.1, §2.2 | §5 out-of-scope table | ADR-0008 |
| §2.3 | FR-2.1, FR-2.2, FR-2.7 | — |
| §3, §3.1, §3.2 | FR-1.1…FR-1.6, §1.1 permission principles, NFR-S5, FR-11.5 | — |
| §4 (P0 list) | FR-2.x…FR-13.x, §5 out-of-scope | ADR-0007 for campaigns |
| §5.1 | FR-2.3, FR-8.1…FR-8.4, FR-8.7 | — |
| §5.2 | FR-9.1…FR-9.4 | — |
| §5.3 | *None — out of scope* | ADR-0007 |
| §6.1 | FR-2.2, FR-2.3, FR-3.2, FR-3.3, FR-3.6 | ADR-0004 (fork-aware table) |
| §6.2 | FR-3.1, FR-3.7, FR-3.8, FR-3.9, FR-5.1, FR-5.2, FR-5.7, FR-7.3, FR-7.4 | ADR-0004, ADR-0006 |
| §6.3 | FR-4.1…FR-4.6 | ADR-0004 |
| §6.4 | FR-5.3…FR-5.6, FR-7.7 | ADR-0006 (GNN deferred) |
| §6.5 | FR-6.2, FR-6.3, FR-6.4 | — |
| §6.6 | FR-6.5, FR-6.6, FR-6.7, §4 severity taxonomy, NFR-X2 | — |
| §7.1 | FR-11.1…FR-11.5 | — |
| §7.2 | *None directly — constraints recorded* | ADR-0007, ADR-0008 |
| §7.3 | FR-1.2, NFR-S1…NFR-S7, FR-12.3, FR-12.4 | — |
| §8.1 | *Corrected* | ADR-0001 (Python API), ADR-0002 (Next.js client) |
| §8.2 | *Corrected* | ADR-0001, ADR-0003, ADR-0004 |
| §9.1 | FR-1.3, FR-2.4, FR-8.7, §3.2 of architecture doc | ADR-0007 (campaign tables dropped) |
| §9.2 | *None — out of scope* | ADR-0007 |
| §10, §10.1 | FR-8.5, FR-8.6, FR-14.1…FR-14.7 | — |
| §11.1 | FR-13.1…FR-13.4, NFR-X3, NFR-X4 | ADR-0002 |
| §11.2 | FR-1.1, FR-1.6 | — |
| §11.3 | FR-13.x, §5 out-of-scope | ADR-0008 |
| §11.4 | FR-2.1, FR-2.5, FR-2.6, FR-2.7 | — |
| §11.5 | FR-2.4, FR-4.6, FR-13.5 | — |
| §11.6 | FR-8.8 | — |
| §11.7, §11.8 | FR-8.2, FR-8.3, NFR-R2, NFR-P2 | — |
| §11.9, §11.10 | FR-6.5, FR-9.1…FR-9.4 | — |
| §11.11 | FR-13.6 | — |
| §11.12 | FR-10.1…FR-10.5 | ADR-0008 |
| §11.13 | FR-7.6 | ADR-0006 |
| §11.14 | NFR-O2, NFR-O3 | — |
| §11.15 | FR-12.1…FR-12.4 | — |
| §11.16 | FR-1.5, FR-3.x settings | — |
| §11.17 | *None — out of scope* | ADR-0007 |
| §11.18 | FR-13.11, NFR-X4 | — |
| §12 | FR-9.4, FR-13.8, FR-13.9, FR-13.10 | — |
| §13.1 | FR-7.5 | — |
| §13.2 | §5 out-of-scope (model release process) | ADR-0006 |
| §13.3 | FR-7.6 | ADR-0006 |
| §14.1 | FR-3.3, FR-3.4, FR-3.7 | ADR-0005 (oracle) |
| §14.2 | NFR-S5 | — |
| §14.3 | NFR-S7 | — |
| §14.4 | *Validation scripts only* | ADR-0005 |
| §15 | NFR-R1, NFR-P1…NFR-P4, NFR-O1, NFR-M1, NFR-M2, NFR-X1…NFR-X4, NFR-PT2 | ADR-0003 (portability bullet) |
| §16 | NFR-PT2 | ADR-0001, ADR-0003 |
| §17 | FR-15.3 | ADR-0006 (Phase 4 scope) |
| §18 | FR-3.2, FR-4.2, FR-8.7, FR-9.1, FR-10.3, FR-10.4, FR-11.3, FR-13.7, FR-13.8, NFR-M2, NFR-S7 | ADR-0007 (item 15 withdrawn) |
| §19.1, §19.2, §19.3 | NFR-O2, NFR-O3, NFR-O4, NFR-R4 | — |
| §20 | *None — out of scope* | ADR-0007, ADR-0008 |
| §21 | FR-3.6, FR-7.3, FR-7.7, §5 out-of-scope | ADR-0004, ADR-0005, ADR-0006, ADR-0007 |
| §22 | FR-15.2, FR-15.3, NFR-S2, NFR-S7 | ADR-0007, ADR-0008 |
| §23.1 | FR-7.2, FR-7.3, FR-8.1, NFR-M3…NFR-M6, NFR-O1 | ADR-0001, ADR-0002, ADR-0003, ADR-0004, ADR-0006 |
| §23.2 | FR-7.1, FR-7.2, NFR-M3, NFR-M4, NFR-M5, NFR-M6 | ADR-0001, ADR-0006 |
| §23.3 | *Corrected* | ADR-0001, ADR-0002 |
| §23.4 | FR-3.6, NFR-M7 | ADR-0001 (now governing) |
| §24 | NFR-PT3 | ADR-0003 |
| §24.1 | FR-7.7, NFR-PT3, §5 out-of-scope | ADR-0003, ADR-0006 |
| §24.4 | NFR-PT3 | ADR-0003 |
| §25, §25.1–§25.7 | FR-14.x, NFR-M6, NFR-PT2 | ADR-0001 (§25.2 corrected) |
| §26 | NFR-R3, NFR-P4, §5 out-of-scope | — |
| §27 | FR-15.3, §5 out-of-scope | ADR-0001, ADR-0002, ADR-0003, ADR-0004, ADR-0005, ADR-0006 |
| Appendix A | §5 out-of-scope | ADR-0008 |
| Appendix B | FR-15.1, FR-15.2, NFR-PT2 | ADR-0001, ADR-0003 |

---

## 7. Resolved open questions

Design doc §21 lists fourteen questions for the product owner. The ones that
this project has answered are recorded here with the governing ADR. The rest
remain open and are genuinely for the owner to decide.

| §21 question | Status | Answer / ADR |
|---|---|---|
| 3. Which disassembler/static-analysis libraries are acceptable? | **Answered** | Custom `packages/evm_analysis` with a vendored, fork-accurate table; `pyevmasm` rejected; `evmole` retained as a validation oracle only. ADR-0004, ADR-0005. |
| 5. Is the first ML deliverable a baseline classifier or is a GNN mandatory? | **Answered** | Baseline classifier. scikit-learn TF-IDF; GNN deferred with explicit reopening conditions. ADR-0006. |
| 10. Should campaign tracking ship in P1 or be removed from the first product? | **Answered** | Removed from the MVP. ADR-0007. |
| 8. What deployment budget and target concurrency are available? | **Answered (partially)** | Free tier only; no paid service is required. ADR-0003, NFR-PT3. |
| 1. Initial chain list and supported fork range | **Partially answered** | Fourteen forks `frontier` → `prague` are supported by the vendored table. The initial chain list is still open. ADR-0004. |
| 2. Will users paste bytecode, provide addresses, upload artifacts, or all three? | **Answered** | All three are supported. `POST /api/v1/scans` accepts bytecode hex or an address to fetch; a standalone targets/upload API is not built. FR-2.1. |
| 4. Is there a labelled dataset? | **Open — blocking for ML** | No labelled dataset is known to exist. This blocks FR-7.3. ADR-0006 lists it as reopening condition 1. |
| 6. Which user roles and workspace boundaries are needed for the first customer? | **Answered** | The six roles of §3.1, with workspace-level isolation. FR-1.4, §1.1. |
| 7. Which report formats are mandatory? | **Open** | §11.12 lists PDF/Markdown/JSON export; which is mandatory is undecided. |
| 9. Which campaign interactions are explicitly allowed by each target protocol? | **Moot for the MVP** | Campaigns are out of scope. ADR-0007. |
| 11. What is the actual seed raise target? | **Open — business, not engineering** | Also §2.2's allocation reconciliation. ADR-0008 forbids presenting it as a product commitment. |
| 12. Which financial forecast assumptions are supported by historical evidence? | **Open — business, not engineering** | §2.1 marks these as hypotheses. ADR-0008. |
| 13. What constitutes success for the first 30/60/90 days? | **Open** | — |
| 14. Who is accountable for reviewing findings and approving disclosure reports? | **Open** | The `reviewer` role exists (FR-1.4) but the accountable person is unassigned. |

## 8. Implementation status of the MVP requirements

This section records which requirements above are **actually implemented** in
the repository as of 2026-10-28. It is a status report, not a requirement —
nothing here adds to or removes from §2. The authoritative as-built detail is
in [`docs/architecture.md`](architecture.md).

Legend: **Met** — implemented and tested · **Partial** — implemented in some
form, with a named gap · **Not built** — specified but absent.

| Requirement area | Status | Evidence / gap |
|---|---|---|
| FR-2.2 Contract target intake | **Partial** | `POST /api/v1/scans` creates the target and the scan. No standalone targets router; no artifact upload path; `abi_object_key` is never populated. |
| FR-2.3 Disassembly | **Met** | `packages/evm_analysis/evm_analysis/disassembler.py`; 15 unit tests. |
| FR-2.4 Control-flow graph | **Met** | `cfg.py`, `stack.py`, `resolver.py`; 20 unit tests. |
| FR-2.5 Feature extraction | **Met** | `features.py`; deterministic, versioned. |
| FR-2.6 Detection | **Partial** | 6 baseline detectors in `services/rules.py`. Control-flow-transfer and check-effects-interactions analysis are not implemented, so the reentrancy rule stays a heuristic. No false-positive feedback path. |
| FR-2.7 ML scoring | **Partial** | The `packages/ml_baseline` package is complete and tested, but it is **not** called by the scan pipeline. `ENABLE_EXPERIMENTAL_ML` defaults to `false`. No model registry; no labelled dataset (open question 4). |
| FR-2.8 Scan execution | **Met** | `app/worker.py` + `services/pipeline.py`; 4 worker tests. |
| FR-2.9 Finding review and feedback | **Partial** | `findings` are read via `GET /api/v1/findings`. No status-transition endpoint, no analyst decision recording, no false-positive feedback. |
| FR-2.10 Reporting | **Not built** | No `reports` table, no builder, no export format, no approval gate. The web app reads findings from the API instead. |
| FR-2.11 Sandbox reproduction | **Not built** | `workers/sandbox_runner/` is empty; `SANDBOX_ENABLED=false`. |
| FR-2.12 Audit log | **Partial** | The `audit_events` table exists with a redacted-metadata column, but no route writes to it and no audit router exists. |
| FR-2.13 UI/UX | **Partial** | 6 pages and 9 components. The web client sends no `X-API-Key`, so authenticated calls return `401`; the scan-detail page requests an endpoint the backend does not serve. |
| FR-2.14 API contract | **Partial** | 7 routes serve scans, findings, and health. There is no `GET /api/v1/scans/{id}/findings`, no targets endpoint, and no finding mutation route. |
| FR-2.15 Documentation and setup | **Met** | This document set, the ADRs, the runbook, and `README.md`. |
| §1.1 RBAC server-side enforcement | **Partial** | API-key principals and workspace scoping exist. The six-role RBAC model is modelled but there is no role-checked authorisation beyond workspace filtering. |
| NFR-M1 Reproducibility | **Met** | Input hash, opcode-table version, fork, and tool versions are stored per scan. |
| NFR-S1–S3 Credential handling | **Met** | API keys are stored as SHA-256 digests; audit metadata is redacted before write. |
| NFR-PT1–PT2 Free-tier / no-Docker | **Met** | Native PostgreSQL 17.11 and Redis 8.10.3. ADR-0003. |
| NFR-PT3 Portability | **Partial** | Documented as Windows/MSYS native. No Linux or macOS path is validated. |

**Not built at all, and not claimed anywhere:** campaign tracking (ADR-0007),
any airdrop/bounty/campaign-income promise or metric (ADR-0008), and the
graph neural network (ADR-0006, deferred).

---
