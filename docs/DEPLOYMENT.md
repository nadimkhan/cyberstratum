# CyberStratum — Production Deployment

**Topology.** The frontend and the backend are deployed separately, on
purpose:

| Piece | Where | Why |
|---|---|---|
| Next.js frontend | **Netlify** (Next.js runtime, not static export) | The pages are server components that read the API at request time, so a static export would ship empty data. |
| FastAPI API | **Linux VPS**, behind a TLS reverse proxy | Owns the database, the queue and the analysis engines. |
| PostgreSQL | Linux VPS (or a managed instance) | Scan, finding, artifact and provenance data. |
| Redis + RQ workers | Linux VPS | Three workers: scans, Mythril (manual), correspondence (manual). |
| Mythril | **Optional**, in its own virtualenv on the VPS | Manual-only by decision (ADR-0014); it lives outside the application environment. |
| Slither | **Optional**, installed system-wide outside the app venv | AGPL-3.0, run out of process (ADR-0013). See the legal blocker below. |

**What is needed from the account owner** (nothing here is committed to the
repository, and no value below is a real credential):

- A Linux VPS — Ubuntu 22.04 or newer, 2 vCPU / 4 GB RAM is enough to start.
  A hostname, an SSH user and a way to add an SSH key.
- An A record for the API hostname (e.g. `api.example.com`) pointing at the
  VPS, so a certificate can be issued.
- A Netlify account, and the site's final origin(s).
- Optionally a Blockscout API key (free tier) for the discovery PRO route.
- Optionally a source-explorer API key.

---

## Step 1 — Provision the VPS

```bash
ssh root@<vps-ip>

apt-get update && apt-get install -y git python3.12 python3.12-venv \
    postgresql redis-server curl
```

Create the database and its application role. The role is **not** a
superuser and owns only its own database:

```bash
sudo -u postgres psql <<'SQL'
CREATE ROLE cyberstratum_app LOGIN PASSWORD '<generated>';
CREATE DATABASE cyberstratum OWNER cyberstratum_app;
SQL
```

Redis: the queue data is disposable, but a flush would discard in-flight
jobs. Point the application at its own instance or at least its own database
number (`REDIS_URL=redis://127.0.0.1:6379/1`).

## Step 2 — Clone the repository

The remote is private. Use a **deploy key** rather than a personal token:

```bash
sudo install -d -o cyberstratum -g cyberstratum /opt/cyberstratum
sudo -u cyberstratum git clone git@github.com:nadimkhan/cyberstratum.git /opt/cyberstratum/app
```

## Step 3 — Create the environment file

```bash
sudo cp /opt/cyberstratum/app/deploy/vps/app.env.example /etc/cyberstratum/app.env
sudo chown root:cyberstratum /etc/cyberstratum/app.env
sudo chmod 640 /etc/cyberstratum/app.env
sudo nano /etc/cyberstratum/app.env
```

Set at least:

```
APP_ENV=production
DATABASE_URL=postgresql+psycopg://cyberstratum_app:<password>@127.0.0.1:5432/cyberstratum
REDIS_URL=redis://127.0.0.1:6379
API_KEY=<openssl rand -hex 32>
AUTH_SECRET=<openssl rand -hex 32>
API_BASE_URL=https://api.example.com
WEB_BASE_URL=https://<site>.netlify.app
CORS_EXTRA_ORIGINS=https://<site>.netlify.app
OBJECT_STORAGE_ROOT=/var/lib/cyberstratum/artifacts
```

`API_KEY` is a **single shared administrative credential**: it is not scoped
to a workspace and it can see every tenant's data. Hand it only to the
frontend server and to trusted automation. Per-customer keys are stored
hashed in the `api_keys` table and are scoped to their workspace.

## Step 4 — Deploy

```bash
cd /opt/cyberstratum/app
sudo ./deploy/vps/deploy.sh
```

The script installs the virtualenv (every distribution editable, ReportLab
pinned), proves the application imports the working tree rather than a
copied snapshot, installs the units, migrates the database, starts the API
and the three workers, and then **verifies** that each unit is active and
that the health endpoint actually answers. It exits non-zero if any of that
fails.

## Step 5 — TLS in front of the API

```bash
sudo cp /opt/cyberstratum/app/deploy/vps/Caddyfile /etc/caddy/Caddyfile
sudo nano /etc/caddy/Caddyfile     # put your hostname in
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

The hostname in the Caddyfile must equal `API_BASE_URL`. The API itself
only ever listens on `127.0.0.1:8000`.

## Step 6 — Deploy the frontend to Netlify

1. **Add the site** in Netlify: import the existing repository
   (`github.com/nadimkhan/cyberstratum`). Do not use "Deploy manually".
2. **Build settings**: the repository's `netlify.toml` already sets the
   build command (`npm run build:web`), the publish directory
   (`apps/web/.next`), `NODE_VERSION=22` and the Next.js plugin. Nothing
   needs changing there.
3. **Environment variables** (Site configuration → Environment variables):

   | Variable | Scope | Value |
   |---|---|---|
   | `NEXT_PUBLIC_API_BASE_URL` | build | `https://api.example.com` — public build config, inlined at build time |
   | `API_KEY` | build | the same key the VPS has — **server-only** |
   | `NEXT_PUBLIC_APP_URL` | build | `https://<site>.netlify.app` — used to build the OAuth redirect URI (optional; the site also derives its own origin from the request) |
   | `GOOGLE_CLIENT_ID` | build | the OAuth client id — **server-only** |
   | `GOOGLE_CLIENT_SECRET` | build | the OAuth client secret — **server-only** |

   `API_KEY` is read by `src/lib/api.ts` on the server and sent as the
   `X-API-Key` header. It must **never** be renamed to `NEXT_PUBLIC_API_KEY`:
   that would ship the key to every browser. The same applies to
   `GOOGLE_CLIENT_SECRET`.

4. **Deploy.** The first build takes a few minutes.

## Step 7 — Verify the deployment

```bash
# API is up and reachable through TLS
curl -fsS https://api.example.com/api/v1/health

# The frontend can reach the API with the key (browser origin allowed)
curl -fsS -H "X-API-Key: $API_KEY" https://api.example.com/api/v1/scans

# Every worker registered under its own name in Redis
redis-cli keys 'rq:worker:*'
#   rq:worker:cyberstratum-worker
#   rq:worker:cyberstratum-worker-mythril
#   rq:worker:cyberstratum-worker-correspondence
```

---

## First live test — what to actually do

1. **Open the frontend.** The dashboard loads; the API is reached through
   the Next.js server, so the browser never holds the key.
2. **Scan a real contract.** Use a well-known token, for example
   `0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48` (Ethereum USDC). The scan
   is queued, the worker picks it up, and the findings list fills in.
3. **Read the evidence, not just the count.** A bytecode finding carries a
   PC, an opcode sequence and a CFG path. It carries **no source line**,
   because no correspondence has been proven for it.
4. **Trigger the manual actions** on the scan detail page:
   - *Correspondence* — recompiles the verified source with the exact
     compiler Sourcify recorded and compares the executable code. For USDC
     this is expected to come back `established` with `FiatTokenProxy.sol`
     and solc `0.4.24+commit.e67f0147`. Only then may a source line be
     claimed.
   - *Mythril* — a symbolic-execution run on its own queue. It is manual
     for a reason: it is slow, and it must never delay an ordinary scan.
     If Mythril is not installed on the VPS the button must report
     `mythril_not_installed`, **not** a clean result.
5. **Download the report.** The PDF is served with an `X-Report-SHA256`
   header, and the same bytes are stored as a scan artifact, so the issued
   document can be proven to be the one the evidence produced. Rendering
   the same evidence twice yields the same SHA-256.

### What a correct result looks like

- An engine that did not run reads as **no verdict / skipped / error** —
  never as "clean".
- The report's provenance section shows the parser, ruleset and model
  versions, the dataset and model manifest hashes, and the correspondence
  proof status. A value that does not exist reads as **not available**.
- The report states that it presents automated evidence, that it does not
  assert exploitability, and that the absence of findings is not proof of
  absence.

---

## Rolling back

```bash
cd /opt/cyberstratum/app
sudo -u cyberstratum git fetch && sudo -u cyberstratum git checkout <previous-commit>
sudo ./deploy/vps/deploy.sh
```

If the release included a migration, downgrade explicitly — a migration is
never re-run, and the downgrade path is part of the chain:

```bash
sudo -u cyberstratum env $(cat /etc/cyberstratum/app.env) \
  /opt/cyberstratum/app/.venv/bin/python -m alembic -c alembic.ini downgrade -1
```

Note that a downgrade that narrows a column removes the rows that use the
new values, and says so before it does.

## Operations

```bash
systemctl status cyberstratum-api cyberstratum-worker
journalctl -u cyberstratum-api -f
tail -f /var/log/cyberstratum/worker.log

# the daily check-only dependency update report
systemctl list-timers cyberstratum-update-check.timer
cat /var/lib/cyberstratum/update-check.json
```

The update check **reports** newer upstream versions once a day. It never
installs and never upgrades: production dependency changes go through gated
CI.

---

## Still blocked before a commercial launch

| Blocker | What it needs |
|---|---|
| Slither's AGPL-3.0 network clause | Legal review, given Slither runs out of process but is reachable by the API's users. |
| Dataset corpus redistribution | Licence terms for SmartBugs Curated / DeFiHackLabs derived artifacts, plus a per-repository audit for Web3Bugs. |
| Human sign-in | Google OAuth for humans; hashed API keys for machine clients exist already, but the OAuth flow is not built. |
| Multi-tenant isolation | Being closed out now — see `docs/PENDING.md` §3.1. |
