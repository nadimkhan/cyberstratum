import { describe, expect, it } from "vitest";
import { __testing } from "./api";

const { normaliseFindingsSummary,
  normaliseLearningStatus } = __testing;

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


describe("normaliseLearningStatus", () => {
  it("reads the reviewed corpus, the model and the last cycle", () => {
    const status = normaliseLearningStatus({
      reviewed: {
        total: 2,
        confirmed: 1,
        false_positive: 1,
        contracts: 1,
        categories: 2,
      },
      model: {
        manifest_id: "manifest-1",
        path: "/var/models/m",
        payload: { trained_at: "2026-11-13", precision: 0.91 },
      },
      last_cycle: {
        records: 1,
        promotable: false,
        gate_reason: "there is no validation split",
        installed: false,
        manifest_id: null,
        dataset_path: "/repo/.learning/reviewed-labels.jsonl",
      },
    });

    expect(status.reviewed.total).toBe(2);
    expect(status.reviewed.falsePositive).toBe(1);
    expect(status.reviewed.contracts).toBe(1);
    expect(status.model?.manifestId).toBe("manifest-1");
    expect(status.model?.payload.precision).toBe(0.91);
    expect(status.lastCycle?.promotable).toBe(false);
    expect(status.lastCycle?.gateReason).toBe("there is no validation split");
  });

  it("treats an absent model and an absent cycle as absent, not as broken", () => {
    const status = normaliseLearningStatus({});
    expect(status.reviewed.total).toBe(0);
    expect(status.reviewed.confirmed).toBe(0);
    expect(status.model).toBeNull();
    expect(status.lastCycle).toBeNull();
  });

  it("reads a cycle written in camel case as well", () => {
    const status = normaliseLearningStatus({
      reviewed: { falsePositive: 3 },
      lastCycle: {
        records: 4,
        promotable: true,
        gateReason: "",
        installed: true,
      },
    });
    expect(status.reviewed.falsePositive).toBe(3);
    expect(status.lastCycle?.promotable).toBe(true);
    expect(status.lastCycle?.installed).toBe(true);
  });
});
