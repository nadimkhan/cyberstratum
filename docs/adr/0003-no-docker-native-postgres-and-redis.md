# ADR-0003: No Docker; native local PostgreSQL and Redis

- **Status:** Accepted
- **Date:** 2026-10-28
- **Governs:** design-document §8.2, §16, §23.1, §24.1, §24.4, §27, Appendix B

## Context

The design document repeatedly prescribes Docker Compose for local
infrastructure:

- §8.2 "Suggested stack": "Deployment: Docker Compose for local development".
- §16 "Suggested Repository Structure" lists `infra/docker/` and a top-level
  `docker-compose.yml`.
- §23.1 "Selected stack": "Local services | Docker Compose | Reproducible local
  Postgres, Redis, API, and worker setup."
- §24.1 lists "Local Docker Postgres" and "Local Redis in Docker for
  development" as the fallback options for PostgreSQL and Redis.
- §24.4 "Initial recommendation", item 2: "Docker Compose for local PostgreSQL
  and Redis."
- §27 "Recommended default": "develop locally with Docker Compose".
- Appendix B ticket 1: "Create monorepo, CI, Docker Compose, and environment
  validation."

Docker Compose is a reasonable default in many projects, but it is not
neutral here. It imposes a container runtime on every contributor, requires
the developer machine to have a working Docker Desktop / engine (which on
Windows brings WSL2 or Hyper-V into the dependency chain), and obscures the
actual version of PostgreSQL and Redis in use — a material concern for a
project whose §26 requires the team to know exactly what it is running and
what it costs.

The project is also free-tier-only (§24) and single-developer in its current
phase, so the primary benefit of Compose — reproducible multi-service startup
across many machines — buys little.

Native local installations already exist on this machine at pinned versions:

- PostgreSQL 17.11 — binaries at `E:/tools/pg17/pgsql/bin`, data directory
  `E:/data/cyberstratum/pgdata`, port 5433.
- Redis 8.10.3 — binaries at
  `E:/tools/redis8/Redis-8.10.3-Windows-x64-msys2`, port 6379.

## Decision

**CyberStratum does not use Docker.** There is no `docker-compose.yml`, no
`Dockerfile`, and no `infra/docker/` directory in the repository.

Local development runs **native** services:

| Service | Version | Location | Port |
|---|---|---|---|
| PostgreSQL | 17.11 | `E:/tools/pg17/pgsql/bin` | 5433 |
| Redis | 8.10.3 | `E:/tools/redis8/Redis-8.10.3-Windows-x64-msys2` | 6379 |

The exact start/stop commands are documented in `docs/runbook.md`. The
PostgreSQL cluster is a dedicated instance for this project on port 5433 (not
the default 5432), so it cannot collide with any other PostgreSQL on the
machine. The application connects through `postgresql+psycopg://` to database
`cyberstratum`, with a separate `cyberstratum_test` database for tests.

The design document's §24 free-tier *hosted* provider research is unaffected:
hosted Neon/Supabase/Upstash remain valid options for staging, and the
PostgreSQL adapter is URL-driven so switching is a configuration change.

**Explicitly not in scope:** containerisation of the API/worker for production
deployment. If production hosting later needs containers, that is a separate
decision with its own ADR, and it does not change the local development path.

## Consequences

**Positive**

- No container runtime in the contributor's dependency chain. A new developer
  needs PostgreSQL, Redis, Python, and Node — and the exact versions are
  pinned and documented.
- The database and queue versions in local development are exactly the versions
  documented, which supports §26's requirement to know real costs and
  §14's reproducibility requirements.
- Port 5433 isolates this project's cluster from any other PostgreSQL on the
  machine.
- Starting the stack is two commands, both of which are inspectable and
  scriptable outside Docker.

**Negative / accepted cost**

- Setup is **not** one-command reproducible for a brand-new machine. The
  runbook has to carry the manual steps (install / `initdb` / create role and
  databases / set `pg_hba.conf`).
- The environment is not isolated from the host the way a container is: the
  PostgreSQL data directory and the Redis working directory are host paths
  owned by the project, and the developer is responsible for them.
- CI must provision PostgreSQL and Redis as services (or use ephemeral
  equivalents) rather than `docker compose up`; this is a CI concern only and
  does not affect the local path.

**Follow-up obligation**

- `docs/runbook.md` must contain the exact, copy-pasteable commands, including
  the role/database creation step, since that step is no longer hidden inside
  a Compose file.

## Design-document sections resolved

- **§8.2** — the deployment bullet becomes "native local PostgreSQL 17.11 and
  Redis 8.10.3; no Docker".
- **§15** — the "Portability: local Docker development" bullet is annotated to
  point at this ADR.
- **§16** — the repository-structure listing drops `infra/docker/` and
  `docker-compose.yml`.
- **§23.1** — the "Local services" row becomes native PostgreSQL + Redis.
- **§24.1** — the "Local Docker Postgres" / "Local Redis in Docker" fallbacks
  become the native installs.
- **§24.4** — item 2 becomes native local PostgreSQL and Redis.
- **§27** — items 3 and 4 ("local Docker first") become "local native install
  first"; the "Recommended default" paragraph drops Docker Compose.
- **Appendix B** — ticket 1 becomes "Create monorepo, CI, and environment
  validation" and no longer includes Docker Compose.
