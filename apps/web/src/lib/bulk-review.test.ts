import { describe, expect, it } from "vitest";
import { bulkVerdictProblem } from "./bulk-review";

describe("a verdict applied to many findings", () => {
  it("accepts a confirmed verdict without a reason", () => {
    expect(bulkVerdictProblem("confirmed", "")).toBeNull();
    expect(bulkVerdictProblem("confirmed", "checked by hand")).toBeNull();
  });

  it("refuses a false positive without a reason", () => {
    expect(bulkVerdictProblem("false_positive", "")).not.toBeNull();
    expect(bulkVerdictProblem("false_positive", "   ")).not.toBeNull();
  });

  it("accepts a false positive that says why", () => {
    expect(bulkVerdictProblem("false_positive", "a style question, not a defect")).toBeNull();
  });

  it("accepts the verdicts that need no reason", () => {
    expect(bulkVerdictProblem("needs_more_evidence", "")).toBeNull();
    expect(bulkVerdictProblem("triage", "")).toBeNull();
  });
});
