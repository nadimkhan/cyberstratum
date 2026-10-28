# CyberStratum Backend

The CyberStratum backend is a **Python 3.12+ / FastAPI / SQLAlchemy 2.x / Alembic / RQ**
control plane. The frontend (Next.js, `apps/web`) is a separate application and is
not covered here.

The backend is responsible for:

- accepting scan submissions and returning `202 Accepted` with a scan ID,
- queueing the work on Redis via RQ,
- running the deterministic EVM analysis pipeline in a worker,
- persisting scans, jobs, artifacts, analysis records and findings in PostgreSQL,
- serving the read APIs the frontend consumes.

---

## 1. Prerequisites

| Component | Version | Notes |
|---|---|---|
| Python | 3.12+ (3.14 supported) | Virtualenv lives at `.venv/` |
| PostgreSQL | 17.x | Isolated instance on `127.0.0.1:5433` |
| Redis | 8.x | `127.0.0.1:6379` |

The repository is a workspace: `packages/evm_analysis` (the EVM engine),
`packages/evm_ml` and `packages/sandbox_runner` are installed into the same
virtualenv. Install everything in one command from the repository root:

```bash
uv pip install --python .venv/Scripts/python.exe -e ".[dev]"
```

> On Windows the venv may not ship `pip`; use `uv pip install --python <venv>/Scripts/python.exe ...`
> as above. On macOS/Linux the interpreter path is `.venv/bin/python`.

### Environment file

The backend reads configuration from environment variables, falling back to the
repository-root `.env` file. Copy the template and fill it in:

```bash
cp .env.example .env
```

At minimum set these (all other keys have safe defaults):

```dotenv
DATABASE_URL=postgresql+psycopg://cyberstratum_app:<password>@127.0.0.1:5433/cyberstratum
TEST_DATABASE_URL=postgresql+psycopg://cyberstratum_app:<password>@127.0.0.1:5433/cyberstratum_test
REDIS_URL=redis://127.0.0.1:6379
API_KEY=<a service key you choose>
```

`.env` is git-ignored. **Never** commit real credentials; use the literal
placeholder `[REDACTED]` in any documentation.

---

## 2. Database migrations

Alembic is the single source of truth for the schema. `alembic.ini` lives at the
repository root and points `script_location` at `apps/api/alembic`. The
migration target is taken from `DATABASE_URL` (via `app.core.config`), so the
application and the migrations always target the same database.

```bash
# Apply all migrations to the configured database
.venv/Scripts/python.exe -m alembic upgrade head

# Create a new revision after changing the ORM models
.venv/Scripts/python.exe -m alembic revision --autogenerate -m "describe the change"

# Inspect state
.venv/Scripts/python.exe -m alembic current
.venv/Scripts/python.exe -m alembic history
```

The initial revision creates these tables:

`users`, `api_keys`, `workspaces`, `workspace_members`, `chains`,
`contract_targets`, `audit_events`, `scans`, `scan_jobs`, `scan_artifacts`,
`instructions`, `basic_blocks`, `cfg_edges`, `features`, `findings`.

To verify with `psql`:

```bash
PGPASSWORD=<password> /e/tools/pg17/pgsql/bin/psql.exe \
  -h 127.0.0.1 -p 5433 -U cyberstratum_app -d cyberstratum -c "\dt"
```

---

## 3. Running the API

From the repository root:

```bash
.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

`apps/api` is on the interpreter path (the workspace is installed editable), so
`app.main:app` resolves from the repository root. If you prefer to run from
`apps/api/`, the same command works with the relative venv path.

Interactive API docs:

- Swagger UI: <http://127.0.0.1:8000/docs>
- ReDoc: <http://127.0.0.1:8000/redoc>
- OpenAPI JSON: <http://127.0.0.1:8000/openapi.json>

### Health checks

```bash
curl http://127.0.0.1:8000/health
# {"status":"ok","service":"cyberstratum-api","version":"0.1.0","timestamp":"..."}

curl http://127.0.0.1:8000/api/health
# includes per-dependency "checks" for the database and the queue
```

`/health` is a public liveness probe. `/api/health` is a readiness probe that
also pings PostgreSQL and Redis; it returns `503` if a dependency is down.
Neither endpoint exposes hostnames, credentials or stack traces.

---

## 4. Running the worker

The worker consumes the RQ queue named `cyberstratum:scans`
(`QUEUE_PREFIX` + `SCAN_QUEUE_NAME`).

```bash
# Foreground
.venv/Scripts/python.exe -m app.worker

# One-shot drain of the queue (useful for local verification)
.venv/Scripts/python.exe -c "from app.worker import build_worker; build_worker().work(burst=True)"
```

RQ's default worker forks a work horse per job, which Windows does not
support. `app.worker.build_worker()` therefore returns a `SimpleWorker`
(in-process) on platforms without `os.fork` and a regular `Worker` elsewhere, so
the same entrypoint works everywhere.

The worker **degrades gracefully** when bytecode cannot be fetched: the scan row
moves to `failed` with `error_code = rpc_unreachable` and a redacted message,
and the job is marked `finished` rather than raising. This is the expected
behaviour on a machine with no reachable public RPC endpoint.

---

## 5. API surface

All routes are under `/api/v1` except the health probes, per design doc
section 10. Every route except the health probes requires the API-key header.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Public liveness probe |
| `GET` | `/api/health` | Readiness probe with dependency checks |
| `POST` | `/api/v1/scans` | Submit a scan; returns `202` and enqueues an RQ job |
| `GET` | `/api/v1/scans` | List scans (filter by `status`, `workspace_id`) |
| `GET` | `/api/v1/scans/{scan_id}` | Scan detail with jobs, artifacts and findings |
| `GET` | `/api/v1/findings` | List/filter findings (`scan_id`, `severity`, `status`) |
| `GET` | `/api/v1/findings/summary` | Severity/status breakdown and average confidence |

### Authentication

Send the configured service key in the `X-API-Key` header (header name is
configurable via `API_KEY_HEADER`):

```bash
curl -X POST http://127.0.0.1:8000/api/v1/scans \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -d '{"contract_address":"0x1111111111111111111111111111111111111111","chain_id":1,"fork":"cancun"}'
```

Response (`202 Accepted`):

```json
{
  "id": "cf3481f1-8d53-4a31-b753-e182c61efe74",
  "status": "queued",
  "status_url": "/api/v1/scans/cf3481f1-8d53-4a31-b753-e182c61efe74",
  "queue_name": "cyberstratum"
}
```

Per-user API keys stored in the `api_keys` table are also accepted; only the
SHA-256 digest is stored, never the raw key.

### Error envelope

All errors share one shape and never leak stack traces, credentials or
filesystem paths:

```json
{"error": {"code": "http_401", "message": "Missing API key. Supply the X-API-Key header."}}
```

---

## 6. Tests

The suite runs against the **separate** `cyberstratum_test` database, selected
through `TEST_DATABASE_URL`. It never depends on a running RQ worker: the
enqueue call is replaced by a recording stub.

```bash
.venv/Scripts/python.exe -m pytest tests/api -q
```

Coverage:

| File | What it covers |
|---|---|
| `tests/api/test_health.py` | Liveness, readiness, OpenAPI document |
| `tests/api/test_scans.py` | Scan submission, validation, listing, detail |
| `tests/api/test_worker.py` | Worker pipeline, finding persistence, failure recording |
| `tests/api/test_findings.py` | Finding listing, filters, severity breakdown |

### Lint and types

```bash
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m mypy apps/api/app
```

Both are clean for the backend package. `mypy` runs in `strict` mode.

---

## 7. Layout

```
apps/api/
  alembic/
    env.py                     # migration environment; uses app settings
    versions/                  # generated revisions
  app/
    api/                       # FastAPI routers (health, scans, findings)
    core/                      # config, logging, security, error handlers
    db/                        # engine/session, declarative base, enums, models
    queue/                     # Redis/RQ connection and queue factory
    schemas/                   # Pydantic v2 request/response models
    services/                  # bytecode, storage, rules, scan pipeline
    main.py                    # FastAPI application factory
    worker.py                  # RQ enqueue + worker entrypoint
tests/api/                     # pytest suite
alembic.ini                    # root Alembic config
```

---

## 8. Decisions

Where the design document is ambiguous or self-contradictory, the following
choices were made. They are recorded here so a reviewer can see where the
implementation made a call.

1. **Python/FastAPI over the document's Node/Prisma sections.** The design doc
   still contains Node/Prisma/BullMQ material. Section 10 of the doc is
   illustrative; the ADR `docs/adr/0001-python-backend-over-node-prisma.md`
   records the decision to use Python. The doc's *endpoint intent* is
   preserved, but not its runtime stack.
2. **Enum values are stored lowercase.** SQLAlchemy's `Enum` type stores member
   *names* by default. `app.db.base.enum_column()` sets `values_callable` so the
   database stores the lowercase values (`queued`, `failed`, `high`). This keeps
   the DB, the API responses and the doc's example contracts in agreement.
3. **Scan submission takes `contract_address` + `chain_id` + `fork`** rather
   than the doc's `targetId` + `analysisProfile`. The doc's example is marked
   illustrative; taking the address directly is the simplest coherent contract
   and matches the MVP scope of "scan a contract". A `workspace_id` may be
   supplied; otherwise the scan is filed under the default workspace.
4. **The API uses snake_case** (`rq_job_id`, `by_severity`, `average_confidence`)
   rather than the doc's illustrative camelCase. The doc explicitly labels its
   examples as illustrative contracts, and the final shapes are whatever the
   committed OpenAPI document says.
5. **Findings are triage signals, not confirmed vulnerabilities.** Every finding
   carries a `limitations` field and a confidence score, and the rule set is
   deliberately conservative. The doc requires that findings are not presented
   as confirmed exploitability, so no finding is auto-promoted to a
   vulnerability.
6. **Synchronous SQLAlchemy with `psycopg`.** The backend is a low-traffic
   control plane; the async engine would add complexity without throughput
   benefit. The worker is CPU-bound, not I/O-bound.
7. **Local filesystem artifact storage behind an interface.** `OBJECT_STORAGE_DRIVER=local`
   writes to `OBJECT_STORAGE_ROOT`. The storage module exposes `put_bytes` /
   `put_json` / `get_bytes` so an S3 driver can replace it without touching the
   pipeline.
8. **Health endpoints are public; everything else requires the API key.** The
   doc says routes require auth "unless explicitly marked public", and health
   probes must be reachable by a load balancer or uptime monitor.
9. **Per-user API keys are supported alongside the static service key.** Only
   SHA-256 digests are stored. A key belonging to an inactive user yields
   `403`; a missing or unknown key yields `401`.
10. **A `default` workspace is created on demand** when a scan is submitted
    without a `workspace_id`, so single-tenant local use needs no setup.
11. **`scan_jobs` rows are written by the API, not the worker.** The RQ job ID
    and the database job row are separate concerns: the row is the durable
    record of the attempt, the RQ ID points at the queue entry.

---

## 9. Troubleshooting

**`alembic upgrade head` says "Target database is not up to date"** — the
database has a revision that is not in `apps/api/alembic/versions/`. Either
restore the missing revision file or stamp the database:
`.venv/Scripts/python.exe -m alembic stamp head`.

**`password authentication failed for user`** — the credentials in `.env` do not
match the role on the PostgreSQL instance at `127.0.0.1:5433`. Note this is a
separate instance from any system-wide PostgreSQL.

**The worker logs `rpc_fetch_failed` and the scan ends as `failed`** — expected
when no public RPC endpoint is reachable. The scan records
`error_code = rpc_unreachable`; the worker did not crash.

**RQ worker exits immediately with a fork error** — you are running RQ's default
`Worker` directly. Use `app.worker.build_worker()`, which selects `SimpleWorker`
on Windows.
