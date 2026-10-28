import { describe, expect, it } from "vitest";
import { __testing } from "./api";

const { normaliseFinding, normaliseScanSummary, normaliseScanDetail } = __testing;

describe("normaliseScanSummary", () => {
  it("maps snake_case backend payloads", () => {
    const scan = normaliseScanSummary({
      id: "scan-1",
      contract_address: "0x1234567890abcdef1234567890abcdef12345678",
      chain_id: 1,
      status: "completed",
      created_at: "2026-03-12T10:30:00Z",
      finding_counts: { critical: 1, high: 2 },
      total_findings: 3,
    });

    expect(scan.id).toBe("scan-1");
    expect(scan.contractAddress).toBe("0x1234567890abcdef1234567890abcdef12345678");
    expect(scan.chainId).toBe(1);
    expect(scan.status).toBe("completed");
    expect(scan.findingCounts.critical).toBe(1);
    expect(scan.findingCounts.high).toBe(2);
    expect(scan.totalFindings).toBe(3);
    expect(scan.createdAt).toBe("2026-03-12T10:30:00.000Z");
  });

  it("maps camelCase backend payloads", () => {
    const scan = normaliseScanSummary({
      id: "scan-2",
      contractAddress: "0xabc",
      chainId: 137,
      status: "running",
      findingCounts: { high: 4 },
    });

    expect(scan.contractAddress).toBe("0xabc");
    expect(scan.chainId).toBe(137);
    expect(scan.status).toBe("running");
    expect(scan.findingCounts.high).toBe(4);
  });

  it("defaults safely when fields are missing", () => {
    const scan = normaliseScanSummary({});
    expect(scan.id).toBe("unknown");
    expect(scan.status).toBe("queued");
    expect(scan.totalFindings).toBe(0);
    expect(scan.findingCounts).toEqual({
      critical: 0,
      high: 0,
      medium: 0,
      low: 0,
      info: 0,
    });
  });
});

describe("normaliseFinding", () => {
  it("maps a documented finding payload", () => {
    const finding = normaliseFinding({
      id: "f-1",
      scan_id: "scan-1",
      category: "reentrancy_candidate",
      severity: "high",
      confidence: 0.72,
      status: "needs_review",
      detector_id: "REENT-001",
      function_signature: "withdraw(uint256)",
      evidence: {
        byteOffsets: [412, 468],
        basicBlockIds: ["block-12"],
        signals: ["external_call_before_state_write"],
      },
      limitations: "Static pattern only.",
    });

    expect(finding.id).toBe("f-1");
    expect(finding.scanId).toBe("scan-1");
    expect(finding.severity).toBe("high");
    expect(finding.confidence).toBeCloseTo(0.72);
    expect(finding.reviewStatus).toBe("new");
    expect(finding.detectorId).toBe("REENT-001");
    expect(finding.functionSignature).toBe("withdraw(uint256)");
    expect(finding.byteOffsets).toEqual([412, 468]);
    expect(finding.evidence).toEqual(["external_call_before_state_write"]);
    expect(finding.limitations).toBe("Static pattern only.");
  });

  it("normalises a percentage confidence into a 0-1 value", () => {
    expect(normaliseFinding({ id: "f", confidence: 85 }).confidence).toBeCloseTo(0.85);
  });
});

describe("normaliseScanDetail", () => {
  it("extracts stages, artifacts and reproducibility metadata", () => {
    const detail = normaliseScanDetail({
      id: "scan-3",
      status: "completed",
      stages: [
        { key: "validate", label: "Input validation", status: "completed", duration_ms: 12 },
        { key: "disasm", label: "Disassembly", status: "failed", message: "truncated input" },
      ],
      artifacts: [
        { id: "a1", name: "report.json", kind: "report", size_bytes: 2048, sha256: "abc" },
      ],
      reproducibility: {
        tool_versions: [{ name: "evm-analysis", version: "0.1.0" }],
        opcode_table_version: "2026-03-01",
        bytecode_hash: "0xdeadbeef",
        ruleset_version: "rules-3",
      },
      warnings: ["unresolved jump at 0x120"],
    });

    expect(detail.stages).toHaveLength(2);
    expect(detail.stages[0].status).toBe("completed");
    expect(detail.stages[1].status).toBe("failed");
    expect(detail.stages[1].message).toBe("truncated input");
    expect(detail.artifacts[0].sizeBytes).toBe(2048);
    expect(detail.reproducibility.opcodeTableVersion).toBe("2026-03-01");
    expect(detail.reproducibility.bytecodeHash).toBe("0xdeadbeef");
    expect(detail.reproducibility.rulesetVersion).toBe("rules-3");
    expect(detail.reproducibility.toolVersions).toEqual([
      { name: "evm-analysis", version: "0.1.0" },
    ]);
    expect(detail.warnings).toEqual(["unresolved jump at 0x120"]);
  });
});
