import { describe, expect, it } from "vitest";
import { __testing } from "./api";

const { normaliseWeakness } = __testing;

describe("normaliseWeakness", () => {
  it("reads the class of a finding", () => {
    const weakness = normaliseWeakness({
      swc_id: "SWC-115",
      title: "Authorization through tx.origin",
      severity: null,
      cwe_ids: ["CWE-477"],
      basis: "The detector reports a contract that reads the original sender.",
      source: "cyberstratum-correspondence",
    });

    expect(weakness).not.toBeNull();
    expect(weakness?.swcId).toBe("SWC-115");
    expect(weakness?.title).toBe("Authorization through tx.origin");
    expect(weakness?.cweIds).toEqual(["CWE-477"]);
    expect(weakness?.basis).toContain("original sender");
    expect(weakness?.source).toBe("cyberstratum-correspondence");
  });

  it("leaves out a class it cannot describe", () => {
    expect(normaliseWeakness(null)).toBeNull();
    expect(normaliseWeakness(undefined)).toBeNull();
    expect(normaliseWeakness({})).toBeNull();
    expect(normaliseWeakness({ title: "No identifier" })).toBeNull();
  });
});
