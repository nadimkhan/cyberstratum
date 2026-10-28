# ADR-0010: The frontend API key is server-only

- **Status:** Accepted
- **Date:** 2026-10-28
- **Governs:** design-document §7.3, §10.1, §11.2, §25.3

## Context

The backend requires an API key on every route (`X-API-Key`), as §10.1 and
§25.3 require. The frontend is a Next.js App Router application that must
therefore present that key on every call.

Next.js has two environment-variable namespaces:

- `NEXT_PUBLIC_*` — inlined into the browser bundle at build time. Anything
  prefixed this way is public to anyone who loads the page.
- Unprefixed names — read on the server only, in server components, route
  handlers, and `getServerSideProps`-equivalent code paths.

A shared API key presented by a browser-facing app is a credential handed to
every visitor. A key in `NEXT_PUBLIC_*` would be readable by anyone who opens
devtools on the page.

The design document does not say how the browser app is meant to
authenticate. §11.2 describes a sign-in page and §3 describes roles, but
neither is implemented; the backend currently accepts either a static
configured key or a per-user stored key.

## Decision

**The API key is a server-only variable. There is no `NEXT_PUBLIC_` copy of
it, and there will not be one.**

- The variable is named `API_KEY`, lives in `apps/web/.env.local`, and is
  read with `process.env.API_KEY`.
- It is attached as the `X-API-Key` header by the server-side API client
  (`apps/web/src/lib/api.ts`), which is only ever called from server
  components and server route handlers.
- The only value that reaches the browser is `NEXT_PUBLIC_API_BASE_URL`,
  which is a hostname and is not a secret.
- `apps/web/.env.local` is git-ignored. The committed `apps/web/.env.example`
  contains the variable names and placeholder values only.

Because the key never crosses into the browser, the static configured key is
acceptable for local development. The per-user stored-key path in the
backend remains the intended mechanism for a multi-user deployment, where the
key would be resolved per session on the server.

## Consequences

**Positive**

- The key is not in the JavaScript bundle, not in the page source, and not
  in the network tab of a browser request. A visitor cannot read it.
- There is one key variable, not two, so the two cannot drift apart.
- The backend's authentication stays a server-side concern; the browser app
  is a plain HTTP client of the API, exactly as ADR-0002 describes.

**Negative / accepted cost**

- The API is not callable directly from the browser. The browser talks to
  Next.js, and Next.js talks to the API. Every call costs an extra hop.
- Server components cannot be cached as freely as client-rendered data,
  because a request that depends on a credential should not be shared
  across users. The current pages are dynamic for this reason.
- A multi-user deployment still needs a session mechanism to decide *which*
  stored key to present. That is out of scope here and is recorded as a
  known gap.

**Follow-up obligation**

- If a client-side feature is ever added that needs to call the API
  directly from the browser, it must not be given the shared key. It needs a
  short-lived, scoped token issued by the Next.js server, and that design
  needs its own ADR.
