# ADR-0001: Python backend over Node/TypeScript + Prisma

- **Status:** Accepted
- **Date:** 2026-10-28
- **Governs:** design-document §8.1, §8.2, §23.1, §23.3, §23.4, §25.2, §27, Appendix B

## Context

The design document specifies the implementation stack in two mutually
incompatible ways:

- §8.2 "Suggested stack" and §23.1 "Selected stack" prescribe a **Python +
  FastAPI** API with **SQLAlchemy + Alembic** and describe the queue as
  "Redis with BullMQ or equivalent".
- §8.1 "Logical architecture" labels the API layer "API / Auth / RBAC
  (Node.js + TypeScript)", §23.3 describes `packages/database` as a "Prisma
  schema", §25.2 pairs a `postgresql+psycopg://` SQLAlchemy URL with
  "verify Prisma compatibility", §27's "Recommended default" names
  "Node/TypeScript, PostgreSQL, Redis, Prisma", and Appendix B ticket 2 says
  "Define Prisma schema for users, workspaces, targets, scans, findings, audit
  events".
- §23.4 directly contradicts all of the above: "Do not use Prisma in the Python
  backend", "**Do not use BullMQ from Python**", and "a Python-native queue
  avoids unnecessary runtime coupling".

A backend cannot be simultaneously Node/Prisma and Python/FastAPI/SQLAlchemy.
The contradiction is not cosmetic: it determines the runtime, the ORM, the
migration tool, the queue library, the test fixtures, and the shape of the
shared-type boundary between the frontend and the API.

The analysis engine itself is already Python
(`packages/evm_analysis/evm_analysis/`), and the ML baseline is
scikit-learn. A Node backend would put a network hop and a serialisation
boundary between the API and the only code that actually does the analysis.

## Decision

The backend is **Python 3.12+** with:

| Concern | Choice |
|---|---|
| API framework | FastAPI (Pydantic v2 schemas, OpenAPI generated from the app) |
| ASGI server | Uvicorn |
| ORM | SQLAlchemy 2.x |
| Migrations | Alembic |
| DB driver | `psycopg` 3 (binary), via the `postgresql+psycopg://` URL scheme |
| Task queue | **RQ** on Redis |
| Cache | Redis |
| Dependency management | `uv` with a committed lockfile |
| Lint / types | Ruff + mypy (strict) |
| Tests | pytest (+ `pytest-asyncio`, HTTPX) |

**Prisma is not used anywhere in this project.** **BullMQ is not used anywhere
in this project.** There is no cross-language queue protocol; the API enqueues
Python callables into RQ queues and Python workers consume them.

The frontend remains TypeScript and talks to the API over HTTP with a typed
client (see [ADR-0002](0002-nextjs-frontend.md)). The frontend/backend boundary
is the HTTP boundary, not a shared ORM or generated client from a Node-side
schema.

Configuration is environment-driven and validated at startup by
`apps/api/app/core/config.py` (Pydantic `BaseSettings`); `QUEUE_BACKEND` is
constrained to `rq` (or `celery` if that decision is ever revisited) and an
unknown value fails fast.

## Consequences

**Positive**

- One language across the API, the analysis engine, the worker, and the ML
  baseline. The scan pipeline shares typed domain models with the API without a
  serialisation boundary.
- The design document's §23.4 implementation notes — the section that was
  already the most detailed and most internally coherent — become the
  governing specification rather than an aside.
- Alembic migrations and SQLAlchemy models are the single source of truth for
  schema; there is no second schema definition to keep in sync.
- `postgresql+psycopg://` in §25.2 becomes correct as written instead of
  contradictory.

**Negative / accepted cost**

- No Prisma-generated TypeScript client. The frontend must hand-write or
  separately generate its API types (for example from the OpenAPI schema).
- RQ is a simpler queue than BullMQ or Celery: no built-in task routing,
  scheduling, or workflow composition. If workflow orchestration is needed
  later, the queue choice must be revisited deliberately rather than
  incrementally.
- The Python API process and the Python worker process share the codebase but
  must remain separately deployable and separately scalable (§15 scalability
  requirement).

**Explicitly not decided here**

- Which EVM library backs the tokenizer (see
  [ADR-0004](0004-custom-vendored-opcode-table.md)).
- The ML model family (see
  [ADR-0006](0006-scikit-learn-tfidf-baseline-gnn-deferred.md)).
- Where the API and worker are hosted (see
  [ADR-0003](0003-no-docker-native-postgres-and-redis.md) for local
  development).

## Design-document sections resolved

- **§8.1** — the "API / Auth / RBAC (Node.js + TypeScript)" label in the
  logical architecture diagram becomes "API / Auth / RBAC (Python + FastAPI)".
- **§8.2** — the stack bullet list is reconciled with the Python backend and the
  queue line loses "BullMQ".
- **§23.1** — the "Selected stack" table rows for API, ORM/migrations, and Queue
  are corrected to SQLAlchemy + Alembic and RQ.
- **§23.3** — `packages/database` is described as SQLAlchemy models and Alembic
  migrations, not a Prisma schema.
- **§23.4** — retained unchanged; it is now the governing statement rather than
  a contradiction.
- **§25.2** — the "verify Prisma compatibility" sentence is replaced with the
  SQLAlchemy/psycopg requirement it actually needs.
- **§27** — the "Recommended default" paragraph no longer names
  Node/TypeScript/Prisma, and items 3, 4, and 10 are resolved.
- **Appendix B** — ticket 1 drops "Docker Compose" (see ADR-0003) and ticket 2
  becomes "Define SQLAlchemy models and Alembic migrations".
