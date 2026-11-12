import { describe, expect, it } from "vitest";
import { __testing } from "./api";

const { normaliseGuidance } = __testing;

describe("the guidance a finding carries", () => {
  it("normalises an API guidance entry", () => {
    const guidance = normaliseGuidance({
      detector_id: "slither.assembly",
      title: "Inline assembly bypasses the compiler's checks",
      what_it_means: "The contract contains an assembly block.",
      why_it_matters: "The compiler does not check it.",
      how_to_fix: "Keep it small.",
      false_positive_patterns: "Expected in a proxy fallback.",
      references: "Solidity documentation: Inline Assembly",
      default_severity: "medium",
      version: "1",
    });

    expect(guidance).not.toBeNull();
    expect(guidance?.detectorId).toBe("slither.assembly");
    expect(guidance?.title).toBe("Inline assembly bypasses the compiler's checks");
    expect(guidance?.whatItMeans).toBe("The contract contains an assembly block.");
    expect(guidance?.whyItMatters).toBe("The compiler does not check it.");
    expect(guidance?.howToFix).toBe("Keep it small.");
    expect(guidance?.falsePositivePatterns).toBe("Expected in a proxy fallback.");
    expect(guidance?.references).toBe("Solidity documentation: Inline Assembly");
    expect(guidance?.defaultSeverity).toBe("medium");
  });

  it("refuses an entry that names no detector", () => {
    expect(normaliseGuidance({ title: "no detector" })).toBeNull();
    expect(normaliseGuidance(null)).toBeNull();
    expect(normaliseGuidance("nonsense")).toBeNull();
  });

  it("falls back to a severity the product knows", () => {
    const guidance = normaliseGuidance({
      detector_id: "example.detector",
      default_severity: "catastrophic",
    });

    expect(guidance?.defaultSeverity).toBe("medium");
  });

  it("keeps every half of the advice", () => {
    const guidance = normaliseGuidance({ detector_id: "example.detector" });

    expect(guidance?.title).toBe("");
    expect(guidance?.whatItMeans).toBe("");
    expect(guidance?.falsePositivePatterns).toBe("");
    expect(guidance?.version).toBe("1");
  });
});
