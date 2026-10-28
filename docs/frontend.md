# CyberStratum frontend (`apps/web`)

The web UI is a **Next.js App Router** application written in TypeScript and styled with
**Tailwind CSS**. It is a thin client: all analysis runs in the Python/FastAPI backend and the
UI talks to it through the typed client in `src/lib/api.ts`.

- Framework: Next.js 15 (App Router), React 19, TypeScript (strict)
- Styling: Tailwind CSS v4 (`@tailwindcss/postcss`), design tokens in `app/globals.css`
- Unit tests: Vitest
- No auth provider, no analytics, no paid services — everything runs locally and offline after
  `npm install`.

## Requirements

- Node.js 20 or newer (Node 24 is what the repo is developed against)
- npm 10 or newer

## Install

The repository is an npm workspace, and `apps/web` is a workspace member, so a single install at
the repository root installs the frontend too:

```bash
cd E:/projects/cyberstratum
npm install
```

Or install only the frontend workspace:

```bash
cd E:/projects/cyberstratum/apps/web
npm install
```

## Configuration

The UI needs two environment variables:

| Variable | Default | Purpose |
| --- | --- | --- |
| `NEXT_PUBLIC_API_BASE_URL` | `http://127.0.0.1:8000` | Base URL of the FastAPI backend, **without** the `/api/v1` prefix (the client appends the versioned prefix itself). Public: it is inlined into the browser bundle. The versioned prefix is applied server-side, so this must point at the API root. |
| `API_KEY` | *(empty)* | The backend API key, sent as the `X-API-Key` header. **Server-only** — it is not prefixed with `NEXT_PUBLIC_`, so Next.js strips it from the browser bundle. |

Copy the example file to get started:

```bash
cd apps/web
cp .env.example .env.local
```

`.env.local` is git-ignored.

### Why the API key stays server-side

The backend requires an API key on every route, and the key must not reach the browser. The
web app gets this for free: every call to the backend is made from a **server component** or a
**server route handler** (`src/lib/api.ts` is never imported by a `"use client"` module), so
the header is attached on the server and the secret never enters the bundle.

If you ever add a client component that needs the backend directly, do **not** add a
`NEXT_PUBLIC_` copy of the key. Add a route handler under `app/api/` that forwards the request
and attaches the key server-side, the way `app/api/scans/route.ts` already does.

Set `API_KEY` to the same value as the `API_KEY` key in the repository `.env`. The local
development default is `dev-api-key-change-me`; change it before exposing anything beyond
`127.0.0.1`.

## Run the dev server

```bash
cd E:/projects/cyberstratum/apps/web
npm run dev
```

The UI is then served on <http://localhost:3000>. From the repository root you can also run
`npm run dev:web`.

The backend is optional for the UI to boot. If the API is not running, the pages render an
explicit **"Backend unreachable"** panel with the API base URL instead of crashing, so the
frontend can be developed without the API running.

To run the backend locally:

```bash
cd E:/projects/cyberstratum/apps/api
uvicorn app.main:app --reload --port 8000
```

## Production build

```bash
cd E:/projects/cyberstratum/apps/web
npm run build      # or: npm run build:web from the repository root
npm start          # serves the production build on http://localhost:3000
```

`npm run build` runs `next build`, which type-checks the whole project as part of the build.

## Type checking and tests

```bash
cd E:/projects/cyberstratum/apps/web
npm run typecheck   # tsc --noEmit
npm test            # vitest run
```

Both are also wired into the repository root:

```bash
npm run typecheck:web
npm run test:web
npm test             # web unit tests, then the Python pytest suite
```

## Routes

| Route | Purpose |
| --- | --- |
| `/` | Overview dashboard: totals, findings by severity, recent scans, average risk score, "needs attention" list. |
| `/scans` | All scans with status, contract address, chain and creation time. |
| `/scans/new` | Scan submission form: contract address, chain id, EVM fork, optional labels, optional bytecode hex, optional experimental ML. |
| `/scans/[id]` | Scan detail: status, pipeline stage timeline, findings table, artifacts and reproducibility metadata (tool versions, opcode-table version, bytecode hash). |
| `/findings` | Every finding with a severity filter (server-side, `?severity=high`), a confidence filter, sortable columns, detector rule id, affected function signature and byte-offset / file references. |
| `/reproducibility` | Scan index of pinned analysis versions used for re-running a result. |

## Backend contract used by the client

The client calls the versioned `/api/v1` prefix defined in the design document:

| Method | Endpoint | Used for |
| --- | --- | --- |
| `GET` | `/api/health` | Readiness of the backend (falls back to `/health`). |
| `GET` | `/api/v1/scans` | Scan list (dashboard, scans page, reproducibility page). |
| `GET` | `/api/v1/scans/:id` | Scan detail (jobs, artifacts, embedded findings). |
| `GET` | `/api/v1/findings` | Findings queue, filterable by `severity`, `status`, `category` and `scan_id`. |
| `GET` | `/api/v1/findings/summary` | Aggregate counts by severity and triage status. |
| `POST` | `/api/v1/scans` | Queue a scan. |

The client sends exactly the fields the backend accepts on `POST /api/v1/scans`
(`contract_address`, `chain_id`, `fork`, `label`, `bytecode_hex`, `enable_experimental_ml`);
the backend forbids unknown fields, so nothing extra is sent.

The backend does not expose a stage array, a risk score or a separate
`/scans/:id/findings` route. The UI therefore derives the pipeline timeline from the scan
status, the artifacts and the queue jobs, and reads findings for one scan from
`/api/v1/findings?scan_id=...`. A risk score is estimated locally from the severity
histogram when the API does not supply one, and the UI labels such values as *estimated*.

Responses are normalised in `src/lib/api.ts`: the client accepts `snake_case` or `camelCase`
keys and both bare arrays and `{data: []}`-style envelopes, and maps them onto the canonical
types in `src/lib/types.ts`. Severity and status strings are mapped onto the canonical taxonomy
in `src/lib/severity.ts` and `src/lib/status.ts`.

## Accessibility and theming

- Semantic HTML (`nav`, `main`, `table` with `caption`/`scope`, `dl`, `ol`) and a skip link.
- Severity and status are always conveyed by text as well as colour, and every badge carries an
  `aria-label`.
- Severity colour is defined in exactly one place — `SEVERITY_META` in `src/lib/severity.ts` —
  and is consumed through the `SeverityBadge` component.
- Visible focus rings on all interactive elements; sortable table headers are real buttons.
- Light and dark palettes are both provided and selected with `prefers-color-scheme`; there is no
  theme toggle and no colour-scheme dependence.

## Layout of the source

```
apps/web
├── app/                     # App Router routes
│   ├── layout.tsx           # Global shell, metadata, skip link
│   ├── globals.css          # Tailwind import + design tokens
│   ├── page.tsx             # Dashboard
│   ├── findings/page.tsx
│   ├── reproducibility/page.tsx
│   └── scans/{page.tsx,new/page.tsx,[id]/page.tsx}
├── src/components/          # SeverityBadge, StatusBadge, ScanTable, FindingTable,
│                            # RiskScoreGauge, StageTimeline, EmptyState, ApiUnreachable,
│                            # AppShell, NewScanForm
├── app/api/scans/route.ts   # Server-side proxy for scan creation
└── src/lib/                 # api.ts (typed client), types.ts, severity.ts, status.ts,
                             # format.ts
```