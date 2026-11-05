import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  DEFAULT_SESSION_MAX_AGE_SECONDS,
  exchangeTicket,
  fetchCurrentUser,
  googleStartUrl,
  readSessionToken,
  resolveRequestOrigin,
  sessionMaxAgeSeconds,
  signOut,
} from "./auth";

const cookiesMock = vi.hoisted(() => vi.fn());

vi.mock("next/headers", () => ({
  cookies: cookiesMock,
}));

function headerValue(
  headers: HeadersInit | undefined,
  name: string,
): string | undefined {
  // `Headers` lowercases every key, so the lookup is case-insensitive.
  return new Headers(headers).get(name) ?? undefined;
}

describe("readSessionToken", () => {
  afterEach(() => {
    cookiesMock.mockReset();
  });

  it("reads the session token from the request cookies", async () => {
    const token = await readSessionToken({
      get: (name) => (name === "cs_session" ? { value: "tok-123" } : undefined),
    });
    expect(token).toBe("tok-123");
  });

  it("returns null when there is no session cookie", async () => {
    const token = await readSessionToken({ get: () => undefined });
    expect(token).toBeNull();
  });

  it("treats a blank cookie value as no session", async () => {
    const token = await readSessionToken({
      get: () => ({ value: "   " }),
    });
    expect(token).toBeNull();
  });

  it("falls back to the request scope when no store is given", async () => {
    cookiesMock.mockResolvedValue({
      get: (name: string) => (name === "cs_session" ? { value: "scoped" } : undefined),
    });
    await expect(readSessionToken()).resolves.toBe("scoped");
  });

  it("returns null outside a request scope", async () => {
    cookiesMock.mockRejectedValue(new Error("cookies() was called outside a request scope"));
    await expect(readSessionToken()).resolves.toBeNull();
  });
});

describe("sessionMaxAgeSeconds", () => {
  const now = Date.parse("2026-03-12T10:00:00Z");

  it("uses the backend expiry when it is an ISO timestamp", () => {
    expect(sessionMaxAgeSeconds("2026-03-12T12:00:00Z", now)).toBe(7200);
  });

  it("accepts a Unix epoch in seconds", () => {
    const expires = Math.floor((now + 3600 * 1000) / 1000);
    expect(sessionMaxAgeSeconds(expires, now)).toBe(3600);
  });

  it("accepts a Unix epoch in milliseconds", () => {
    expect(sessionMaxAgeSeconds(now + 1800 * 1000, now)).toBe(1800);
  });

  it("falls back to a default when no expiry is reported", () => {
    expect(sessionMaxAgeSeconds(null, now)).toBe(DEFAULT_SESSION_MAX_AGE_SECONDS);
    expect(sessionMaxAgeSeconds(undefined, now)).toBe(DEFAULT_SESSION_MAX_AGE_SECONDS);
    expect(sessionMaxAgeSeconds("", now)).toBe(DEFAULT_SESSION_MAX_AGE_SECONDS);
  });

  it("falls back to a default when the expiry is unparseable", () => {
    expect(sessionMaxAgeSeconds("not-a-date", now)).toBe(
      DEFAULT_SESSION_MAX_AGE_SECONDS,
    );
  });

  it("never writes a cookie that is already expired", () => {
    expect(sessionMaxAgeSeconds("2020-01-01T00:00:00Z", now)).toBe(1);
  });
});

describe("resolveRequestOrigin", () => {
  it("prefers the configured app URL", () => {
    const origin = resolveRequestOrigin(
      { get: () => "https://ignored.example" },
      "https://app.example/",
    );
    expect(origin).toBe("https://app.example");
  });

  it("derives the origin from the forwarded host and protocol", () => {
    const headers = new Headers({
      "x-forwarded-host": "app.example",
      "x-forwarded-proto": "https",
    });
    expect(resolveRequestOrigin(headers)).toBe("https://app.example");
  });

  it("uses http for a localhost host", () => {
    const headers = new Headers({ host: "localhost:3000" });
    expect(resolveRequestOrigin(headers)).toBe("http://localhost:3000");
  });

  it("returns an empty origin when no host is available", () => {
    expect(resolveRequestOrigin({ get: () => null })).toBe("");
  });
});

describe("googleStartUrl", () => {
  it("points at the backend start endpoint with an encoded redirect", () => {
    const url = new URL(googleStartUrl("https://app.example/api/auth/callback"));
    expect(url.pathname).toBe("/api/v1/auth/google/start");
    expect(url.searchParams.get("redirect_uri")).toBe(
      "https://app.example/api/auth/callback",
    );
  });
});

describe("exchangeTicket", () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    globalThis.fetch = vi.fn() as unknown as typeof fetch;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it("exchanges the ticket for a session token", async () => {
    (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      status: 200,
      text: async () =>
        JSON.stringify({
          session_token: "session-abc",
          expires_at: new Date(Date.now() + 3600_000).toISOString(),
          user: { id: "u1", email: "analyst@example.com", display_name: "Analyst" },
          workspace: { id: "w1", name: "Acme", slug: "acme" },
        }),
    });

    const result = await exchangeTicket("ticket-1");
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.sessionToken).toBe("session-abc");
    expect(result.session.user.email).toBe("analyst@example.com");
    expect(result.session.user.displayName).toBe("Analyst");
    expect(result.session.workspace?.slug).toBe("acme");
    expect(result.maxAgeSeconds).toBeGreaterThan(0);
    expect(result.maxAgeSeconds).toBeLessThanOrEqual(3600);

    const call = (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mock
      .calls[0];
    expect(call[0]).toContain("/api/v1/auth/exchange");
    expect(call[1].method).toBe("POST");
    expect(JSON.parse(call[1].body)).toEqual({ ticket: "ticket-1" });
  });

  it("fails when the backend rejects the ticket", async () => {
    (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: false,
      status: 400,
      text: async () => "",
    });

    await expect(exchangeTicket("ticket-bad")).resolves.toEqual({ ok: false });
  });

  it("fails when the backend returns no session token", async () => {
    (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      status: 200,
      text: async () => JSON.stringify({ user: { id: "u1", email: "a@b.c" } }),
    });

    await expect(exchangeTicket("ticket-2")).resolves.toEqual({ ok: false });
  });
});

describe("fetchCurrentUser", () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    globalThis.fetch = vi.fn() as unknown as typeof fetch;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it("returns the signed-in user for a valid token", async () => {
    (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      status: 200,
      text: async () =>
        JSON.stringify({
          expires_at: "2026-03-12T12:00:00Z",
          user: { id: "u1", email: "analyst@example.com", display_name: null },
          workspace: { id: "w1", name: "Acme", slug: "acme" },
        }),
    });

    const session = await fetchCurrentUser("tok");
    expect(session?.user.email).toBe("analyst@example.com");
    expect(session?.user.displayName).toBeNull();
    expect(session?.workspace?.name).toBe("Acme");

    const call = (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mock
      .calls[0];
    expect(call[0]).toContain("/api/v1/auth/me");
    expect(headerValue(call[1].headers, "Authorization")).toBe("Bearer tok");
  });

  it("returns null when there is no session", async () => {
    await expect(fetchCurrentUser(null)).resolves.toBeNull();
    expect(globalThis.fetch).not.toHaveBeenCalled();
  });

  it("returns null when the backend rejects the session", async () => {
    (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: false,
      status: 401,
      text: async () => "",
    });

    await expect(fetchCurrentUser("tok")).resolves.toBeNull();
  });
});

describe("signOut", () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    globalThis.fetch = vi.fn() as unknown as typeof fetch;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it("revokes the session on the backend", async () => {
    (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      status: 204,
      text: async () => "",
    });

    await expect(signOut("tok")).resolves.toBe(true);
    const call = (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mock
      .calls[0];
    expect(call[0]).toContain("/api/v1/auth/logout");
    expect(call[1].method).toBe("POST");
    expect(headerValue(call[1].headers, "Authorization")).toBe("Bearer tok");
  });

  it("is a no-op when there is no session", async () => {
    await expect(signOut(null)).resolves.toBe(true);
    expect(globalThis.fetch).not.toHaveBeenCalled();
  });
});
