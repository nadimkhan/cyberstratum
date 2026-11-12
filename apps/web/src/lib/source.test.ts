import { describe, expect, it } from "vitest";
import { __testing } from "./api";

const { normaliseFinding, normaliseScanSource } = __testing;

describe("the source of a scan", () => {
  it("normalises the files that were analysed", () => {
    const source = normaliseScanSource({
      available: true,
      language: "solidity",
      compiler_version: "0.8.26",
      verified: true,
      source_uri: "https://example.test/contract",
      files: [{ path: "Stored.sol", content: "contract Stored {}" }],
    });

    expect(source.available).toBe(true);
    expect(source.language).toBe("solidity");
    expect(source.compilerVersion).toBe("0.8.26");
    expect(source.verified).toBe(true);
    expect(source.sourceUri).toBe("https://example.test/contract");
    expect(source.files).toHaveLength(1);
    expect(source.files[0].path).toBe("Stored.sol");
    expect(source.files[0].content).toBe("contract Stored {}");
  });

  it("keeps the reason a scan has no source", () => {
    const source = normaliseScanSource({
      available: false,
      reason: "This scan was analysed from runtime bytecode alone.",
      files: [],
    });

    expect(source.available).toBe(false);
    expect(source.reason).toBe("This scan was analysed from runtime bytecode alone.");
    expect(source.files).toEqual([]);
  });

  it("drops a file that carries no content", () => {
    const source = normaliseScanSource({
      available: true,
      files: [{ path: "Empty.sol", content: "" }, { path: "Real.sol", content: "x" }],
    });

    expect(source.files).toHaveLength(1);
    expect(source.files[0].path).toBe("Real.sol");
  });

  it("survives a malformed response", () => {
    const source = normaliseScanSource(null);

    expect(source.available).toBe(false);
    expect(source.files).toEqual([]);
  });
});

describe("the line a finding points at", () => {
  it("carries the line and the file it belongs to", () => {
    const finding = normaliseFinding({
      id: "f1",
      detector_id: "baseline.tx_origin",
      evidence: { source_line: 17, source_file: "Stored.sol" },
    });

    expect(finding.sourceLine).toBe(17);
    expect(finding.sourceFile).toBe("Stored.sol");
  });

  it("keeps no line when the source could not be placed", () => {
    const finding = normaliseFinding({
      id: "f2",
      detector_id: "baseline.delegatecall",
      evidence: { offsets: [12] },
    });

    expect(finding.sourceLine).toBeNull();
    expect(finding.sourceFile).toBeNull();
  });
});
