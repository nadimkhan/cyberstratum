import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { listScans } from "./api";

const cookiesMock = vi.hoisted(() => vi.fn());

vi.mock("next/headers", () => ({
  cookies: cookiesMock,
}));

const originalFetch = globalThis.fetch;

function lastCall(): [string, RequestInit] {
  const mock = globalThis.fetch as unknown as ReturnType<typeof vi.fn>;
  return mock.mock.calls[mock.mock.calls.length - 1] as [string, RequestInit];
}

describe("session scoping of backend calls", () => {
  beforeEach(() => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      text: async () => JSON.stringify({ items: [], total: 0 }),
      json: async () => ({ items: [], total: 0 }),
    }) as unknown as typeof fetch;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    cookiesMock.mockReset();
  });

  it("sends only the service key when there is no session", async () => {
    cookiesMock.mockResolvedValue({ get: () => undefined });

    await listScans();

    const headers = new Headers(lastCall()[1].headers);
    expect(headers.get("Authorization")).toBeNull();
  });

  it("sends the bearer token alongside the service key when a session exists", async () => {
    cookiesMock.mockResolvedValue({
      get: (name: string) => (name === "cs_session" ? { value: "tok-1" } : undefined),
    });

    await listScans();

    const headers = new Headers(lastCall()[1].headers);
    expect(headers.get("Authorization")).toBe("Bearer tok-1");
  });

  it("treats a blank session cookie as no session", async () => {
    cookiesMock.mockResolvedValue({ get: () => ({ value: "" }) });

    await listScans();

    expect(new Headers(lastCall()[1].headers).get("Authorization")).toBeNull();
  });

  it("still works outside a request scope", async () => {
    cookiesMock.mockRejectedValue(new Error("cookies() outside a request scope"));

    const result = await listScans();
    expect(result.ok).toBe(true);
    expect(new Headers(lastCall()[1].headers).get("Authorization")).toBeNull();
  });
});
