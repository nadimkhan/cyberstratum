import { cookies } from "next/headers";
import { API_BASE_URL, API_PREFIX, SESSION_COOKIE_NAME } from "./api";

/**
 * Server-side helpers for the human-identity session.
 *
 * The browser never holds the session token: it lives in an HttpOnly cookie
 * named `cs_session` and is only ever read on the server (ADR-0010). This
 * module is therefore server-only - importing it from a client component
 * would leak the token into the bundle.
 *
 * The token is exchanged for a session on the backend, never minted here.
 */

export interface AuthUser {
  id: string;
  email: string;
  displayName: string | null;
}

export interface AuthWorkspace {
  id: string;
  name: string;
  slug: string | null;
}

export interface SessionInfo {
  user: AuthUser;
  workspace: AuthWorkspace | null;
  expiresAt: string | null;
}

/** The subset of the Next.js cookie store this module needs. */
export interface CookieReader {
  get(name: string): { value: string } | undefined;
}

/**
 * Default cookie lifetime when the backend does not report an expiry.
 *
 * Eight hours, matching the backend's default `ACCESS_TOKEN_TTL_MINUTES`
 * (ADR-0020). The backend's own `expires_at` always wins when it is present.
 */
export const DEFAULT_SESSION_MAX_AGE_SECONDS = 60 * 60 * 8;

/**
 * Read the session token from a cookie store.
 *
 * Returns `null` when there is no session - an anonymous visitor is a normal
 * state, not an error.
 */
export async function readSessionToken(
  store?: CookieReader,
): Promise<string | null> {
  let cookiesApi: CookieReader;
  try {
    cookiesApi = store ?? (await cookies());
  } catch {
    // Outside a request scope (a build-time prerender, a unit test) there is
    // no session to read.
    return null;
  }
  if (!cookiesApi || typeof cookiesApi.get !== "function") return null;
  const value = cookiesApi.get(SESSION_COOKIE_NAME)?.value;
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  return trimmed === "" ? null : trimmed;
}

/**
 * Convert the backend's `expires_at` into a cookie lifetime in seconds.
 *
 * The backend may report an ISO-8601 timestamp or a Unix epoch (seconds or
 * milliseconds). Anything unparseable falls back to a conservative default so
 * a session cookie is never written without an expiry.
 */
export function sessionMaxAgeSeconds(
  expiresAt: string | number | null | undefined,
  now: number = Date.now(),
): number {
  if (expiresAt === null || expiresAt === undefined || expiresAt === "") {
    return DEFAULT_SESSION_MAX_AGE_SECONDS;
  }

  let expiresAtMs: number | null = null;

  if (typeof expiresAt === "number" && Number.isFinite(expiresAt)) {
    // Values below ~1e12 are Unix seconds; larger ones are milliseconds.
    expiresAtMs = expiresAt < 1e12 ? expiresAt * 1000 : expiresAt;
  } else {
    const parsed = Date.parse(String(expiresAt));
    if (!Number.isNaN(parsed)) expiresAtMs = parsed;
  }

  if (expiresAtMs === null) return DEFAULT_SESSION_MAX_AGE_SECONDS;

  const seconds = Math.floor((expiresAtMs - now) / 1000);
  if (!Number.isFinite(seconds) || seconds <= 0) return 1;
  return seconds;
}

/**
 * Resolve the absolute origin of the running app.
 *
 * `NEXT_PUBLIC_APP_URL` wins when it is set; otherwise the origin is derived
 * from the request headers so the same build works on Netlify, on localhost
 * and behind a proxy without hardcoding a domain.
 */
export function resolveRequestOrigin(
  headers: { get(name: string): string | null },
  configuredUrl?: string | null,
): string {
  const configured = (configuredUrl ?? "").trim();
  if (configured) return stripTrailingSlash(configured);

  const forwardedHost = headers.get("x-forwarded-host");
  const host = forwardedHost?.split(",")[0]?.trim() || headers.get("host")?.trim();
  if (!host) return "";

  const forwardedProto = headers.get("x-forwarded-proto")?.split(",")[0]?.trim();
  const proto =
    forwardedProto ||
    (host.startsWith("localhost") || host.startsWith("127.0.0.1") ? "http" : "https");

  return `${proto}://${host}`;
}

function stripTrailingSlash(value: string): string {
  return value.replace(/\/+$/, "");
}

/** Build the backend URL that starts the Google OAuth handshake. */
export function googleStartUrl(redirectUri: string): string {
  const query = new URLSearchParams({ redirect_uri: redirectUri });
  return `${API_BASE_URL}${API_PREFIX}/auth/google/start?${query.toString()}`;
}

type RawSessionRecord = Record<string, unknown>;

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function pickString(record: Record<string, unknown>, keys: string[]): string | null {
  for (const key of keys) {
    const value = record[key];
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return null;
}

function normaliseUser(value: unknown): AuthUser | null {
  const record = asRecord(value);
  const id = pickString(record, ["id", "user_id"]);
  const email = pickString(record, ["email"]);
  if (!id && !email) return null;
  return {
    id: id ?? "",
    email: email ?? "",
    displayName: pickString(record, ["display_name", "displayName", "name"]),
  };
}

function normaliseWorkspace(value: unknown): AuthWorkspace | null {
  const record = asRecord(value);
  const id = pickString(record, ["id", "workspace_id"]);
  if (!id) return null;
  return {
    id,
    name: pickString(record, ["name"]) ?? "",
    slug: pickString(record, ["slug"]),
  };
}

async function authRequest(
  path: string,
  init: RequestInit,
): Promise<{ ok: true; status: number; data: unknown } | { ok: false; status: number }> {
  try {
    const response = await fetch(`${API_BASE_URL}${API_PREFIX}${path}`, {
      ...init,
      cache: "no-store",
      headers: {
        Accept: "application/json",
        ...(init.body ? { "Content-Type": "application/json" } : {}),
        ...(init.headers ?? {}),
      },
    });

    if (response.status === 204 || response.status === 200) {
      const text = await response.text();
      let data: unknown = null;
      if (text) {
        try {
          data = JSON.parse(text) as unknown;
        } catch {
          data = null;
        }
      }
      return { ok: true, status: response.status, data };
    }
    return { ok: false, status: response.status };
  } catch {
    return { ok: false, status: 0 };
  }
}

/**
 * Exchange a one-time ticket for a session token.
 *
 * The ticket is single-use and short-lived; it is never persisted and never
 * echoed back to the browser.
 */
export async function exchangeTicket(
  ticket: string,
): Promise<
  | { ok: true; sessionToken: string; maxAgeSeconds: number; session: SessionInfo }
  | { ok: false }
> {
  const result = await authRequest("/auth/exchange", {
    method: "POST",
    body: JSON.stringify({ ticket }),
  });

  if (!result.ok) return { ok: false };

  const record = asRecord(result.data) as RawSessionRecord;
  const sessionToken = pickString(record, ["session_token", "sessionToken"]);
  if (!sessionToken) return { ok: false };

  const user = normaliseUser(record.user);
  if (!user) return { ok: false };

  const expiresAt = pickString(record, ["expires_at", "expiresAt"]);

  return {
    ok: true,
    sessionToken,
    maxAgeSeconds: sessionMaxAgeSeconds(record.expires_at as string | number | null),
    session: {
      user,
      workspace: normaliseWorkspace(record.workspace),
      expiresAt,
    },
  };
}

/**
 * Fetch the signed-in user from the backend.
 *
 * Returns `null` when there is no session, when the session has expired, or
 * when the backend cannot be reached. A signed-out visitor is a normal state.
 *
 * `token` of `undefined` means "read the session cookie"; `null` means
 * "there is no session" and skips the request entirely.
 */
export async function fetchCurrentUser(
  token?: string | null,
): Promise<SessionInfo | null> {
  const sessionToken =
    token === undefined ? await readSessionToken() : token;
  if (!sessionToken) return null;

  const result = await authRequest("/auth/me", {
    method: "GET",
    headers: { Authorization: `Bearer ${sessionToken}` },
  });

  if (!result.ok) return null;

  const record = asRecord(result.data);
  const user = normaliseUser(record.user);
  if (!user) return null;

  return {
    user,
    workspace: normaliseWorkspace(record.workspace),
    expiresAt: pickString(record, ["expires_at", "expiresAt"]),
  };
}

/**
 * End the session on the backend.
 *
 * Returns `true` when the backend confirmed the logout. The caller clears the
 * local cookie regardless: a stale cookie is worse than a cookie the backend
 * has already forgotten.
 *
 * `token` of `undefined` means "read the session cookie"; `null` means
 * "there is no session" and skips the request entirely.
 */
export async function signOut(token?: string | null): Promise<boolean> {
  const sessionToken =
    token === undefined ? await readSessionToken() : token;
  if (!sessionToken) return true;

  const result = await authRequest("/auth/logout", {
    method: "POST",
    headers: { Authorization: `Bearer ${sessionToken}` },
  });

  return result.ok;
}
