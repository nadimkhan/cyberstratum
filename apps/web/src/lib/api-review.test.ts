import { afterEach, describe, expect, it, vi } from "vitest";
import { reviewFinding } from "./api";

/**
 * A review verdict is the label the machine learning pipeline learns from,
 * so these tests pin two things: that the request carries the verdict and
 * the reason, and that a false positive without a reason never leaves the
 * browser at all.
 */

afterEach(() => {
  vi.unstubAllGlobals();
});

function stubFetch(status: number, body: unknown) {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
    text: async () => JSON.stringify(body),
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("reviewFinding", () => {
  it("posts the verdict to the review route", async () => {
    const fetchMock = stubFetch(200, { status: "confirmed", review_note: "yes" });

    const result = await reviewFinding("finding-1", {
      status: "confirmed",
      note: "the reentrancy is reachable",
    });

    expect(result.ok).toBe(true);
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/findings/finding-1/review");
    expect(init.method).toBe("POST");
    const body = JSON.parse(String(init.body));
    expect(body.status).toBe("confirmed");
    expect(body.note).toBe("the reentrancy is reachable");
  });

  it("refuses a false positive without a reason before making a request", async () => {
    const fetchMock = stubFetch(200, {});

    const result = await reviewFinding("finding-1", { status: "false_positive" });

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.message).toMatch(/reason/i);
    }
    // The request was never made: a false positive with no reason cannot
    // be told apart from a mistaken verdict, and neither is usable.
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("sends a null note when the reviewer wrote nothing", async () => {
    const fetchMock = stubFetch(200, { status: "triage" });

    await reviewFinding("finding-1", { status: "triage", note: "   " });

    const body = JSON.parse(String(fetchMock.mock.calls[0][1].body));
    expect(body.note).toBeNull();
  });

  it("reports the backend's refusal", async () => {
    stubFetch(422, { error: { message: "that is not a verdict" } });

    const result = await reviewFinding("finding-1", { status: "confirmed" });

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.kind).not.toBe("network");
    }
  });
});
