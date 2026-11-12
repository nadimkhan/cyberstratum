import { describe, expect, it } from "vitest";
import { __testing } from "./api";

const { toScopeStatus, normaliseScanSummary } = __testing;

describe("toScopeStatus", () => {
  it("reads the three honest answers", () => {
    expect(toScopeStatus("in_scope")).toBe("in_scope");
    expect(toScopeStatus("out_of_scope")).toBe("out_of_scope");
    expect(toScopeStatus("unknown")).toBe("unknown");
  });

  it("reads a scope it cannot understand as unknown, never as permission", () => {
    expect(toScopeStatus(undefined)).toBe("unknown");
    expect(toScopeStatus(null)).toBe("unknown");
    expect(toScopeStatus("")).toBe("unknown");
    expect(toScopeStatus("in scope")).toBe("unknown");
    expect(toScopeStatus("yes")).toBe("unknown");
    expect(toScopeStatus(42)).toBe("unknown");
  });
});

describe("normaliseScanSummary", () => {
  it("carries the authorisation the scan was made under", () => {
    const summary = normaliseScanSummary({
      id: "scan-1",
      status: "completed",
      scope_status: "out_of_scope",
    });

    expect(summary.scopeStatus).toBe("out_of_scope");
  });

  it("defaults to unknown when the scan does not say", () => {
    const summary = normaliseScanSummary({
      id: "scan-2",
      status: "completed",
    });

    expect(summary.scopeStatus).toBe("unknown");
  });
});
