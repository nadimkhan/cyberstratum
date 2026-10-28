# ADR-0018 — Authorised scanning and responsible disclosure

- Status: Accepted
- Date: 2026-10-29
- Related: ADR-0007, ADR-0008 (campaign tracking and airdrop/bounty promises
  are outside the MVP scope), ADR-0017 (evidence model)

## Context

The request is to participate in bug bounty programs and airdrops, and to
scan mainnet for every chain so that issues can be found before they are
exploited, and then contacted the company directly.

Some of this is squarely in scope. Some of it is not, and the distinction is
not a formality — it is the difference between a security company and an
outage.

The boundary that matters:

- **Reading public chain state** — public, permissionless, already-published
  data. Scanning it is analysis. This is what the discovery feed already does.
- **Sending transactions** — writing to a chain. This is interaction with
  somebody else's system. It is not covered by "the data is public".

Program rules make this concrete. Immunefi-style programs publish a scope
list, a list of assets in scope, rules of engagement, and a safe-harbour
statement. Typical safe-harbour language is roughly: if you act in good faith,
within scope, without harming users or degrading the service, and you report
the issue as specified, you will not be sued or pursued. **Both conditions
matter** — staying in scope *and* following the reporting procedure. A finding
outside scope, or a report that bypasses the programme's process, is not
covered.

Programmes also commonly require that automated findings include a working
proof of concept, not merely a scanner's output. A finding produced by a tool
that cannot be demonstrated is, for most programmes, not a report — it is
noise, and submitting it burns credibility with that programme.

Airdrops add a second, distinct risk: many airdrop designs explicitly
prohibit Sybil behaviour and testing against the live project. Automated
interaction with an airdrop can forfeit eligibility and can be treated as
abuse.

## Decision

### In scope now

- **Continuous read-only discovery** across the supported chains via Blockscout,
  recording verified contracts and their scan status. This is already built
  (`f200d94`).
- **Read-only scanning** of any contract we discover, whether verified or not.
- **Preparing disclosure material** — the evidence, the PDF report, the
  reproduction steps — held internally until a human decides to send it.
- **Maintaining a per-programme scope registry** so that, when we want to
  submit, we know which assets are in scope, what the reporting procedure is,
  and what the safe-harbour conditions are.

### Explicitly out of scope, and why

- **Automated submission.** A human reviews and sends every report. A
  half-true report sent to a live project with real users is a real harm, and
  no confidence threshold is a substitute for a person reading it.
- **Sending transactions to live projects to test findings.** This is
  exploitation-adjacent activity against systems we do not own. It requires
  explicit per-programme authorisation, and it is not something we automate.
- **Fuzzing, symbolic execution with state mutation, or PoC execution against
  live mainnet contracts.** Our analysis is static. We do not need to touch a
  live contract to find the issue, and we will not.
- **Airdrop participation as a scanning strategy.** Many airdrops prohibit
  test traffic. We will not probe airdrop infrastructure.

### The "code or bytecode" question, answered

**Both, and the choice is driven by verification status, not preference.**

| Contract state | Primary path | Evidence produced |
| --- | --- | --- |
| Verified, correspondence chain completes | Source analysis **and** bytecode analysis, cross-checked | `source_line` **and** `bytecode_offset`, plus `source_bytecode_correlation` |
| Verified, correspondence chain fails | Source analysis only | `source_line` — with the limitation stated |
| Unverified | Bytecode analysis only | `bytecode_offset`, `bytecode_pc`, `cfg_edge` |

So: we do **both** whenever the contract allows it. The bytecode pass is
always run, because it analyses what is actually deployed and it catches
problems the source-level view misses (proxy/admin issues, immutable values,
divergence between source and deployment). The source pass adds the line
numbers. And the correspondence chain, when it completes, lets us state that
the deployed bytes are the compiled form of the line we are pointing at.

This gives the business what it asked for — a specific location — with an
honest account of how specific it is.

### Disclosure workflow

1. A scan produces findings with typed evidence.
2. A report is generated from the persisted evidence (ADR-0019).
3. The report is **reviewed by a human**. The review checks: is the evidence
   type appropriate for the claim, is the severity defensible, are the
   limitations stated, is the reproduction actually reproducible, is the asset
   in scope for the target programme.
4. Only then is it sent, through the target's published reporting channel.

The report itself states what was done and what was not done: which tools ran
and at which versions, what was analysed, what was skipped and why, and what
the evidence does not establish.

### Honesty requirements in every generated report

- No claim of exploitability beyond what the evidence shows.
- No claim of certainty that a finding is a true positive.
- The tool versions and the exact analysis inputs are stated.
- The limitations are stated.
- Unresolved analysis (unresolved dynamic jumps, skipped engines, failed
  recompiles) is stated.

## Consequences

- The platform can scan broadly and produce professional material without
  creating legal or ethical exposure. We are a research and reporting
  business, not an attack business.
- The per-programme scope registry is real work, and it is a genuine
  competitive asset — knowing scope, safe-harbour terms, and the reporting
  channel before you spend a week on a report.
- The airdrop goal, as stated, is not a scanning goal. If the underlying
  business goal is *finding vulnerabilities in projects that have airdrops*, we
  can serve that by scanning those projects' contracts — the airdrop itself is
  irrelevant to the analysis and its prohibition on test traffic is a reason
  to stay read-only.
- Reports are slower to send and far more likely to be accepted.

## Alternatives considered

- **Auto-submit findings above a confidence threshold.** Rejected: false
  positives in a disclosure are reputational damage with the programme, and
  programmes can ban reporters. A human reads every report.
- **Test against live mainnet to confirm exploitability.** Rejected: it is
  interaction with systems we do not own, it is usually out of scope, and
  static evidence is enough to start a conversation.
- **Ignore scope and report everything we find.** Rejected: out-of-scope
  reports are frequently the basis for legal action against a reporter, and
  they are frequently wrong (protocol contracts, dependencies, and test
  deployments are not vulnerabilities).
