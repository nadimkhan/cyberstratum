import { describe, expect, it } from "vitest";
import {
  countSeverities,
  emptySeverityCounts,
  estimateRiskScore,
  SEVERITY_LABELS,
  SEVERITY_META,
  toSeverity,
} from "./severity";
import { SEVERITY_ORDER } from "./types";

describe("toSeverity", () => {
  it("maps canonical values", () => {
    for (const severity of SEVERITY_ORDER) {
      expect(toSeverity(severity)).toBe(severity);
    }
  });

  it("normalises case and separators", () => {
    expect(toSeverity("Critical")).toBe("critical");
    expect(toSeverity("HIGH")).toBe("high");
    expect(toSeverity("medium-severity")).toBe("medium");
    expect(toSeverity("informational")).toBe("info");
  });

  it("falls back to info for unknown or invalid values", () => {
    expect(toSeverity("banana")).toBe("info");
    expect(toSeverity(undefined)).toBe("info");
    expect(toSeverity(42)).toBe("info");
  });
});

describe("SEVERITY_META", () => {
  it("defines a label and badge for every severity", () => {
    for (const severity of SEVERITY_ORDER) {
      const meta = SEVERITY_META[severity];
      expect(meta.label).toBeTruthy();
      expect(meta.badge).toBeTruthy();
      expect(meta.weight).toBeGreaterThan(0);
    }
  });

  it("orders severity weights from most to least severe", () => {
    const weights = SEVERITY_ORDER.map((severity) => SEVERITY_META[severity].weight);
    for (let index = 1; index < weights.length; index += 1) {
      expect(weights[index]).toBeLessThan(weights[index - 1]);
    }
  });

  it("exposes a filter label per severity", () => {
    expect(SEVERITY_LABELS.map((entry) => entry.value)).toEqual([...SEVERITY_ORDER]);
  });
});

describe("countSeverities", () => {
  it("counts a mixed list into a histogram", () => {
    const counts = countSeverities(["critical", "critical", "high", "info"]);
    expect(counts).toEqual({
      critical: 2,
      high: 1,
      medium: 0,
      low: 0,
      info: 1,
    });
  });

  it("returns an empty histogram for an empty list", () => {
    expect(countSeverities([])).toEqual(emptySeverityCounts());
  });
});

describe("estimateRiskScore", () => {
  it("is zero when there are no findings", () => {
    expect(estimateRiskScore(emptySeverityCounts())).toBe(0);
  });

  it("rises with severity and count, and stays within 0-100", () => {
    const low = estimateRiskScore({ ...emptySeverityCounts(), low: 5 });
    const critical = estimateRiskScore({ ...emptySeverityCounts(), critical: 5 });
    expect(critical).toBeGreaterThan(low);
    expect(estimateRiskScore({ ...emptySeverityCounts(), critical: 1000 })).toBeLessThanOrEqual(100);
    expect(estimateRiskScore({ ...emptySeverityCounts(), critical: 1000 })).toBeGreaterThanOrEqual(0);
  });
});
