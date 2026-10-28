# ADR-0008: No airdrop, bounty, or campaign promises

- **Status:** Accepted
- **Date:** 2026-10-28
- **Governs:** design-document §1, §1.2, §2, §2.2, §7.2, §11.3, §18, §20, §21, §22, Appendix A

## Context

The source material behind the design document makes revenue and participation
claims that §2 already flags as unverified:

- §2.1 lists claims needing evidence before external use, including "95% of
  public airdrop campaigns being diluted by spam", "Billions in losses
  attributable specifically to unvetted pre-launch contracts", "The projected
  frequency and value of bounty awards", and "Historical TGE averages used to
  estimate airdrop value".
- §2.2 reconciles a financial model of $515,000 bounty revenue plus $470,000
  "vested airdrop value" for $985,000 total, and then states plainly:
  "airdrop value is not the same as realised cash revenue until tokens are
  received, transferable, liquid, and sold or otherwise monetised."
- §1.2 lists as a non-goal: "Guaranteed vulnerability discovery or guaranteed
  bounty income" and "Guaranteed airdrop eligibility, allocations, token value,
  or liquidity."
- §11.3 says the dashboard must "not show projected bounty or airdrop revenue as
  if it were actual revenue".
- Appendix A maps the pitch deck's "Bug-bounty business model" and "Airdrop
  business model" rows to implementation.

The risk is specific: a security tool that appears to promise income becomes a
tool that attracts people who will act on an unverified promise, and it
reputationally damages the analysis product. §1.1's outcome "Track authorized
testnet campaigns, tasks, costs, eligibility notes, and evidence without
promising rewards" shows the intent; what is missing is a binding commitment
that the product surface never carries the promise at all.

## Decision

**CyberStratum makes no airdrop, bounty-income, or campaign-reward promise, and
the product surface does not carry such a promise in any form.**

Binding rules:

1. **No promise of reward.** The product never states or implies that using it
   yields income, tokens, allocations, airdrop eligibility, bounty payouts, or
   any other financial return. This includes UI copy, onboarding text, API
   response fields, documentation, and marketing materials derived from this
   repository.
2. **No reward telemetry.** There are no fields, dashboards, or exports for
   "expected reward", "airdrop value", "bounty earnings", "estimated
   allocation", or equivalents. A metric that cannot exist cannot be
   misread as a projection.
3. **No financial dashboard in the MVP.** §20's Finance/Outcomes page is out of
   scope (see [ADR-0007](0007-campaign-tracking-out-of-mvp-scope.md)). If it
   is ever built, every number must carry a source and a state —
   `actual`, `pending`, `estimated`, or `forecast` — with forecast figures
   visibly distinct from actuals, per §20.
4. **Findings are not money.** A confirmed finding is not described as
   "worth", "pays", or "earns". The product's value proposition is
   *evidence quality*, not payout size.
5. **Source claims stay labelled as claims.** §2.1's hypotheses remain marked
   as **hypotheses**, **targets**, or **management projections** in any
   material derived from this repository. Marketing and investor materials must
   distinguish actual results, backtests, and forecasts.
6. **No autonomous exploitation.** Independently of the reward question: the
   product never automatically exploits third-party live contracts, drains
   assets, evades anti-bot or anti-Sybil controls, impersonates users, or
   submits reports without researcher approval (§1). PoC execution is confined
   to a local fork, a dedicated sandbox, or a program-authorized environment
   (§7.1).
7. **No wallet connection to scan.** §11.4's requirement stands: scanning
   bytecode must not request a wallet connection.

## Consequences

**Positive**

- The product cannot be mistaken for an income tool. The honest value
  proposition — better static analysis with reproducible evidence — is the only
  one the product makes.
- §2's discipline about unverified claims is enforced at the implementation
  level, not just documented.
- No telemetry that a reader could quote as a projection. The absence of a
  "projected value" field removes an entire class of misrepresentation.
- Security posture is tighter: with no reward path, there is no incentive to
  run PoCs against live contracts, which keeps the §7.1 sandbox boundary
  coherent.
- Research effort goes into analysis quality — the thing that is actually
  verifiable — rather than into dashboards about money that does not exist.

**Negative / accepted cost**

- The product's appeal is narrower than the pitch implies. It is a
  professional analysis tool, not a participation-and-earn platform.
- If the business model genuinely depends on bounty income or airdrops, that
  model is not served by this product, and the gap is a business-plan issue
  for the product owner. It must not be papered over in the product.
- Some readers may find the absence of a "potential earnings" number
  unsatisfying. The absence is the point.

**Explicitly not in scope**

- Any legal or financial advice about bounty programmes, token allocations, or
  campaign eligibility.
- Bug-bounty *workflow* support (submission tracking, report templates) where
  it serves triage and evidence preparation only — §1 permits CyberStratum to
  "assist researchers with triage, evidence, and report preparation". That
  assistance is about the quality of the analysis, not about predicted payout.
  No submission is made automatically to any bounty platform (§11.12).

## Design-document sections resolved

- **§1** — the "Authorized ecosystem research" workstream is annotated as out
  of MVP scope; the bug-bounty assistance language is retained but explicitly
  bounded to triage, evidence, and report preparation.
- **§1.2** — the non-goals list is retained and confirmed as binding.
- **§2.1 / §2.2** — the unverified claims and the financial model are
  annotated as claims/projections that must never be surfaced as product
  guarantees.
- **§7.1 / §7.2** — the safe-execution and campaign/wallet compliance
  requirements are retained in full and apply to any future campaign feature.
- **§11.3** — the dashboard requirement not to show projected bounty or
  airdrop revenue as actual revenue is retained; the MVP has no such metrics
  at all.
- **§11.12** — "No automatic submission to bounty platforms" is retained.
- **§18** — no acceptance criterion implies a reward; §18 item 15 is withdrawn
  per ADR-0007.
- **§20** — remains out of MVP scope; if built, must distinguish actual,
  pending, estimated, and forecast.
- **§22** — "Review all investor-facing claims against measured evidence"
  becomes a binding pre-release checklist item.
- **Appendix A** — the "Bug-bounty business model" and "Airdrop business
  model" rows are annotated to state that no product feature corresponds to
  them.
