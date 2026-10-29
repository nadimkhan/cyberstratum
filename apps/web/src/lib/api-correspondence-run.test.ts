import { afterEach, describe, expect, it, vi } from "vitest";
import { triggerCorrespondence } from "./api";

/**
 * The manual correspondence action has one job: report that the work was
 * queued, and claim nothing else. These tests pin that behaviour, because
 * the failure mode here is a report that quietly implies a source line may
 * already be cited.
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

describe("triggerCorrespondence", () => {
  it("posts to the correspondence route", async () => {
    const fetchMock = stubFetch(202, {
      scan_id: "scan-1",
      job_id: "job-1",
      status: "queued",
      queue_name: "cyberstratum:correspondence",
      message: "Correspondence proof queued.",
    });

    const result = await triggerCorrespondence("scan-1");

    expect(result.ok).toBe(true);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/scans/scan-1/correspondence");
    expect(init.method).toBe("POST");
  });

  it("reports the queued state and never a verdict", async () => {
    stubFetch(202, {
      scan_id: "scan-1",
      job_id: "job-1",
      status: "queued",
      queue_name: "cyberstratum:correspondence",
      message: "Correspondence proof queued.",
    });

    const result = await triggerCorrespondence("scan-1");

    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.data.status).toBe("queued");
    expect(result.data.scanId).toBe("scan-1");
    expect(result.data.queue).toBe("cyberstratum:correspondence");
  });

  it("surfaces a queue outage as an error rather than a queued proof", async () => {
    stubFetch(503, { detail: "The job queue is unavailable." });

    const result = await triggerCorrespondence("scan-1");

    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.error.kind).toBe("http");
    expect(result.error.status).toBe(503);
  });
});
