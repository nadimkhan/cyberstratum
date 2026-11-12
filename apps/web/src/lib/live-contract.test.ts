import { describe, expect, it } from "vitest";
import { __testing } from "./api";

const { normaliseScanSummary, normaliseScanDetail, normaliseFinding } = __testing;

describe("live backend contract", () => {
  it("normalises a FastAPI ScanSummary payload", () => {
    const scan = normaliseScanSummary({
      id: "0f0f0f0f-0000-0000-0000-000000000001",
      workspace_id: "0f0f0f0f-0000-0000-0000-0000000000ff",
      target_id: "0f0f0f0f-0000-0000-0000-0000000000aa",
      contract_address: "0x1234567890abcdef1234567890abcdef12345678",
      chain_id: 1,
      labels: ["defi"],
      finding_counts: { critical: 1, high: 2 },
      total_findings: 3,
      status: "running_detectors",
      fork: "cancun",
      bytecode_source: "rpc",
      queued_at: "2026-03-12T10:30:00Z",
      started_at: "2026-03-12T10:30:01Z",
      completed_at: null,
      parser_version: "0.1.0",
      ruleset_version: "0.1.0",
      model_version: null,
      error_code: null,
      error_message_redacted: null,
      created_at: "2026-03-12T10:30:00Z",
    });

    expect(scan.status).toBe("running");
    expect(scan.findingCounts.high).toBe(2);
    expect(scan.totalFindings).toBe(3);
    expect(scan.fork).toBe("cancun");
    expect(scan.labels).toEqual(["defi"]);
    expect(scan.rulesetVersion).toBe("0.1.0");
  });

  it("derives pipeline stages from a terminal scan status", () => {
    const detail = normaliseScanDetail({
      id: "scan-2",
      status: "completed",
      fork: "cancun",
      parser_version: "0.1.0",
      ruleset_version: "0.1.0",
      artifacts: [
        {
          id: "a1",
          kind: "bytecode",
          content_type: "application/octet-stream",
          object_key: "scans/scan-2/bytecode.bin",
          byte_size: 2048,
          sha256: "a".repeat(64),
          created_at: "2026-03-12T10:31:00Z",
        },
      ],
      findings: [],
      jobs: [],
    });

    expect(detail.stages.length).toBe(5);
    expect(detail.stages.every((stage) => stage.status === "completed")).toBe(true);
    expect(detail.artifacts[0].name).toBe("bytecode.bin");
    expect(detail.artifacts[0].sizeBytes).toBe(2048);
    expect(detail.reproducibility.bytecodeHash).toBe("a".repeat(64));
    expect(detail.reproducibility.opcodeTableVersion).toBe("cancun");
    expect(detail.reproducibility.toolVersions).toEqual([
      { name: "parser", version: "0.1.0" },
      { name: "ruleset", version: "0.1.0" },
    ]);
  });

  it("marks the failing stage when a scan failed", () => {
    const detail = normaliseScanDetail({
      id: "scan-3",
      status: "failed",
      error_code: "BYTECODE_FETCH_FAILED",
      error_message_redacted: "RPC endpoint unavailable",
      artifacts: [],
    });

    const failed = detail.stages.filter((stage) => stage.status === "failed");
    expect(failed).toHaveLength(1);
    expect(failed[0].key).toBe("intake");
    expect(failed[0].message).toBe("RPC endpoint unavailable");
  });

  it("reads detector evidence offsets and edge counts", () => {
    const finding = normaliseFinding({
      id: "f-1",
      scan_id: "scan-1",
      detector_id: "baseline.call_before_state_write",
      detector_version: "0.1.0",
      category: "reentrancy_candidate",
      title: "Potential reentrancy pattern",
      description: "Heuristic signal.",
      severity: "medium",
      confidence: 0.55,
      status: "new",
      evidence: {
        callOffset: 120,
        storageWriteOffset: 96,
        signals: ["external_call_before_state_write"],
      },
      limitations: "Static pattern only.",
      created_at: "2026-03-12T10:31:00Z",
    });

    expect(finding.severity).toBe("medium");
    expect(finding.byteOffsets).toEqual([96, 120]);
    expect(finding.evidence).toEqual(["external_call_before_state_write"]);
    expect(finding.reviewStatus).toBe("new");
    expect(finding.experimental).toBe(false);
  });

  it("derives graph coverage from the analysis-limitation finding", () => {
    const detail = normaliseScanDetail({
      id: "scan-4",
      status: "partial",
      artifacts: [],
      findings: [
        {
          id: "f-limitation",
          category: "analysis_limitation",
          severity: "info",
          confidence: 0.2,
          status: "new",
          evidence: { unresolvedEdgeCount: 3, edgeCount: 40 },
        },
      ],
    });

    expect(detail.coverage?.unresolvedJumps).toBe(3);
    expect(detail.coverage?.resolvedJumps).toBeNull();
  });
  it("reads the stored coverage measurement", () => {
    const detail = normaliseScanDetail({
      id: "scan-5",
      status: "completed",
      artifacts: [],
      findings: [],
      coverage: {
        instructions: 118,
        executable_bytes: 449,
        metadata_bytes: 53,
        edges: 46,
        dynamic_jumps: 6,
        unreachable_blocks: 1,
        notes: ["solidity metadata detected at offset 449"],
      },
    });

    expect(detail.coverage?.instructions).toBe(118);
    expect(detail.coverage?.executableBytes).toBe(449);
    expect(detail.coverage?.metadataBytes).toBe(53);
    expect(detail.coverage?.edges).toBe(46);
    expect(detail.coverage?.unresolvedJumps).toBe(6);
    expect(detail.coverage?.resolvedJumps).toBe(40);
    expect(detail.coverage?.notes).toEqual([
      "solidity metadata detected at offset 449",
    ]);
  });
});
