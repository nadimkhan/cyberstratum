import { describe, expect, it } from "vitest";
import { __testing } from "./api";

const { normaliseFindingsSummary } = __testing;

describe("normaliseFindingsSummary", () => {
  it("names the detectors that raised the findings", () => {
    const summary = normaliseFindingsSummary({
      total: 3,
      by_detector: [
        { detector_id: "baseline.delegatecall", count: 2 },
        { detector_id: "baseline.tx_origin", count: 1 },
      ],
    });

    expect(summary.byDetector).toHaveLength(2);
    expect(summary.byDetector[0].detectorId).toBe("baseline.delegatecall");
    expect(summary.byDetector[0].count).toBe(2);
  });

  it("names the chains the findings came from", () => {
    const summary = normaliseFindingsSummary({
      total: 2,
      by_chain: [{ chain_id: 1, chain_name: "Ethereum", count: 2 }],
    });

    expect(summary.byChain).toHaveLength(1);
    expect(summary.byChain[0].chainId).toBe(1);
    expect(summary.byChain[0].chainName).toBe("Ethereum");
  });

  it("reads the camelCase shape as well", () => {
    const summary = normaliseFindingsSummary({
      byDetector: [{ detectorId: "baseline.reentrancy", count: 4 }],
      byChain: [{ chainId: 10, chainName: "OP Mainnet", count: 4 }],
    });

    expect(summary.byDetector[0].detectorId).toBe("baseline.reentrancy");
    expect(summary.byChain[0].chainName).toBe("OP Mainnet");
  });

  it("survives a summary that says nothing", () => {
    const summary = normaliseFindingsSummary({});

    expect(summary.byDetector).toEqual([]);
    expect(summary.byChain).toEqual([]);
    expect(summary.total).toBe(0);
  });
});
