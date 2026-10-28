# CyberStratum — Local Development Runbook

**Audience:** anyone setting up CyberStratum on a fresh Windows machine.
**Last verified against:** the repository state on 2026-10-28.

> **Credentials.** No real credential appears in this file or in any file in
> this repository. Where a password is required, the literal placeholder
> `[REDACTED]` is used. Keep it that way: never write a real password into a
> tracked file, a command that lands in shell history, or a commit.

---

## 1. Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.12+ (3.14.x verified) | `python --version` |
| Node.js | 20+ (24.x verified) | `node --version` — needed for the opcode-table generator only |
| `uv` | any recent | `uv --version` — Python package management |
| PostgreSQL | **17.11** | Native install at `E:/tools/pg17/pgsql/bin` |
| Redis | **8.10.3** | Native install at `E:/tools/redis8/Redis-8.10.3-Windows-x64-msys2` |
| Git | any recent | `git --version` |

All commands below are written for **git-bash / MSYS** (the shell used by the
Hermes terminal on this machine). Native Windows programs such as
`postgres.exe` and `redis-server.exe` must be given **forward-slash native
paths** (`E:/tools/...`), not MSYS paths (`/e/tools/...`).

No Docker is used. See [ADR-0003](adr/0003-no-docker-native-postgres-and-redis.md).

---

## 2. Repository layout (as it exists today)

```text
E:/projects/cyberstratum/
├── apps/
│   ├── api/
│   │   ├── app/
│   │   │   ├── main.py             # create_app() — FastAPI app factory
│   │   │   ├── worker.py           # RQ worker: enqueue_scan(), process_scan_job()
│   │   │   ├── core/               # config, logging, security, errors
│   │   │   ├── db/                 # base, enums, session, models/
│   │   │   ├── api/                # health, scans, findings routers
│   │   │   ├── schemas/            # Pydantic request/response models
│   │   │   ├── services/           # pipeline, rules, bytecode, storage
│   │   │   └── queue/              # Redis + RQ connection helper
│   │   └── alembic/                # env.py + versions/
│   └── web/                        # Next.js 15 App Router app
│       ├── app/                    # 6 pages
│       └── src/                    # components/ + lib/ (typed API client)
├── packages/
│   ├── evm_analysis/
│   │   ├── evm_analysis/
│   │   │   ├── opcodes.py         # fork-aware opcode table loader
│   │   │   ├── disassembler.py    # instruction tokenizer
│   │   │   ├── metadata.py        # Solidity CBOR trailer detection
│   │   │   ├── cfg.py             # basic blocks + control-flow graph
│   │   │   ├── stack.py           # abstract stack simulation
│   │   │   ├── resolver.py        # jump-target resolution
│   │   │   └── features.py        # deterministic feature extraction
│   │   ├── data/opcodes.json      # vendored, generated opcode table (committed)
│   │   └── pyproject.toml
│   └── ml_baseline/
│       ├── evm_ml/                 # tokenize, dataset, features, model, evaluate
│       └── pyproject.toml
├── scripts/
│   ├── generate_opcodes.mjs       # regenerates data/opcodes.json
│   ├── crosscheck_evmole.py       # manual oracle cross-check (network)
│   ├── validate_real_bytecode.py  # manual real-bytecode validation (network)
│   └── build_fixture_dataset.py   # builds the smoke JSONL fixture
├── tests/
│   ├── unit/                       # 8 modules — engine + ML baseline
│   └── api/                        # 4 modules — scans, findings, worker, health
├── docs/adr/                      # architecture decision records
├── .venv/                         # Python virtual environment (uv)
├── .env.example                   # environment template
├── alembic.ini                    # Alembic config (repo root)
├── package.json                   # Node workspace (generator + web app)
└── pyproject.toml                 # Python project definition
```

---

## 3. One-time setup

### 3.1 Clone and create the virtual environment

```bash
cd /e/projects/cyberstratum

# Create the venv and install the project in editable mode with dev extras.
# requires-python is ">=3.12" for all three distributions. The existing venv
# on this machine is Python 3.14.7; use 3.12 if you prefer the floor.
uv venv --python 3.14
uv pip install -e ".[dev]"

# Install the EVM analysis package (separate distribution) in editable mode.
uv pip install -e packages/evm_analysis

# Install the ML baseline package (separate distribution) in editable mode.
uv pip install -e packages/ml_baseline

# Install the oracle used only for cross-validation (not a runtime dependency).
uv pip install "evmole==0.9.4"
```

The ML baseline's own dependencies (scikit-learn, pandas, NumPy, joblib) are
the `ml` extra of the root project:

```bash
uv pip install -e ".[ml]"
```

### 3.2 Node dependencies

```bash
cd /e/projects/cyberstratum
npm install
```

`npm install` pulls `@ethereumjs/common`, `@ethereumjs/evm` and `evm-opcodes`,
which the opcode-table generator reads for stack effects.

### 3.3 Environment file

```bash
cd /e/projects/cyberstratum
cp .env.example .env
```

Then edit `.env` and replace every placeholder with a real value **on your
machine only**. `.env` is git-ignored. At minimum:

```dotenv
DATABASE_URL=postgresql+psycopg://cyberstratum_app:[REDACTED]@127.0.0.1:5433/cyberstratum
AUTH_SECRET=[REDACTED]
```

`.env.example` ships `CHANGE_ME` placeholders. Leave them as `CHANGE_ME` in
the template; never put the real value in the template.

### 3.4 PostgreSQL cluster (first time only)

The cluster used by CyberStratum lives at `E:/data/cyberstratum/pgdata` and
listens on **5433** (not the default 5432), so it cannot collide with any other
PostgreSQL on the machine.

```bash
PG_BIN=E:/tools/pg17/pgsql/bin
PG_DATA=E:/data/cyberstratum/pgdata

# 1. Create the data directory and initialise the cluster (skip if it exists).
mkdir -p /e/data/cyberstratum
"$PG_BIN/initdb.exe" -D "$PG_DATA" -U cyberstratum --auth-local=trust --auth-host=scram-sha-256 -E UTF8

# 2. Pin the port and listen address.
cat >> "$PG_DATA/postgresql.conf" <<'EOF'
port = 5433
listen_addresses = '127.0.0.1'
EOF
```

> On Windows, `initdb.exe` writes the superuser password from a file given by
> `--pwfile`. Write the password to a file **outside the repository**, for
> example `E:/data/cyberstratum/pgpw.txt`, then:
>
> ```bash
> "$PG_BIN/initdb.exe" -D "$PG_DATA" -U cyberstratum --pwfile=E:/data/cyberstratum/pgpw.txt ...
> ```
>
> The file is outside the repository and is never committed. Its contents are
> `[REDACTED]` as far as any documentation is concerned.

### 3.5 Database role and databases

The project expects a dedicated application role and two databases:

| Object | Name | Notes |
|---|---|---|
| Superuser role | `cyberstratum` | Owns the cluster |
| Application role | `cyberstratum_app` | `CREATEDB`; owns the project databases |
| Database | `cyberstratum` | Development |
| Database | `cyberstratum_test` | Test suite |

```bash
PG_BIN=E:/tools/pg17/pgsql/bin

# Superuser login — prompt for the password, do not put it on the command line.
"$PG_BIN/psql.exe" -h 127.0.0.1 -p 5433 -U cyberstratum -d postgres

# In the psql session:
CREATE ROLE cyberstratum_app LOGIN PASSWORD '[REDACTED]' CREATEDB;
CREATE DATABASE cyberstratum        OWNER cyberstratum_app ENCODING 'UTF8';
CREATE DATABASE cyberstratum_test   OWNER cyberstratum_app ENCODING 'UTF8';
```

Then update `.env` with the same credentials you just chose:

```dotenv
DATABASE_URL=postgresql+psycopg://cyberstratum_app:[REDACTED]@127.0.0.1:5433/cyberstratum
```

**Check `pg_hba.conf`.** The TCP rules must allow password authentication
from loopback. The expected shape of `E:/data/cyberstratum/pgdata/pg_hba.conf`
is:

```text
local   all             all                                     trust
host    all             all             127.0.0.1/32            scram-sha-256
host    all             all             ::1/128                 scram-sha-256
```

If you temporarily change this file to `trust` while bootstrapping, **restore
it** and reload:

```bash
"$PG_BIN/psql.exe" -h 127.0.0.1 -p 5433 -U cyberstratum -d postgres -c "SELECT pg_reload_conf();"
```

### 3.6 Redis

Redis needs no initialisation; it is a single self-contained process with a
local persistence directory.

```bash
mkdir -p /e/data/cyberstratum
```

---

## 4. Daily start-up

### 4.0 One command

```bash
cd /e/projects/cyberstratum
npm run dev
```

This starts everything: PostgreSQL 17.11 on port 5433, Redis 8.10.3 on port
6379, the API on `http://127.0.0.1:8000`, the RQ worker, and the Next.js
dev server on `http://127.0.0.1:3100`. It runs `alembic upgrade head`
first, so the schema is current. Anything already running is left alone, so
the command is safe to re-run.

To stop everything:

```bash
npm run stop
```

`npm run stop` is the reliable stop. `Ctrl+C` also asks the stack to stop,
but npm sits between the terminal and the script and tears its own process
tree down, so the cleanup is not guaranteed to finish. `npm run stop` is
idempotent and leaves nothing behind — including the `postmaster.pid` that a
hard kill leaves behind.

The running services are owned by a detached supervisor process. Everything
the stack writes goes to `.dev-logs/dev.log`:

```bash
npm run logs
```

Flags: `--no-infra`, `--no-migrate`, `--prod`, `--api-port N`, `--web-port N`.
The paths for PostgreSQL and Redis can be moved with the `PG_BIN`, `PG_DATA`,
`PG_LOG` and `REDIS_BIN` environment variables.

The sections below describe each service on its own, which is useful when
something needs to be restarted or debugged in isolation.

### 4.1 PostgreSQL 17.11

```bash
PG_BIN=E:/tools/pg17/pgsql/bin
PG_DATA=E:/data/cyberstratum/pgdata

"$PG_BIN/pg_ctl.exe" -D "$PG_DATA" -l E:/data/cyberstratum/pg17.log -o "-p 5433" start
```

Verify:

```bash
"$PG_BIN/pg_isready.exe" -h 127.0.0.1 -p 5433
# expected: 127.0.0.1:5433 - accepting connections
```

Stop:

```bash
"$PG_BIN/pg_ctl.exe" -D "$PG_DATA" -m fast stop
```

### 4.2 Redis 8.10.3

```bash
REDIS_DIR=E:/tools/redis8/Redis-8.10.3-Windows-x64-msys2

"$REDIS_DIR/redis-server.exe" "$REDIS_DIR/redis.conf" \
  --port 6379 \
  --dir E:/data/cyberstratum \
  --logfile E:/data/cyberstratum/redis.log
```

Verify:

```bash
"$REDIS_DIR/redis-cli.exe" -p 6379 ping
# expected: PONG
```

Stop:

```bash
"$REDIS_DIR/redis-cli.exe" -p 6379 shutdown nosave
```

### 4.3 The API

```bash
cd /e/projects/cyberstratum
.venv/Scripts/python.exe -m uvicorn app.main:app --app-dir apps/api --host 127.0.0.1 --port 8000 --reload
```

> **Status:** working. `apps/api/app/main.py` exists and the app object is
> `app.main:app`. Verify it with:
>
> ```bash
> .venv/Scripts/python.exe -c "import sys; sys.path.insert(0,'apps/api'); from app.main import app; print(app.title)"
> ```
>
> The routes it serves are:
>
> | Method | Path |
> |---|---|
> | `GET` | `/health` |
> | `GET` | `/api/health` |
> | `POST` | `/api/v1/scans` |
> | `GET` | `/api/v1/scans` |
> | `GET` | `/api/v1/scans/{scan_id}` |
> | `GET` | `/api/v1/findings` |
> | `GET` | `/api/v1/findings/summary` |
> | `GET` | `/api/v1/scans/{scan_id}/findings` |
>
> Every route except `/health` requires an `X-API-Key` header. The OpenAPI
> document is at `/openapi.json` and Swagger UI at `/docs`.
>
> A quick authenticated smoke test:
>
> ```bash
> curl -s http://127.0.0.1:8000/health
> curl -s -H "X-API-Key: $API_KEY" http://127.0.0.1:8000/api/v1/scans
> ```
>
> The key is the `API_KEY` value from `.env`; the header name is `API_KEY_HEADER`
> (default `X-API-Key`). A request with no key returns `401`.

### 4.4 The RQ worker

```bash
cd /e/projects/cyberstratum/apps/api
../../.venv/Scripts/python.exe -m app.worker
```

The queue names come from `.env`: `SCAN_QUEUE_NAME=scans` and
`SANDBOX_QUEUE_NAME=sandbox`. The sandbox queue is **disabled by default**
(`SANDBOX_ENABLED=false`) and has no worker.

The worker registers itself in Redis under the name `cyberstratum-worker`.
RQ keeps that registration until the worker reports its own death, so a
worker that is killed hard — a console kill, a crash, a power cut — leaves
the registration behind, and the next worker would otherwise refuse to start
with *"There exists an active worker named 'cyberstratum-worker' already"*.
On startup the worker therefore reconciles that registration: a
registration whose process no longer exists is cleared, and one whose
process **is** still alive is left alone and reported as

```text
A worker named 'cyberstratum-worker' is already running (pid 23580).
Stop it before starting another one.
```

That is a real conflict, not a stale entry: two workers on one queue would
process scans concurrently, so the second one refuses to start.

> **Status:** working. The job function is `process_scan_job()` in
> `apps/api/app/worker.py`; the API enqueues onto the `scans` queue via
> `enqueue_scan()`. The `sandbox` and `reproduction` queue names are
> configured but have no producer or consumer.

### 4.5 The Next.js dev server

```bash
cd /e/projects/cyberstratum/apps/web
npm run dev
# expected: http://localhost:3000
```

> **Status:** working. `apps/web` is a full Next.js 15.5 App Router project
> with 6 pages under `apps/web/app/` (Overview, Scans, New scan, Scan detail,
> Findings, Reproducibility). Set `NEXT_PUBLIC_API_BASE_URL` **and** `API_KEY`
> in `apps/web/.env.local` (see `apps/web/.env.example`).
>
> The backend requires an API key on every route, so the key must be set or
> every call returns `401` and the pages render the "Backend unreachable"
> panel. `API_KEY` is **server-only** (no `NEXT_PUBLIC_` prefix): every call
> to the backend is made from a server component or route handler, so the
> header is attached on the server and the secret never enters the browser
> bundle. The value must match the `API_KEY` key in the repository `.env`.

---

## 5. Database migrations

Alembic is the migration tool ([ADR-0001](adr/0001-python-backend-over-node-prisma.md)).
The Alembic environment directory is `apps/api/alembic/` and the versions
directory is `apps/api/alembic/versions/`. The `alembic.ini` file is at the
**repository root** and points `script_location` at `apps/api/alembic` and
`prepend_sys_path` at `apps/api`, so the commands run from the repo root with
no `-c` flag.

> **Status:** working. Two revisions exist —
> `6d0038e2fcb8_initial_schema.py` and
> `9f4c1a2b7e10_add_inline_bytecode.py` (the nullable `inline_bytecode`
> column that lets a target carry user-supplied bytes) — and the development
> database is at `head`.

```bash
cd /e/projects/cyberstratum

# Apply all migrations to the development database.
.venv/Scripts/python.exe -m alembic upgrade head

# Apply migrations to the test database.
DATABASE_URL="postgresql+psycopg://cyberstratum_app:[REDACTED]@127.0.0.1:5433/cyberstratum_test" \
  .venv/Scripts/python.exe -m alembic upgrade head

# Create a new revision after changing the SQLAlchemy models.
.venv/Scripts/python.exe -m alembic revision --autogenerate -m "add <table>"

# Inspect current revision.
.venv/Scripts/python.exe -m alembic current
```

The API test suite does not use migrations — `tests/api/conftest.py` drops and
recreates the schema directly from the SQLAlchemy metadata — so a test
database does not need to be migrated by hand.

---

## 6. Tests and quality gates

```bash
cd /e/projects/cyberstratum

# Python tests (138 tests, all passing as of 2026-10-28).
.venv/Scripts/python.exe -m pytest -q

# Web tests only (4 Vitest suites).
npm run test:web

# Everything: web tests, then Python tests.
npm test

# Lint (Python).
npm run lint          # ruff check apps workers tests

# Type check (Python + TypeScript).
npm run typecheck     # mypy apps workers && tsc --noEmit
```

Coverage of the current suite:

| File | Subject |
|---|---|
| `tests/unit/test_opcodes.py` | Fork table mapping, per-fork opcode availability, stack effects, normalisation |
| `tests/unit/test_disassembler.py` | PUSH immediate handling, truncation, unknown opcodes, n-grams, metadata detection |
| `tests/unit/test_cfg.py` | Block boundaries, edge types, resolution confidence, cycles |
| `tests/unit/test_metadata.py` | Solidity CBOR trailer detection |
| `tests/unit/test_resolver.py` | Jump-target resolution and the abstract stack |
| `tests/unit/test_ml_tokenize.py` | ML opcode n-gram tokenizer, including `PUSH0` and metadata exclusion |
| `tests/unit/test_ml_dataset.py` | Provenance, family-level splits, and split-leakage prevention |
| `tests/unit/test_ml_pipeline.py` | End-to-end training run, evaluation file, manifest, adapter round-trip |
| `tests/api/test_health.py` | Liveness, readiness, OpenAPI generation |
| `tests/api/test_scans.py` | Auth, validation, job enqueue, row persistence, listing, filtering, 404 |
| `tests/api/test_findings.py` | Listing, severity/scan filters, summary, auth |
| `tests/api/test_worker.py` | Pipeline execution, findings recorded, failure handling, job lifecycle |

The API tests need a live PostgreSQL test database. `tests/api/conftest.py`
resolves `TEST_DATABASE_URL` from the environment, falling back to the
`TEST_DATABASE_URL` key in the repository `.env` file. If neither is set,
the suite **errors out** with a `RuntimeError` — it does not silently skip.
The suite also replaces the RQ enqueue call with a recording stub, so it
never needs a running worker. The web tests are
`apps/web/src/lib/*.test.ts` and need no services.

There are **no** end-to-end tests yet — `tests/e2e/` is empty.

---

## 7. Regenerating the opcode table

The opcode table `packages/evm_analysis/data/opcodes.json` is a committed,
generated artifact. Regenerate it only when the pinned upstream sources change
or when a new fork is added — and review the resulting diff carefully.

```bash
cd /e/projects/cyberstratum
npm run generate:opcodes
```

What the generator does:

1. Fetches `ethereum/execution-specs` at the **pinned tag `v2.20.0`** for each
   of the fourteen forks and parses the per-fork `Ops` enum for opcode
   availability and canonical names.
2. Merges stack effects from `evm-opcodes` (legacy) and `@ethereumjs/evm`
   (modern, EIP-5450). **If the two sources disagree on any opcode, the
   generator aborts** rather than emitting a table.
3. Validates: no duplicate codes; `0xFE` never a valid instruction; core
   opcodes present in every fork; `PUSH1` parsed correctly; no fork loses an
   opcode relative to its predecessor; every opcode has a stack effect; and a
   set of hard-coded spot-checks (`SSTORE` 2/0, `PUSH0` 0/1, `MCOPY` 3/0,
   `RETURN` 2/0, plus fork-introduction checks for `REVERT`, `SHL`, `PUSH0`,
   `MCOPY`).
4. Writes `packages/evm_analysis/data/opcodes.json` with `schemaVersion`,
   the `sources` provenance string, and the fork list.

After regenerating, always run the unit tests:

```bash
.venv/Scripts/python.exe -m pytest -q
```

The generator requires network access to `raw.githubusercontent.com`.

### 7.1 Cross-validation against `evmole` (manual, needs network)

```bash
cd /e/projects/cyberstratum
.venv/Scripts/python.exe scripts/crosscheck_evmole.py
.venv/Scripts/python.exe scripts/validate_real_bytecode.py
```

Both fetch deployed runtime bytecode for well-known verified mainnet contracts
(USDC, WETH, DAI, Uniswap V2/V3 routers, SushiSwap, Aave V3 Pool, Lido stETH)
from Sourcify and compare the instruction stream against the independent
`evmole` engine. Any divergence means at least one engine is wrong. See
[ADR-0005](adr/0005-evmole-as-cross-validation-oracle.md).

---

## 8. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `pg_ctl: could not start server` / `FATAL: could not bind ... Permission denied` | Another PostgreSQL already holds the port, or the Windows "excluded application port range" (Hyper-V/WSL dynamic reservation) has claimed 5433 | Check `netstat -ano \| grep 5433`. Pick a different port in `postgresql.conf` and in `DATABASE_URL`. |
| `FATAL: lock file "postmaster.pid" contains wrong PID` | A stale `postmaster.pid` after an abnormal shutdown | Stop any surviving `postgres.exe` (`wmic process where "name='postgres.exe'" get ProcessId`), then `pg_ctl -D <data> -m immediate stop`, remove `postmaster.pid`, restart. |
| `FATAL: password authentication failed for user "cyberstratum_app"` | The password in `.env` does not match the role, or `pg_hba.conf` was left in `trust`/`scram` mismatch | Reset the role password as the superuser (`ALTER ROLE cyberstratum_app LOGIN PASSWORD '[REDACTED]';`) and update `.env` to match. Verify the `host ... 127.0.0.1/32 scram-sha-256` line in `pg_hba.conf`. |
| `FATAL: role "postgres" does not exist` | The cluster's superuser is named `cyberstratum`, not `postgres` | Connect with `-U cyberstratum`. |
| `could not reserve shared memory region ... error code 487` | Windows shared-memory contention between PostgreSQL backends | Restart the cluster; reduce `max_connections` in `postgresql.conf` if it recurs. |
| `server process (PID ...) was terminated by exception 0xC0000142` | A backend DLL failed to load (usually ICU or antivirus interference) | Restart the cluster; confirm `icudt67.dll` and friends are present next to `postgres.exe`. |
| `redis-server.exe: command not found` / `cannot open` | MSYS path used for a native binary | Use the native forward-slash path: `E:/tools/redis8/Redis-8.10.3-Windows-x64-msys2/redis-server.exe`. |
| `redis-cli ping` → `NOAUTH` | `requirepass` set in `redis.conf` | Pass `-a [REDACTED]`, or remove `requirepass` for local-only development (Redis listens on 127.0.0.1 only). |
| `Error: connect ECONNREFUSED 127.0.0.1:6379` | Redis is not running | Start it per §4.2 and confirm `redis-cli ping` → `PONG`. |
| `ModuleNotFoundError: No module named 'evm_analysis'` | The package is not installed in the venv | `uv pip install -e packages/evm_analysis` |
| `ModuleNotFoundError: No module named 'app'` | Running from the wrong directory | Use `--app-dir apps/api` (uvicorn) or `sys.path.insert(0,'apps/api')`. |
| `opcode table not found at .../data/opcodes.json` | The generated artifact is missing | `npm install && npm run generate:opcodes` |
| `unsupported EVM fork 'osaka'` | `osaka` is not in the vendored table (only 14 forks through `prague`) | Use a supported fork. Note `DEFAULT_EVM_FORK` in `apps/api/app/core/config.py` currently still permits `osaka` in its validator — that is a known inconsistency with [ADR-0004](adr/0004-custom-vendored-opcode-table.md). |
| `Stack effect sources disagree` during generation | `evm-opcodes` and `@ethereumjs/evm` disagree | Do not bypass the check. Update one of the pinned dependencies so they agree, then regenerate. |
| `npm run generate:opcodes` fails with a fetch error | No network access to `raw.githubusercontent.com` | Retry. The committed `opcodes.json` remains usable offline. |
| Port 8000 or 3000 already in use | Another process holds the port | `netstat -ano \| grep 8000`; stop it or change `API_PORT` / use `next dev -p 3001`. |
| `RuntimeError: TEST_DATABASE_URL is not set` | The API test suite needs a dedicated test database | Add `TEST_DATABASE_URL=postgresql+psycopg://cyberstratum_app:[REDACTED]@127.0.0.1:5433/cyberstratum_test` to `.env`. The suite **errors**, it does not skip. |
| `alembic.util.exc.CommandError: Can't locate revision` | Alembic was run from the wrong directory | `alembic.ini` is at the **repo root**; run `alembic` from `E:/projects/cyberstratum`, not from `apps/api`. |
| `ModuleNotFoundError: No module named 'evm_ml'` | The ML baseline package is not installed | `uv pip install -e packages/ml_baseline` (plus `uv pip install -e ".[ml]"` for scikit-learn). |
| API returns `401` to the web app | The frontend sends no `X-API-Key` header | **Known gap, not a config error.** The API client in `apps/web/src/lib/api.ts` has no API-key mechanism yet. Call the API directly with `-H "X-API-Key: ..."` in the meantime. |
| The scan-detail page shows an error but the scan loads | The frontend calls `GET /api/v1/scans/{id}/findings`, which the backend does not serve | **Known gap.** Use `GET /api/v1/findings?scan_id=<id>` instead. |
| `import evm_analysis` works but `import evm_ml` fails inside the API | The ML package is not on the API's path | The ML package is intentionally standalone and is not imported by the API. |

---

## 9. What is not set up yet

Being explicit so that nobody waits on something that does not exist:

| Component | State |
|---|---|
| PostgreSQL 17.11 on 5433 | **Working** — installed, initialised, roles and databases present |
| Redis 8.10.3 on 6379 | **Working** — installed and responding |
| Python venv + editable installs | **Working** — `cyberstratum`, `evm_analysis`, `evm_ml` installed; 138 tests pass |
| `packages/evm_analysis` (parser, CFG, features) | **Working** — implemented and unit-tested |
| Vendored opcode table | **Working** — 14 forks, generated and committed |
| FastAPI application (`apps/api/app/main.py`) | **Working** — 7 routes, OpenAPI served at `/openapi.json` |
| SQLAlchemy models | **Working** — 15 tables in `apps/api/app/db/models/` |
| Alembic environment + migrations | **Working** — `apps/api/alembic/env.py`, one revision `6d0038e2fcb8` |
| RQ worker (`apps/api/app/worker.py`) | **Working** — `enqueue_scan()` + `process_scan_job()` |
| Baseline detectors (`apps/api/app/services/rules.py`) | **Working** — 6 rules |
| Next.js app (`apps/web`) | **Working** — 6 pages, typed API client, 9 components, 4 Vitest suites |
| ML baseline (`packages/ml_baseline/evm_ml`) | **Built as a standalone package** — not wired into the scan pipeline; see [ADR-0006](adr/0006-scikit-learn-tfidf-baseline-gnn-deferred.md) |
| Frontend API authentication | **Not implemented** — the web client sends no `X-API-Key`, so authenticated calls return `401` |
| `GET /api/v1/scans/{id}/findings` | **Not implemented** — the scan-detail page requests it and gets a 404 |
| Report model and report builder | **Not built** — no `reports` table, no export, no approval gate |
| Finding status transitions | **Not implemented** — no `PATCH` route; the `status` column is never updated |
| Sandbox runner | **Not built and disabled** — `SANDBOX_ENABLED=false` |
| End-to-end tests | **Not written** — `tests/e2e/` is empty |
| Campaign tracking | **Out of scope** — [ADR-0007](adr/0007-campaign-tracking-out-of-mvp-scope.md) |
