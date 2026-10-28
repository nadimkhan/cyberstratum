import { describe, expect, it } from "vitest";
import { describeApiError } from "./api";

describe("describeApiError", () => {
  it("reports an unreachable backend", () => {
    const described = describeApiError({ kind: "network", message: "boom" });
    expect(described.title).toBe("Backend unreachable");
  });

  it("reports a rejected API key separately from an outage", () => {
    const described = describeApiError({ kind: "http", message: "nope", status: 401 });
    expect(described.title).toBe("API key rejected");
    expect(described.message).toContain("API_KEY");
  });

  it("reports a missing route", () => {
    const described = describeApiError({
      kind: "not_found",
      message: "The backend has no route for /scans.",
    });
    expect(described.title).toBe("Not found");
  });

  it("falls back to a generic backend error", () => {
    const described = describeApiError({ kind: "http", message: "HTTP 500", status: 500 });
    expect(described.title).toBe("Backend error");
  });
});
