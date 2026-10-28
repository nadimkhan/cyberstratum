# ADR-0007: Campaign tracking out of MVP scope

- **Status:** Accepted
- **Date:** 2026-10-28
- **Governs:** design-document §4, §5.3, §9.2, §11.1, §11.17, §18 item 15, §20, §21, §22, §23.2

## Context

The design document carries a second workstream alongside bytecode security
analysis: tracking participation in authorised testnet campaigns. It appears
throughout:

- §1 describes the product as having "two related workstreams": bytecode
  analysis and "Authorized ecosystem research: manage approved testnet
  campaigns and wallet activity".
- §5.3 specifies an "Authorized campaign workflow" with campaign records,
  tasks, activity logs, eligibility tracking, and reward states.
- §9.2 lists five optional P1 tables: `campaigns`, `campaign_tasks`,
  `wallet_labels`, `campaign_activity`, `reward_records`.
- §11.1 navigation item 8 is "Campaigns (P1; hidden until enabled)".
- §11.17 specifies the full Campaigns page.
- §18 item 15 makes campaign behaviour an acceptance criterion.
- §20 specifies an optional Finance/Outcomes page with bounty and token
  categories.
- §21 question 10 asks: "Should campaign tracking ship in P1 or be removed from
  the first product?"

The workstream also carries the highest compliance risk in the document. §7.2
records that the source pitch "mentions behavioural randomisation, anti-Sybil
controls, residential proxies, and bypassing anti-bot filters", and states:
"These are not MVP requirements. The product must not conceal coordinated
identities or evade a protocol's eligibility controls." §1.2 lists as
non-goals: "Guaranteed airdrop eligibility, allocations, token value, or
liquidity" and "Anti-Sybil evasion, bot-detection bypass, proxy rotation to
disguise identity, or violating campaign terms."

Meanwhile §4's P0 (must ship) list does **not** include campaign tracking — it
appears only under P1 ("After MVP validation"). So the document already places
campaigns outside the MVP; what it lacks is a decision to remove the ambiguity
rather than leave it as an open question.

## Decision

**Campaign tracking is out of scope for the MVP.** It is not implemented, not
modelled, and not on the roadmap for the MVP release.

Specifically:

- **No campaign data model.** The §9.2 tables (`campaigns`, `campaign_tasks`,
  `wallet_labels`, `campaign_activity`, `reward_records`) are **not** created
  in the MVP schema. No SQLAlchemy models, no Alembic migrations, no tables.
- **No campaign workflow.** §5.3 is not implemented.
- **No Campaigns page.** §11.17 is not built, and the navigation item is not
  present at all in the MVP shell.
- **No campaign feature flag.** `ENABLE_CAMPAIGN_TOOLING` is **not** added.
  There is no disabled code path to accidentally enable.
- **§18 item 15 is withdrawn** from the MVP acceptance criteria, because
  "campaign tracking, if enabled" cannot be satisfied by something that does
  not exist. The underlying compliance principles — no anti-Sybil evasion, no
  prohibited actions, official terms recorded — are retained as product-wide
  constraints in
  [ADR-0008](0008-no-airdrop-bounty-or-campaign-promises.md).
- **§20's Finance/Outcomes page remains out of scope** as well; it is
  explicitly optional and not MVP core, and it exists only to support the
  financial-reporting material covered by ADR-0008.

Campaign tracking may return in a later release. If it does, it requires a
new ADR that must, at minimum: define the data model, define what evidence a
task requires, and confirm the compliance controls in §7.2 are implementable
before any UI is built.

## Consequences

**Positive**

- The MVP has one job: bytecode security analysis. The scope in §4 P0 is
  implementable and testable.
- The highest-compliance-risk surface in the document is not built, so the
  anti-Sybil-evasion, proxy-rotation, and bot-bypass concerns in §7.2 do not
  need to be engineered around. They cannot be engineered *around*; they can
  only be engineered *not to exist*.
- §22's "During coding" checklist item "Use feature flags for experimental ML
  and campaign tooling" becomes a single flag (`ENABLE_EXPERIMENTAL_ML`).
- The MVP schema is smaller and every table in it is a table the scanner
  actually uses.

**Negative / accepted cost**

- The source pitch's second workstream is not addressed by the product at
  all. If the business case depends on it, that is a business-plan gap and
  should be stated to the product owner explicitly — it is not something
  engineering can resolve.
- §1's "two related workstreams" framing becomes "one workstream". The
  design document is corrected to say so rather than leaving a half-presented
  feature in the spec.
- No campaign data accumulates, so a future campaign feature starts from zero
  and cannot be back-filled from this product's history.

**Explicitly not decided here**

- Whether campaign tracking ships in P1, P2, or never. That is a product
  decision for the owner and is deliberately left open.

## Design-document sections resolved

- **§1** — the "two related workstreams" framing is corrected to reflect that
  the product ships the analysis workstream only; the campaign workstream is
  out of MVP scope.
- **§4** — P1's "Approved testnet campaign tracker" bullet is annotated as out
  of MVP scope; P2's protocol-authorised task automation bullet is annotated
  as requiring a new ADR before any work.
- **§5.3** — annotated as not implemented in the MVP.
- **§9.2** — the "Optional P1 tables" list is annotated as not part of the MVP
  schema.
- **§11.1** — navigation item 8 ("Campaigns") is annotated as out of MVP
  scope; the MVP navigation has seven items plus Infrastructure, Audit Log,
  and Settings.
- **§11.17** — annotated as not built for the MVP.
- **§18 item 15** — withdrawn from the MVP acceptance criteria.
- **§20** — remains explicitly optional and out of MVP core.
- **§21 question 10** — answered for the MVP: campaign tracking is removed
  from the first product.
- **§22** — the checklist item on campaign feature flags is narrowed to ML.
- **§23.2** — the architecture rules are unchanged in substance; no campaign
  adapter or flag is introduced.
