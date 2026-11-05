# ADR 0020 — Human identity via Google OAuth, API keys for machines

**Status:** accepted, implementation in progress
**Date:** 2026-11-05
**Relates to:** `docs/PENDING.md` §3.2, ADR-0010 (server-only frontend API key),
ADR-0021 (workspace isolation).

## Context

CyberStratum is a commercial multi-tenant product. Two kinds of caller have to
be authenticated, and they are not the same kind of thing:

- **A person** uses the product through the browser. They need a real
  identity, a session that survives a page reload, and a way to be a member of
  a workspace.
- **A machine** — CI, a scanner, a partner integration — calls the API
  directly. It has no browser, no session and no human present.

The schema already carries the shape of both: `users.auth_provider_id` (the
provider's subject id), `users.password_hash`, `api_keys.key_hash`,
`workspaces`, and `workspace_members`. What is missing is the *flow* that
turns a Google sign-in into a session, and the rule that binds a session to
a workspace.

A tempting shortcut is to let the browser hold the static service `API_KEY`
and call the API directly from the client. That is rejected: it would put an
administrative credential in every browser, and it would make per-customer
isolation impossible, because the key is not scoped to a workspace.

## Decision

1. **Humans authenticate with Google OAuth (OpenID Connect, authorization code
   flow with PKCE).** The browser is redirected to Google, comes back with an
   authorization code, and the backend exchanges that code for an id token.
   The backend verifies the id token's signature against Google's JWKS, its
   issuer, its audience and its expiry — the backend never trusts an
   unverified claim from the browser.
2. **A successful sign-in issues a session token**, signed with
   `AUTH_SECRET` (HMAC), carried in an `HttpOnly`, `Secure`,
   `SameSite=Lax` cookie. The token is never readable by JavaScript, so a
   cross-site scripting bug cannot exfiltrate it.
3. **Machine callers use hashed API keys.** The raw key is shown once, at
   creation, and only its SHA-256 digest is stored. A key belongs to a user
   and therefore to that user's workspace.
4. **The static service key stays, but it is explicitly administrative.** It
   is not scoped to a workspace and it can read across tenants. It is for the
   frontend server and for trusted automation only — never for a browser and
   never for a customer. This is stated in `deploy/vps/app.env.example` and
   in `docs/DEPLOYMENT.md`.
5. **Every authenticated request resolves to exactly one workspace**, and
   every query is filtered by it. A session whose user is not a member of any
   workspace is denied rather than granted an unscoped view.

## Consequences

- The frontend keeps its server-only key: the Next.js server talks to the
  backend on the browser's behalf. Browser traffic never carries the
  administrative key.
- The backend needs a Google OAuth client id and secret. They are deployment
  configuration, never committed.
- A refresh path is deferred: the session cookie is short-lived
  (`ACCESS_TOKEN_TTL_MINUTES`, 8 hours by default). A user signs in again
  after it expires. Refresh tokens with their own stored hashes are the next
  step, not this one.
- Password login stays out. `users.password_hash` exists in the schema for
  compatibility, but no password flow is built, and none should be added
  without a decision of its own.

## The trap this ADR exists to prevent

A "no verdict" is never a "clean". The same discipline applies to identity:
**an unauthenticated or unverified caller is not an administrator.** If the
OAuth state check fails, the id token cannot be verified, or the session
token's signature does not check out, the request is rejected — it is never
treated as an unscoped service call. A failed identity check must not
degrade into "give up and let them in".
