# ADR-0002: Next.js frontend

- **Status:** Accepted
- **Date:** 2026-10-28
- **Governs:** design-document §8.1, §8.2, §11, §12, §23.1, §23.3, §27

## Context

The design document's UI/UX specification (§11, §12) describes a dense,
data-heavy operator console: a virtualised disassembly table, a zoomable CFG
canvas, a findings queue with many filters, a report builder with preview, an
audit log table, and a model-lab view with evaluation charts. §11.1 specifies a
dark "security operations console" design system with a concrete token palette,
and §11.18 requires desktop-first layouts with keyboard and screen-reader
support.

The design document does not, however, agree with itself about what the
frontend is *built with*. §8.1 draws "Web UI (Next.js)"; §8.2 says "Next.js
App Router, TypeScript, Tailwind CSS, shadcn/ui"; §23.1 repeats that choice and
separately lists "API validation | Zod" as a layer; §23.3 says `apps/web` is
"UI only; call the API through typed client functions"; §27 item 1 leaves
hosting open.

There is also a boundary question that §8.1's diagram invites: the diagram
shows the web UI talking to "API / Auth / RBAC (Node.js + TypeScript)", which
would make the frontend and the API one Node/TypeScript system. Per
[ADR-0001](0001-python-backend-over-node-prisma.md) that is not the case.

## Decision

The frontend is **Next.js (App Router) + React + TypeScript**, with
**Tailwind CSS + shadcn/ui** and Lucide icons, as specified in §8.2 and
§23.1.

The frontend is a **pure client of the Python HTTP API**:

- `apps/web` contains UI only. It performs no server-side database access, no
  ORM calls, and no direct PostgreSQL or Redis connections.
- All data flows through the versioned REST API at `/api/v1` (§10), with
  workspace membership and RBAC enforced server-side in FastAPI.
- Request/response types are typed on the frontend through a typed client
  function layer (`apps/web/lib`), kept separate from the components so a
  contract change surfaces in one place.
- The §23.1 "API validation | Zod" row is **not** adopted as a second schema
  authority. Server-side validation is Pydantic (the FastAPI contract).
  TypeScript types on the frontend are a compile-time consumer of that
  contract, not an independent definition of it.

## Consequences

**Positive**

- §11's specification is implementable without reinterpreting it: the App
  Router's file-based routing maps onto the §11.1 navigation list, and
  Tailwind/shadcn give the §11.1 design tokens a single implementation.
- The UI never holds database credentials or queue access, so the blast radius
  of a frontend compromise is limited to what the API already authorises for
  that session.
- Server-side RBAC in the API means the frontend cannot become a
  privilege-escalation path — §3.2's "Enforce role-based access control
  (RBAC) server-side on every API" is structurally enforced rather than
  conventional.

**Negative / accepted cost**

- No shared end-to-end type generation across the stack boundary, because the
  two sides are different languages. The frontend's types must be kept in sync
  with the FastAPI OpenAPI schema manually or via a code-generation step added
  later.
- Two build toolchains (Node for the web app, Python for the API and worker)
  instead of one.
- Next.js server components cannot be used to talk to the database directly;
  any server-rendered page that needs data must call the API.

**Explicitly not decided here**

- Which host runs the Next.js app (§27 item 1 remains open; the local
  development path is `npm run dev` in `apps/web`).
- Whether the CFG canvas (§11.11) uses a graph library or a hand-rolled SVG
  renderer. §11.11's requirement for a text/list alternative and for not
  rendering thousands of nodes at once applies regardless.

## Design-document sections resolved

- **§8.1** — the diagram's web-UI layer is explicitly a separate client of the
  Python API, not part of a Node API.
- **§8.2** — retained; it is the governing statement for the frontend stack.
- **§11.1–§11.18** — implemented as written against the Next.js + Tailwind +
  shadcn/ui stack.
- **§12** — reusable components are implemented in `apps/web/components`.
- **§23.1** — the "API validation | Zod" row is annotated as a frontend typing
  concern rather than a server-side validation authority.
- **§23.3** — `apps/web` is "UI only; call the API through typed client
  functions"; retained as written.
- **§27** — item 1 (hosting) remains explicitly open; the framework choice
  itself is no longer in question.
