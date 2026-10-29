import { describe, expect, it } from "vitest";
import { __testing } from "./api";

const { normaliseCorrespondence, normaliseScanDetail, normaliseScanSummary } =
  __testing;

describe("Mythril run status", () => {
  it("defaults to not-run rather than clean", () => {
    const scan = normaliseScanSummary({ id: "scan-1" });

    expect(scan.mythrilRan).toBe(false);
    expect(scan.mythrilSkipped).toBeNull();
  });

  it("maps a recorded Mythril run and its skip reason", () => {
    const scan = normaliseScanSummary({
      id: "scan-2",
      mythril_ran: true,
      mythril_skipped: null,
    });
    expect(scan.mythrilRan).toBe(true);

    const skipped = normaliseScanSummary({
      id: "scan-3",
      mythril_ran: false,
      mythril_skipped: "mythril_not_installed",
    });
    expect(skipped.mythrilRan).toBe(false);
    expect(skipped.mythrilSkipped).toBe("mythril_not_installed");
  });
});

describe("normaliseCorrespondence", () => {
  it("returns null when the backend reported no proof", () => {
    expect(normaliseCorrespondence({}, "scan-1")).toBeNull();
  });

  it("maps a snake_case established proof", () => {
    const proof = normaliseCorrespondence(
      {
        scan_id: "scan-1",
        status: "established",
        compiler_version: "0.4.24+commit.e67f0147",
        source_path: "FiatTokenProxy.sol",
        runtime_sha256: "a".repeat(64),
        executable_sha256: "b".repeat(64),
        metadata_sha256: "c".repeat(64),
        runtime_byte_size: 2186,
        executable_byte_size: 2143,
        instruction_count: 807,
        mapped_instruction_count: 807,
      },
      "scan-1",
    );

    expect(proof?.status).toBe("established");
    expect(proof?.compilerVersion).toBe("0.4.24+commit.e67f0147");
    expect(proof?.sourcePath).toBe("FiatTokenProxy.sol");
    expect(proof?.executableByteSize).toBe(2143);
    expect(proof?.mappedInstructionCount).toBe(807);
  });

  it("keeps a mismatch distinct from an unavailable check", () => {
    const mismatch = normaliseCorrespondence(
      { status: "mismatch" },
      "scan-1",
    );
    expect(mismatch?.status).toBe("mismatch");

    const unavailable = normaliseCorrespondence(
      { status: "unavailable", skipped: "compiler_timeout" },
      "scan-1",
    );
    expect(unavailable?.status).toBe("unavailable");
    expect(unavailable?.skipped).toBe("compiler_timeout");
  });

  it("falls back to skipped, never mismatch, for an unrecognised status", () => {
    const proof = normaliseCorrespondence({ status: "weird" }, "scan-1");
    expect(proof?.status).toBe("skipped");
  });
});

describe("normaliseScanDetail", () => {
  it("exposes the stored correspondence proof", () => {
    const detail = normaliseScanDetail({
      id: "scan-1",
      correspondence: {
        status: "established",
        source_path: "Token.sol",
      },
    });

    expect(detail.correspondence?.status).toBe("established");
    expect(detail.correspondence?.sourcePath).toBe("Token.sol");
  });

  it("reports no proof as null", () => {
    const detail = normaliseScanDetail({ id: "scan-2" });
    expect(detail.correspondence).toBeNull();
  });
});
