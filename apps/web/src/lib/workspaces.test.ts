import { describe, expect, it } from "vitest";
import { __testing } from "./api";

const { normaliseWorkspaces } = __testing;

describe("the workspaces a reviewer may act in", () => {
  it("reads a bare list of workspaces", () => {
    const result = normaliseWorkspaces([
      { id: "w1", name: "Acme", slug: "acme", open_findings: 12 },
    ]);
    expect(result).toEqual([{ id: "w1", name: "Acme", slug: "acme", openFindings: 12 }]);
  });

  it("reads a list wrapped in an envelope", () => {
    const result = normaliseWorkspaces({ items: [{ id: "w2", slug: "beta" }] });
    expect(result).toHaveLength(1);
    expect(result[0].id).toBe("w2");
    expect(result[0].name).toBe("w2");
    expect(result[0].openFindings).toBe(0);
  });

  it("drops a workspace that cannot be acted in", () => {
    const result = normaliseWorkspaces([{ name: "no id" }, null, "nonsense"]);
    expect(result).toEqual([]);
  });

  it("survives an answer that is not a list", () => {
    expect(normaliseWorkspaces(null)).toEqual([]);
    expect(normaliseWorkspaces("nope")).toEqual([]);
  });
});
