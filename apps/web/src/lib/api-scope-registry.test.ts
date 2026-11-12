import { describe, expect, it } from "vitest";
import { __testing } from "./api";

const { normaliseScopeGrants, normaliseScopeStatus } = __testing;

describe("normaliseScopeGrants", () => {
  it("reads a declared grant", () => {
    const grants = normaliseScopeGrants([
      {
        id: "grant-1",
        kind: "contract",
        value: "0x1111111111111111111111111111111111111111",
        chain_id: null,
        safe_harbour: true,
        reference: "https://example.invalid/scope",
        expires_at: null,
        created_at: "2026-11-13T00:00:00Z",
      },
    ]);

    expect(grants).toHaveLength(1);
    expect(grants[0].kind).toBe("contract");
    expect(grants[0].safeHarbour).toBe(true);
    expect(grants[0].reference).toBe("https://example.invalid/scope");
  });

  it("drops a grant of a kind the registry does not know", () => {
    const grants = normaliseScopeGrants([
      { id: "grant-1", kind: "everything", value: "x" },
    ]);

    expect(grants).toHaveLength(0);
  });

  it("drops a grant with no id, because it cannot be acted on", () => {
    const grants = normaliseScopeGrants([{ kind: "contract", value: "0x1" }]);

    expect(grants).toHaveLength(0);
  });
});

describe("normaliseScopeStatus", () => {
  it("keeps the three answers apart", () => {
    expect(normaliseScopeStatus({ status: "in_scope" }).status).toBe("in_scope");
    expect(normaliseScopeStatus({ status: "out_of_scope" }).status).toBe(
      "out_of_scope",
    );
    expect(normaliseScopeStatus({ status: "unknown" }).status).toBe("unknown");
  });

  it("reads an answer it cannot understand as unknown, never as permission", () => {
    expect(normaliseScopeStatus({ status: "granted" }).status).toBe("unknown");
    expect(normaliseScopeStatus({}).status).toBe("unknown");
    expect(normaliseScopeStatus(null).status).toBe("unknown");
  });

  it("carries the reason and the statement", () => {
    const status = normaliseScopeStatus({
      status: "in_scope",
      reason: "Covered by a contract grant.",
      statement: "The target was covered by an authorised scope grant.",
    });

    expect(status.reason).toBe("Covered by a contract grant.");
    expect(status.statement).toBe(
      "The target was covered by an authorised scope grant.",
    );
  });
});
