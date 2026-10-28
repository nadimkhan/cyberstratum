# ADR-0016 — Dependency update monitoring versus automatic upgrades

- Status: Accepted
- Date: 2026-10-29
- Related: ADR-0013 (licensing), ADR-0014 (engine portfolio)

## Context

The requirement is "all the libraries should be updated every 24 hours so we
have the latest version of things."

Taken literally — auto-upgrade every dependency every 24 hours — this is the
single most damaging thing we could do to a commercial multi-tenant product:

- Slither is AGPL-3.0. An automatic upgrade can change its detector set, its
  output schema, or its behaviour, silently invalidating our 122-detector
  mapping and changing every customer-visible finding.
- Mythril is pinned to `z3-solver<=4.12.5.0`. A transitive bump can break the
  Z3 build and take out the symbolic engine entirely.
- The bytecode engine depends on exact opcode tables and fork definitions.
  A dependency bump can shift disassembly output, which breaks
  reproducibility of every stored artifact.
- An automatic upgrade that breaks the worker at 03:00 takes down every
  customer's scan queue with no rollback and no human in the loop.

Upstream releases also arrive at unpredictable times and frequently contain
breaking changes. The 24-hour window gives no room for validation.

## Decision

**Separate "check for updates" from "apply updates".**

### Daily: monitor only

A scheduled job (every 24 hours) checks upstream release metadata and writes
a report. It never mutates the application environment.

- **PyPI** — `https://pypi.org/pypi/{package}/json` for `latest` version,
  `requires_python`, and the declared licence expression.
- **npm** — `https://registry.npmjs.org/{package}` `dist-tags.latest`.
- **GitHub releases** — for tools distributed outside a package index
  (compilers, binary engines).
- **solc** — the compiler release list at `binaries.soliditylang.org`, so a new
  compiler is known before a customer project needs it.

Verified working: the PyPI and npm endpoints above return the data we need.

The daily job writes a `toolchain_update_report` containing, per package:
current pinned version, latest available version, release date, licence
expression, Python/npm requirement, and whether the change is a major bump.

**If a licence expression changes, the report escalates immediately and
requires human review.** A dependency silently becoming AGPL is a legal event,
not a routine bump.

### Applying an upgrade: staged, gated, reversible

An upgrade is a change to the application, and it goes through the same path
as any other change:

1. A branch is cut and the version is bumped.
2. The full quality gate runs: Ruff, mypy, the Python test suite, the Vitest
   suite, the TypeScript typecheck, and the Alembic migration cycle.
3. **Engine output diffing** — the same fixed corpus is scanned before and
   after. The finding set is compared. Any detector that disappears, any
   severity that changed, any output-schema change is a **breaking change**
   and blocks the merge until reviewed.
4. **Model revalidation** — if the model baseline is affected, the candidate
   model is evaluated against the current served model on the held-out
   family-split set (ADR-0015). No silent accuracy regression.
5. **Bytecode-artifact reproducibility check** — disassembly output for the
   cross-validation corpus must be unchanged, or the opcode/fork tables need an
   explicit version bump.
6. Merge, deploy, and keep the last-known-good version pinned for rollback.

Production versions stay pinned in a lockfile. "Latest" is never a deployment
strategy.

### What does update on its own

These are low-risk and may follow the upstream release within a day:

- Compiler binaries (solc). They are pinned per verified contract anyway —
  the correspondence chain requires the *exact* compiler the contract was
  built with, so adding new solc versions strictly increases coverage.
- Frontend dependency patch/minor bumps that pass the gate.

## Consequences

- The platform stays reproducible and defensible. A customer's report can
  always name the exact tool versions that produced it.
- Upstream security fixes land within days, not immediately — accepted, and
  mitigated by the daily report giving notice.
- Tooling work is real: the diffing, the benchmark corpus, and the promotion
  gates have to be built. That cost is accepted because the alternative is
  automatic upgrades that change customer-facing findings without review.
- The daily monitor is a thin, low-risk job: read metadata, write a report.

## Alternatives considered

- **Auto-upgrade every 24 hours.** Rejected: breaks the AGPL mapping, breaks
  reproducibility, breaks the worker, and provides no review step.
- **Auto-upgrade patch versions only, automatically.** Rejected as a partial
  measure: even a patch bump in Slither can change detector behaviour, and it
  removes the review gate that catches it.
- **Never check.** Rejected: the daily report is cheap and it is how we learn
  about a licence change or a breaking release before a customer hits it.
