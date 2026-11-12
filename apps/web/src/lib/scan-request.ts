/**
 * The request a scan is made from, and the rules for making one.
 *
 * A scan analyses exactly one thing: a deployed contract, a piece of
 * Solidity source, or a blob of runtime bytecode. The three modes are
 * kept apart deliberately -- they promise different things and they fail
 * differently -- so the rules live here, in one place, and both the form
 * and the server-side proxy use them.
 */

export type ScanMode = "address" | "source" | "bytecode";

/** A 20-byte EVM address. */
export const ADDRESS_PATTERN = /^0x[0-9a-fA-F]{40}$/;

/** Hexadecimal bytecode, with or without the 0x prefix. */
export const HEX_PATTERN = /^(0x)?[0-9a-fA-F]+$/;

export interface ScanRequestPayload {
  contractAddress?: string;
  chainId: number;
  fork: string;
  labels: string[];
  bytecodeHex?: string;
  sourceCode?: string;
  solcVersion?: string;
  enableExperimentalMl?: boolean;
}

/** The raw values the form collects, before they are validated. */
export interface ScanFormValues {
  mode: ScanMode;
  contractAddress: string;
  chainId: string;
  fork: string;
  labels: string;
  bytecodeHex: string;
  sourceCode: string;
  solcVersion: string;
  enableExperimentalMl: boolean;
}

export type ScanValidation<T> =
  | { ok: true; value: T }
  | { ok: false; error: string };

function ok<T>(value: T): ScanValidation<T> {
  return { ok: true, value };
}

function fail<T>(error: string): ScanValidation<T> {
  return { ok: false, error };
}

/**
 * Parse a comma separated label list.
 *
 * Labels are a free-form organiser, so they are trimmed and de-duplicated
 * rather than rejected: a stray space should not cost a user their scan.
 */
export function parseLabelList(value: string): string[] {
  const seen = new Set<string>();
  for (const part of value.split(",")) {
    const label = part.trim();
    if (label) seen.add(label);
  }
  return [...seen];
}

/**
 * Validate the values collected by the form and build the request.
 *
 * The form uses this to refuse to submit something the backend would
 * reject anyway, so the user is told what is wrong before a round trip.
 */
export function validateScanForm(
  values: ScanFormValues,
): ScanValidation<ScanRequestPayload> {
  const address = values.contractAddress.trim();
  const bytecode = values.bytecodeHex.trim();
  const source = values.sourceCode.trim();

  if (values.mode === "address") {
    if (!ADDRESS_PATTERN.test(address)) {
      return fail("Enter a valid 20-byte contract address beginning with 0x.");
    }
  }
  if (values.mode === "bytecode") {
    const hex = bytecode.replace(/^0x/i, "");
    if (!hex || !HEX_PATTERN.test(hex) || hex.length % 2 !== 0) {
      return fail("Paste runtime bytecode as an even number of hex characters.");
    }
  }
  if (values.mode === "source") {
    if (!source) {
      return fail("Paste the Solidity source to compile.");
    }
  }

  const chainId = Number.parseInt(values.chainId, 10);
  if (!Number.isFinite(chainId) || chainId < 1) {
    return fail("Chain id must be a positive integer.");
  }

  const payload: ScanRequestPayload = {
    chainId,
    fork: values.fork.trim() || "cancun",
    labels: parseLabelList(values.labels),
    enableExperimentalMl: values.enableExperimentalMl,
  };

  if (values.mode === "address") payload.contractAddress = address;
  if (values.mode === "bytecode") payload.bytecodeHex = bytecode;
  if (values.mode === "source") {
    payload.sourceCode = source;
    const solcVersion = values.solcVersion.trim();
    if (solcVersion) payload.solcVersion = solcVersion;
  }

  return ok(payload);
}

/**
 * Validate a scan request that arrived at the server, from anywhere.
 *
 * The proxy is the last checkpoint before the backend, so it applies the
 * same rules the form does: exactly one thing to analyse, and no source
 * and bytecode together.
 */
export function validateScanPayload(body: unknown): ScanValidation<ScanRequestPayload> {
  const record = (body ?? {}) as Record<string, unknown>;
  const contractAddress = String(record.contractAddress ?? "").trim();
  const sourceCode = String(record.sourceCode ?? "").trim();
  const bytecodeHex = String(record.bytecodeHex ?? "").trim();

  if (!contractAddress && !sourceCode && !bytecodeHex) {
    return fail(
      "Supply a contract address, a Solidity source to compile, or runtime bytecode.",
    );
  }
  if (sourceCode && bytecodeHex) {
    return fail("Supply either a Solidity source or bytecode, not both.");
  }
  if (contractAddress && (sourceCode || bytecodeHex)) {
    return fail(
      "Supply either a contract address or source or bytecode, not more than one.",
    );
  }
  if (contractAddress && !ADDRESS_PATTERN.test(contractAddress)) {
    return fail("Enter a valid 20-byte contract address beginning with 0x.");
  }
  if (bytecodeHex) {
    const hex = bytecodeHex.replace(/^0x/i, "");
    if (!HEX_PATTERN.test(hex) || hex.length % 2 !== 0) {
      return fail("Paste runtime bytecode as an even number of hex characters.");
    }
  }

  const chainId = Number(record.chainId);
  if (!Number.isFinite(chainId) || chainId < 1) {
    return fail("chainId must be a positive integer.");
  }

  const labels = Array.isArray(record.labels)
    ? record.labels.map((entry) => String(entry).trim()).filter((entry) => entry.length > 0)
    : [];

  const payload: ScanRequestPayload = {
    chainId,
    fork: String(record.fork ?? "").trim() || "cancun",
    labels: [...new Set(labels)],
  };

  if (contractAddress) payload.contractAddress = contractAddress;
  if (sourceCode) payload.sourceCode = sourceCode;
  if (bytecodeHex) payload.bytecodeHex = bytecodeHex;

  const solcVersion =
    typeof record.solcVersion === "string" ? record.solcVersion.trim() : "";
  if (solcVersion) payload.solcVersion = solcVersion;

  if (typeof record.enableExperimentalMl === "boolean") {
    payload.enableExperimentalMl = record.enableExperimentalMl;
  }

  return ok(payload);
}
