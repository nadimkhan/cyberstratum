import { describe, expect, it } from "vitest";
import {
  parseLabelList,
  validateScanForm,
  validateScanPayload,
  type ScanFormValues,
} from "./scan-request";

const ADDRESS = "0x1111111111111111111111111111111111111111";

function form(overrides: Partial<ScanFormValues> = {}): ScanFormValues {
  return {
    mode: "address",
    contractAddress: ADDRESS,
    chainId: "1",
    fork: "cancun",
    labels: "",
    bytecodeHex: "",
    sourceCode: "",
    solcVersion: "",
    enableExperimentalMl: false,
    ...overrides,
  };
}

describe("parseLabelList", () => {
  it("trims, drops empties and de-duplicates", () => {
    expect(parseLabelList(" defi , vault ,defi, , ")).toEqual(["defi", "vault"]);
  });

  it("returns an empty list for an empty string", () => {
    expect(parseLabelList("   ")).toEqual([]);
  });
});

describe("validateScanForm", () => {
  it("builds an address payload", () => {
    const result = validateScanForm(form({ labels: "defi, vault" }));
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.value.contractAddress).toBe(ADDRESS);
    expect(result.value.chainId).toBe(1);
    expect(result.value.labels).toEqual(["defi", "vault"]);
    expect(result.value.sourceCode).toBeUndefined();
    expect(result.value.bytecodeHex).toBeUndefined();
  });

  it("refuses an address that is not an address", () => {
    const result = validateScanForm(form({ contractAddress: "0x1234" }));
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.error).toContain("20-byte contract address");
  });

  it("builds a source payload and keeps the compiler version", () => {
    const result = validateScanForm(
      form({ mode: "source", contractAddress: "", sourceCode: "contract A {}", solcVersion: "0.8.26" }),
    );
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.value.sourceCode).toBe("contract A {}");
    expect(result.value.solcVersion).toBe("0.8.26");
    expect(result.value.contractAddress).toBeUndefined();
  });

  it("refuses an empty source", () => {
    const result = validateScanForm(form({ mode: "source", contractAddress: "", sourceCode: "  " }));
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.error).toContain("Solidity source");
  });

  it("builds a bytecode payload", () => {
    const result = validateScanForm(
      form({ mode: "bytecode", contractAddress: "", bytecodeHex: "0x60806040" }),
    );
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.value.bytecodeHex).toBe("0x60806040");
    expect(result.value.contractAddress).toBeUndefined();
  });

  it("refuses bytecode of an odd length", () => {
    const result = validateScanForm(
      form({ mode: "bytecode", contractAddress: "", bytecodeHex: "0x608" }),
    );
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.error).toContain("even number of hex characters");
  });

  it("refuses bytecode that is not hexadecimal", () => {
    const result = validateScanForm(
      form({ mode: "bytecode", contractAddress: "", bytecodeHex: "0xzz" }),
    );
    expect(result.ok).toBe(false);
  });

  it("refuses a chain id that is not a positive integer", () => {
    const result = validateScanForm(form({ chainId: "0" }));
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.error).toContain("Chain id");
  });

  it("defaults the fork when none is chosen", () => {
    const result = validateScanForm(form({ fork: "  " }));
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.value.fork).toBe("cancun");
  });
});

describe("validateScanPayload", () => {
  it("accepts an address payload", () => {
    const result = validateScanPayload({ contractAddress: ADDRESS, chainId: 1 });
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.value.contractAddress).toBe(ADDRESS);
    expect(result.value.fork).toBe("cancun");
  });

  it("refuses an empty payload", () => {
    const result = validateScanPayload({ chainId: 1 });
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.error).toContain("Supply a contract address");
  });

  it("refuses source and bytecode together", () => {
    const result = validateScanPayload({
      sourceCode: "contract A {}",
      bytecodeHex: "0x60",
      chainId: 1,
    });
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.error).toContain("not both");
  });

  it("refuses an address together with source", () => {
    const result = validateScanPayload({
      contractAddress: ADDRESS,
      sourceCode: "contract A {}",
      chainId: 1,
    });
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.error).toContain("not more than one");
  });

  it("refuses a malformed address", () => {
    const result = validateScanPayload({ contractAddress: "0xnope", chainId: 1 });
    expect(result.ok).toBe(false);
  });

  it("refuses a chain id that is not a number", () => {
    const result = validateScanPayload({ contractAddress: ADDRESS, chainId: "one" });
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.error).toContain("chainId");
  });

  it("keeps labels and the ML flag", () => {
    const result = validateScanPayload({
      contractAddress: ADDRESS,
      chainId: 1,
      labels: ["defi", "defi", "vault"],
      enableExperimentalMl: true,
    });
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.value.labels).toEqual(["defi", "vault"]);
    expect(result.value.enableExperimentalMl).toBe(true);
  });

  it("refuses a non-object body", () => {
    expect(validateScanPayload(null).ok).toBe(false);
    expect(validateScanPayload("nope").ok).toBe(false);
  });
});
