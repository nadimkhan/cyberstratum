# CyberStratum Architecture Decision Records

This directory is the authoritative log of technical decisions for CyberStratum.

The product design document
(`../../CyberStratum_Product_Technical_Design_Documentation.md`) was written
before the implementation stack was settled and contains mutually contradictory
statements about the backend language, ORM, and job queue. These ADRs resolve
those contradictions. **Where an ADR and the design document disagree, the ADR
governs.** Every corrected section of the design document carries a dated
"Correction note" that points at the governing ADR.

## Index

| ADR | Title | Status | Date |
|---|---|---|---|
| [0001](0001-python-backend-over-node-prisma.md) | Python backend over Node/TypeScript + Prisma | Accepted | 2026-10-28 |
| [0002](0002-nextjs-frontend.md) | Next.js frontend | Accepted | 2026-10-28 |
| [0003](0003-no-docker-native-postgres-and-redis.md) | No Docker; native local PostgreSQL and Redis | Accepted | 2026-10-28 |
| [0004](0004-custom-vendored-opcode-table.md) | Custom vendored fork-accurate opcode table | Accepted | 2026-10-28 |
| [0005](0005-evmole-as-cross-validation-oracle.md) | `evmole` as cross-validation oracle only | Accepted | 2026-10-28 |
| [0006](0006-scikit-learn-tfidf-baseline-gnn-deferred.md) | scikit-learn TF-IDF baseline; GNN deferred | Accepted | 2026-10-28 |
| [0007](0007-campaign-tracking-out-of-mvp-scope.md) | Campaign tracking out of MVP scope | Accepted | 2026-10-28 |
| [0008](0008-no-airdrop-bounty-or-campaign-promises.md) | No airdrop, bounty, or campaign promises | Accepted | 2026-10-28 |
| [0009](0009-sourcify-bytecode-acquisition.md) | Sourcify as the bytecode source; RPC and user-supplied bytes | Accepted | 2026-10-28 |
| [0010](0010-server-only-frontend-api-key.md) | The frontend API key is server-only | Accepted | 2026-10-28 |
| [0011](0011-static-jump-resolution.md) | Static jump resolution with an abstract stack, and its limits | Accepted | 2026-10-28 |

## Format

Each ADR contains:

- **Status** — `Proposed`, `Accepted`, `Superseded by ADR-XXXX`, or `Rejected`.
- **Date** — the date the decision was taken.
- **Context** — the problem, including the design-document sections in conflict.
- **Decision** — what was decided, stated so that it can be checked.
- **Consequences** — what becomes easier, what becomes harder, and what is
  explicitly not being done.

## Change process

1. Add a new ADR with the next free number. Never renumber an existing ADR.
2. Supersede rather than delete: mark the old ADR `Superseded by ADR-XXXX` and
   add a pointer line to it.
3. When an ADR changes the design document, edit the affected section and add a
   dated correction note referencing the ADR number.
4. ADRs are append-only history. If a decision was wrong, supersede it.
