import {
  countSeverities,
  emptySeverityCounts,
  toSeverity,
} from "./severity";
import { toReviewStatus, toScanStatus, toStageStatus } from "./status";
import { CORRESPONDENCE_STATUSES } from "./types";
import type {
  Artifact,
  CorrespondenceProof,
  CorrespondenceRunRequest,
  CorrespondenceStatus,
  CreatedScan,
  Finding,
  MythrilRunRequest,
  Reproducibility,
  ScanDetail,
  ScanJobInfo,
  ScanStage,
  ScanSummary,
  SeverityCounts,
} from "./types";

/**
 * Typed client for the CyberStratum FastAPI backend.
 *
 * The backend is not always running (and during a build it never is), so every
 * call resolves to an `ApiResult` instead of throwing. Callers render an
 * explicit "backend unreachable" state when `ok` is false.
 *
 * Routes mirror the live FastAPI service (design document section 10):
 *
 *   GET  /api/health                liveness probe
 *   GET  /api/v1/scans              paginated scan summaries
 *   GET  /api/v1/scans/{id}         scan detail (jobs, artifacts, findings)
 *   POST /api/v1/scans              queue a scan
 *   POST /api/v1/scans/{id}/mythril queue an on-demand Mythril deep analysis
 *   GET  /api/v1/scans/{id}/correspondence  stored source-to-bytecode proof
 *   GET  /api/v1/scans/{id}/report.pdf     the deterministic PDF report
 *   GET  /api/v1/findings           paginated findings, filterable
 *   GET  /api/v1/findings/summary   severity / status breakdown
 *
 * Every request carries the `X-API-Key` header.
 */

export const API_BASE_URL = (
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000"
).replace(/\/+$/, "");

/** Versioned API prefix defined in the design document (section 10). */
export const API_PREFIX = "/api/v1";

/**
 * Server-only API key presented to the backend as `X-API-Key`.
 *
 * This is intentionally read from a non-`NEXT_PUBLIC_` variable so Next.js
 * strips it from client bundles. Every call in this module originates from a
 * server component or a route handler, so the key never reaches the browser.
 */
export const API_KEY = process.env.API_KEY ?? "";

export type ApiErrorKind = "network" | "http" | "parse" | "not_found";

export interface ApiError {
  kind: ApiErrorKind;
  message: string;
  status?: number;
  detail?: string;
}

export type ApiResult<T> =
  | { ok: true; data: T }
  | { ok: false; error: ApiError };

const REQUEST_TIMEOUT_MS = 8000;

/**
 * The report endpoint assembles a PDF from stored evidence and its
 * provenance, so it gets a longer budget than an ordinary JSON call. It is
 * still a bounded wait: an unresponsive backend must not hang the page.
 */
const REPORT_TIMEOUT_MS = 30000;

async function request<T>(
  path: string,
  init?: RequestInit & { next?: { revalidate?: number | false } },
  options: { unprefixed?: boolean } = {},
): Promise<ApiResult<T>> {
  const url = options.unprefixed
    ? `${API_BASE_URL}${path}`
    : `${API_BASE_URL}${API_PREFIX}${path}`;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    const response = await fetch(url, {
      ...init,
      signal: controller.signal,
      cache: "no-store",
      headers: {
        Accept: "application/json",
        ...(init?.body ? { "Content-Type": "application/json" } : {}),
        ...(API_KEY ? { "X-API-Key": API_KEY } : {}),
        ...(init?.headers ?? {}),
      },
    });

    if (!response.ok) {
      const detail = await readDetail(response);
      return {
        ok: false,
        error: {
          kind: response.status === 404 ? "not_found" : "http",
          message:
            response.status === 404
              ? `The backend has no route for ${path}.`
              : response.status === 401
                ? "The backend rejected the API key (HTTP 401)."
                : `The backend responded with HTTP ${response.status}.`,
          status: response.status,
          detail,
        },
      };
    }

    if (response.status === 204) {
      return { ok: true, data: undefined as T };
    }

    const payload = (await response.json()) as unknown;
    return { ok: true, data: payload as T };
  } catch (error) {
    const aborted = error instanceof Error && error.name === "AbortError";
    return {
      ok: false,
      error: {
        kind: "network",
        message: aborted
          ? `The backend did not respond within ${REQUEST_TIMEOUT_MS / 1000}s.`
          : `Could not reach the backend at ${API_BASE_URL}.`,
        detail: error instanceof Error ? error.message : undefined,
      },
    };
  } finally {
    clearTimeout(timeout);
  }
}

async function readDetail(response: Response): Promise<string | undefined> {
  try {
    const text = await response.text();
    if (!text) return undefined;
    try {
      const parsed = JSON.parse(text) as {
        detail?: unknown;
        message?: unknown;
        error?: { message?: unknown } | string;
      };
      const detail = parsed.detail ?? parsed.message ?? parsed.error;
      if (typeof detail === "string") return detail;
      if (detail && typeof detail === "object" && "message" in detail) {
        const message = (detail as { message?: unknown }).message;
        if (typeof message === "string") return message;
      }
      if (detail) return JSON.stringify(detail);
      return text.slice(0, 400);
    } catch {
      return text.slice(0, 400);
    }
  } catch {
    return undefined;
  }
}

/**
 * Human-readable summary of an API failure.
 *
 * The UI shows a different heading depending on the failure: an unreachable
 * backend is an environment problem, a rejected key is a configuration
 * problem, and anything else is a request problem.
 */
export function describeApiError(error: ApiError): { title: string; message: string } {
  if (error.kind === "network") {
    return {
      title: "Backend unreachable",
      message: `The CyberStratum API at ${API_BASE_URL} did not respond, so live data cannot be shown.`,
    };
  }
  if (error.status === 401 || error.status === 403) {
    return {
      title: "API key rejected",
      message:
        "The backend rejected the API key. Check the server-only API_KEY value in apps/web/.env.local.",
    };
  }
  if (error.kind === "not_found") {
    return {
      title: "Not found",
      message: error.message,
    };
  }
  return {
    title: "Backend error",
    message: error.message,
  };
}

/* ------------------------------------------------------------------ */
/* Health                                                              */
/* ------------------------------------------------------------------ */

export interface HealthStatus {
  status: string;
  detail: string | null;
  version: string | null;
}

/**
 * Liveness probe. The service mounts the route at `/api/health`; the bare
 * `/health` path is tried as a fallback so the UI keeps working if the mount
 * point moves.
 */
export async function getHealth(): Promise<ApiResult<HealthStatus>> {
  let last: ApiResult<HealthStatus> | null = null;

  for (const candidate of ["/api/health", "/health"]) {
    const result = await request<Record<string, unknown>>(candidate, undefined, {
      unprefixed: true,
    });
    if (result.ok) {
      const body = result.data ?? {};
      return {
        ok: true,
        data: {
          status: pickString(body, ["status", "state"]) ?? "ok",
          detail: pickString(body, ["detail", "message"]),
          version: pickString(body, ["version"]),
        },
      };
    }
    last = result;
  }

  return (
    last ?? {
      ok: false,
      error: { kind: "network", message: "Could not reach the backend." },
    }
  );
}

/* ------------------------------------------------------------------ */
/* Scans                                                               */
/* ------------------------------------------------------------------ */

export interface ScanListResult {
  items: ScanSummary[];
  total: number;
  limit: number;
  offset: number;
}

export async function listScans(params?: {
  status?: string;
  limit?: number;
  offset?: number;
}): Promise<ApiResult<ScanListResult>> {
  const query = new URLSearchParams();
  if (params?.status) query.set("status", params.status);
  if (params?.limit !== undefined) query.set("limit", String(params.limit));
  if (params?.offset !== undefined) query.set("offset", String(params.offset));
  const suffix = query.toString() ? `?${query.toString()}` : "";
  const result = await request<unknown>(`/scans${suffix}`);
  if (!result.ok) return result;

  const record = asRecord(result.data);
  const items = toArray(result.data).map(normaliseScanSummary);
  return {
    ok: true,
    data: {
      items,
      total: pickNumber(record, ["total"]) ?? items.length,
      limit: pickNumber(record, ["limit"]) ?? items.length,
      offset: pickNumber(record, ["offset"]) ?? 0,
    },
  };
}

export async function getScan(id: string): Promise<ApiResult<ScanDetail>> {
  const result = await request<unknown>(`/scans/${encodeURIComponent(id)}`);
  if (!result.ok) return result;
  return { ok: true, data: normaliseScanDetail(result.data) };
}

/**
 * Findings for one scan. The backend exposes them through the shared findings
 * collection filtered by `scan_id`; the scan detail response also embeds them.
 */
export async function getScanFindings(id: string): Promise<ApiResult<Finding[]>> {
  const result = await request<unknown>(
    `/findings?scan_id=${encodeURIComponent(id)}`,
  );
  if (!result.ok) return result;
  return { ok: true, data: toArray(result.data).map(normaliseFinding) };
}

export interface CreateScanPayload {
  contractAddress: string;
  chainId: number;
  fork: string;
  /**
   * Optional labels for the contract target. The backend stores a single label
   * per target, so the list is joined into one comma-separated string.
   */
  labels?: string[];
  bytecodeHex?: string;
  enableExperimentalMl?: boolean;
}

export async function createScan(
  payload: CreateScanPayload,
): Promise<ApiResult<CreatedScan>> {
  const label = (payload.labels ?? []).join(", ").trim();
  // The backend forbids unknown fields, so only documented keys are sent.
  const body: Record<string, unknown> = {
    contract_address: payload.contractAddress,
    chain_id: payload.chainId,
    fork: payload.fork,
  };
  if (label) body.label = label.slice(0, 200);
  if (payload.bytecodeHex) body.bytecode_hex = payload.bytecodeHex;
  if (payload.enableExperimentalMl !== undefined) {
    body.enable_experimental_ml = payload.enableExperimentalMl;
  }

  const result = await request<unknown>("/scans", {
    method: "POST",
    body: JSON.stringify(body),
  });
  if (!result.ok) return result;
  return { ok: true, data: normaliseCreatedScan(result.data) };
}

/* ------------------------------------------------------------------ */
/* Findings                                                            */
/* ------------------------------------------------------------------ */

export interface FindingListResult {
  items: Finding[];
  total: number;
  limit: number;
  offset: number;
}

export async function listFindings(params?: {
  severity?: string;
  status?: string;
  category?: string;
  scanId?: string;
  limit?: number;
  offset?: number;
}): Promise<ApiResult<FindingListResult>> {
  const query = new URLSearchParams();
  if (params?.severity) query.set("severity", params.severity);
  if (params?.status) query.set("status", params.status);
  if (params?.category) query.set("category", params.category);
  if (params?.scanId) query.set("scan_id", params.scanId);
  if (params?.limit !== undefined) query.set("limit", String(params.limit));
  if (params?.offset !== undefined) query.set("offset", String(params.offset));
  const suffix = query.toString() ? `?${query.toString()}` : "";
  const result = await request<unknown>(`/findings${suffix}`);
  if (!result.ok) return result;

  const record = asRecord(result.data);
  const items = toArray(result.data).map(normaliseFinding);
  return {
    ok: true,
    data: {
      items,
      total: pickNumber(record, ["total"]) ?? items.length,
      limit: pickNumber(record, ["limit"]) ?? items.length,
      offset: pickNumber(record, ["offset"]) ?? 0,
    },
  };
}

export interface FindingsSummary {
  total: number;
  bySeverity: SeverityCounts;
  byStatus: Record<string, number>;
  averageConfidence: number;
}

/** Aggregate finding counts by severity and triage status. */
export async function getFindingsSummary(params?: {
  scanId?: string;
}): Promise<ApiResult<FindingsSummary>> {
  const query = new URLSearchParams();
  if (params?.scanId) query.set("scan_id", params.scanId);
  const suffix = query.toString() ? `?${query.toString()}` : "";
  const result = await request<unknown>(`/findings/summary${suffix}`);
  if (!result.ok) return result;

  const record = asRecord(result.data);
  const bySeverity = emptySeverityCounts();
  for (const entry of pickArray(record, ["by_severity", "bySeverity"])) {
    const row = asRecord(entry);
    const count = pickNumber(row, ["count"]);
    if (count === null) continue;
    bySeverity[toSeverity(row["severity"])] += count;
  }

  const byStatus: Record<string, number> = {};
  for (const entry of pickArray(record, ["by_status", "byStatus"])) {
    const row = asRecord(entry);
    const count = pickNumber(row, ["count"]);
    const status = pickString(row, ["status"]);
    if (count === null || !status) continue;
    byStatus[status] = (byStatus[status] ?? 0) + count;
  }

  const severityTotal = Object.values(bySeverity).reduce((sum, n) => sum + n, 0);
  return {
    ok: true,
    data: {
      total: pickNumber(record, ["total"]) ?? severityTotal,
      bySeverity,
      byStatus,
      averageConfidence:
        pickNumber(record, ["average_confidence", "averageConfidence"]) ?? 0,
    },
  };
}

/* ------------------------------------------------------------------ */
/* Normalisation helpers                                               */
/* ------------------------------------------------------------------ */

function toArray(value: unknown): unknown[] {
  if (Array.isArray(value)) return value;
  if (value && typeof value === "object") {
    const record = value as Record<string, unknown>;
    for (const key of ["data", "items", "results", "scans", "findings", "rows"]) {
      const candidate = record[key];
      if (Array.isArray(candidate)) return candidate;
      if (candidate && typeof candidate === "object") {
        const nested = toArray(candidate);
        if (nested.length) return nested;
      }
    }
  }
  return [];
}

function pickString(
  record: Record<string, unknown> | null | undefined,
  keys: string[],
): string | null {
  if (!record) return null;
  for (const key of keys) {
    const value = record[key];
    if (typeof value === "string" && value.trim()) return value.trim();
    if (typeof value === "number" && Number.isFinite(value)) return String(value);
  }
  return null;
}

function pickNumber(
  record: Record<string, unknown> | null | undefined,
  keys: string[],
): number | null {
  if (!record) return null;
  for (const key of keys) {
    const value = record[key];
    if (typeof value === "number" && Number.isFinite(value)) return value;
    if (typeof value === "string" && value.trim() !== "") {
      const parsed = Number(value);
      if (Number.isFinite(parsed)) return parsed;
    }
  }
  return null;
}

function pickBoolean(
  record: Record<string, unknown> | null | undefined,
  keys: string[],
): boolean {
  if (!record) return false;
  for (const key of keys) {
    const value = record[key];
    if (typeof value === "boolean") return value;
    if (typeof value === "string") {
      const lowered = value.toLowerCase();
      if (lowered === "true" || lowered === "1" || lowered === "yes") return true;
    }
  }
  return false;
}

function pickRecord(
  record: Record<string, unknown> | null | undefined,
  keys: string[],
): Record<string, unknown> {
  if (!record) return {};
  for (const key of keys) {
    const value = record[key];
    if (value && typeof value === "object" && !Array.isArray(value)) {
      return value as Record<string, unknown>;
    }
  }
  return {};
}

function pickArray(
  record: Record<string, unknown> | null | undefined,
  keys: string[],
): unknown[] {
  if (!record) return [];
  for (const key of keys) {
    const value = record[key];
    if (Array.isArray(value)) return value;
  }
  return [];
}

function toIsoString(
  record: Record<string, unknown> | null | undefined,
  keys: string[],
): string | null {
  if (!record) return null;
  for (const key of keys) {
    const value = record[key];
    if (typeof value === "string" && value.trim()) {
      const date = new Date(value);
      if (!Number.isNaN(date.getTime())) return date.toISOString();
    }
    if (typeof value === "number" && Number.isFinite(value)) {
      const date = new Date(value);
      if (!Number.isNaN(date.getTime())) return date.toISOString();
    }
  }
  return null;
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function normaliseCounts(record: Record<string, unknown>): SeverityCounts {
  const nested = pickRecord(record, [
    "finding_counts",
    "findingCounts",
    "counts_by_severity",
  ]);
  if (Object.keys(nested).length > 0) {
    const counts = emptySeverityCounts();
    for (const [key, value] of Object.entries(nested)) {
      if (typeof value === "number") counts[toSeverity(key)] += value;
    }
    return counts;
  }
  const single = pickNumber(record, ["severity"]);
  if (single !== null) {
    const counts = emptySeverityCounts();
    counts[toSeverity(record["severity"])] += 1;
    return counts;
  }
  return emptySeverityCounts();
}

function normaliseLabels(record: Record<string, unknown>): string[] {
  const raw = pickArray(record, ["labels", "tags"]);
  const labels = raw
    .map((label) =>
      typeof label === "string"
        ? label
        : typeof label === "object" && label !== null
          ? pickString(asRecord(label), ["name", "label", "value"])
          : null,
    )
    .filter((label): label is string => typeof label === "string" && label.length > 0);
  if (labels.length > 0) return labels;

  // The backend stores a single comma-separated label per target.
  const single = pickString(record, ["label"]);
  if (!single) return [];
  return single
    .split(",")
    .map((label) => label.trim())
    .filter((label) => label.length > 0);
}

function normaliseScanSummary(value: unknown): ScanSummary {
  const record = asRecord(value);
  const counts = normaliseCounts(record);
  const total =
    pickNumber(record, ["total_findings", "totalFindings", "findings_count"]) ??
    Object.values(counts).reduce((sum, n) => sum + n, 0);
  const startedAt = toIsoString(record, ["started_at", "startedAt"]);
  const completedAt = toIsoString(record, [
    "completed_at",
    "completedAt",
    "finished_at",
  ]);
  const durationMs =
    pickNumber(record, ["duration_ms", "durationMs", "elapsed_ms"]) ??
    (startedAt && completedAt
      ? new Date(completedAt).getTime() - new Date(startedAt).getTime()
      : null);

  return {
    id: pickString(record, ["id", "scan_id", "scanId"]) ?? "unknown",
    contractAddress:
      pickString(record, [
        "contract_address",
        "contractAddress",
        "address",
        "target_address",
      ]) ?? "—",
    targetId: pickString(record, ["target_id", "targetId"]),
    chainId: pickNumber(record, ["chain_id", "chainId", "chain"]),
    fork: pickString(record, ["fork", "evm_fork", "evmFork"]),
    bytecodeSource: pickString(record, ["bytecode_source", "bytecodeSource"]),
    status: toScanStatus(record["status"]),
    createdAt: toIsoString(record, [
      "created_at",
      "createdAt",
      "queued_at",
      "requested_at",
    ]),
    startedAt,
    completedAt,
    durationMs:
      durationMs !== null && Number.isFinite(durationMs) ? durationMs : null,
    riskScore: pickNumber(record, ["risk_score", "riskScore"]),
    findingCounts: counts,
    totalFindings: total,
    requestedBy: pickString(record, ["requested_by", "requestedBy", "created_by"]),
    labels: normaliseLabels(record),
    parserVersion: pickString(record, ["parser_version", "parserVersion"]),
    rulesetVersion: pickString(record, ["ruleset_version", "rulesetVersion"]),
    modelVersion: pickString(record, ["model_version", "modelVersion"]),
    sourceAudited: pickBoolean(record, ["source_audited", "sourceAudited"]),
    sourceAuditSkipped: pickString(record, [
      "source_audit_skipped",
      "sourceAuditSkipped",
    ]),
    // A Mythril run that did not happen is "not run", never "nothing found".
    mythrilRan: pickBoolean(record, ["mythril_ran", "mythrilRan"]) ?? false,
    mythrilSkipped: pickString(record, ["mythril_skipped", "mythrilSkipped"]),
    error:
      pickString(record, [
        "error_message_redacted",
        "error_message",
        "errorMessage",
        "failure_reason",
      ]) ?? pickString(record, ["error_code", "errorCode"]),
  };
}

/**
 * The backend does not expose a stage array: it records the scan status, the
 * queue jobs and one artifact per pipeline stage. The stage list is therefore
 * derived from the status of the scan, so the timeline reflects the real
 * pipeline (intake -> disassembly -> CFG -> features -> rules).
 */
const STAGE_DEFINITIONS = [
  { key: "intake", label: "Bytecode intake", artifactKind: "bytecode" },
  { key: "disassembly", label: "Disassembly", artifactKind: "disassembly" },
  { key: "cfg", label: "Control-flow graph", artifactKind: "cfg" },
  { key: "features", label: "Feature extraction", artifactKind: "features" },
  { key: "rules", label: "Rule engine", artifactKind: null },
] as const;

/** Backend scan statuses in pipeline order (see `ScanStatus` in the API). */
const PIPELINE_STATUSES = [
  "queued",
  "fetching_bytecode",
  "disassembling",
  "building_cfg",
  "extracting_features",
  "running_detectors",
] as const;

function pipelineIndex(status: string | null): number {
  if (!status) return -1;
  return (PIPELINE_STATUSES as readonly string[]).indexOf(status);
}

function normaliseStages(
  record: Record<string, unknown>,
  artifacts: Artifact[],
  findings: Finding[],
): ScanStage[] {
  const explicit = pickArray(record, ["stages", "pipeline", "steps"]);
  if (explicit.length > 0) {
    return explicit.map((entry, index) => {
      const stage = asRecord(entry);
      return {
        key: pickString(stage, ["key", "id", "stage"]) ?? `stage-${index + 1}`,
        label:
          pickString(stage, ["label", "name", "title", "stage"]) ??
          `Stage ${index + 1}`,
        status: toStageStatus(stage["status"] ?? stage["state"]),
        startedAt: toIsoString(stage, ["started_at", "startedAt", "start_time"]),
        endedAt: toIsoString(stage, [
          "ended_at",
          "endedAt",
          "completed_at",
          "finish_time",
        ]),
        durationMs: pickNumber(stage, ["duration_ms", "durationMs", "elapsed_ms"]),
        version: pickString(stage, ["version", "tool_version", "toolVersion"]),
        message: pickString(stage, ["message", "detail", "summary", "error"]),
      } satisfies ScanStage;
    });
  }

  const rawStatus = pickString(record, ["status"]);
  const status = toScanStatus(rawStatus);
  const currentIndex = pipelineIndex(rawStatus);
  const terminal =
    status === "completed" || status === "partial" || status === "failed";
  const cancelled = status === "cancelled";
  const parserVersion = pickString(record, ["parser_version", "parserVersion"]);
  const errorMessage =
    pickString(record, ["error_message_redacted", "error_message"]) ??
    pickString(record, ["error_code"]);
  const errorCode = pickString(record, ["error_code", "errorCode"]);

  // When a scan failed, the error code says which stage gave up.
  let failedIndex = -1;
  if (status === "failed") {
    const code = (errorCode ?? "").toLowerCase();
    if (code.includes("bytecode") || code.includes("fetch")) failedIndex = 0;
    else if (code.includes("disassembl")) failedIndex = 1;
    else if (code.includes("cfg") || code.includes("graph")) failedIndex = 2;
    else if (code.includes("feature")) failedIndex = 3;
    else if (code.includes("rule") || code.includes("detector")) {
      failedIndex = 4;
    }
  }

  return STAGE_DEFINITIONS.map((definition, index) => {
    const artifact = definition.artifactKind
      ? artifacts.find(
          (candidate) => candidate.kind.toLowerCase() === definition.artifactKind,
        )
      : undefined;

    let stageStatus: ScanStage["status"];
    if (cancelled) {
      stageStatus = index === 0 ? "skipped" : "pending";
    } else if (status === "failed" && index === failedIndex) {
      stageStatus = "failed";
    } else if (failedIndex >= 0 && index < failedIndex) {
      stageStatus = "completed";
    } else if (failedIndex >= 0) {
      stageStatus = "pending";
    } else if (terminal) {
      // A partial scan still ran every stage; unresolved edges are reported
      // separately as an analysis-limitation finding.
      stageStatus = "completed";
    } else if (currentIndex < 0) {
      stageStatus = "pending";
    } else if (index < currentIndex) {
      stageStatus = "completed";
    } else if (index === currentIndex) {
      stageStatus = "running";
    } else {
      stageStatus = "pending";
    }

    return {
      key: definition.key,
      label: definition.label,
      status: stageStatus,
      startedAt: null,
      endedAt: artifact?.createdAt ?? null,
      durationMs: null,
      version:
        definition.key === "rules"
          ? pickString(record, ["ruleset_version", "rulesetVersion"])
          : parserVersion,
      message: stageStatus === "failed" ? errorMessage : null,
    } satisfies ScanStage;
  });
}

function basename(objectKey: string | null): string | null {
  if (!objectKey) return null;
  const parts = objectKey.split("/");
  return parts[parts.length - 1] || null;
}

function normaliseArtifacts(value: unknown): Artifact[] {
  return toArray(value).map((entry, index) => {
    const record = asRecord(entry);
    const objectKey = pickString(record, [
      "object_key",
      "objectKey",
      "storage_key",
    ]);
    const uri = pickString(record, ["uri", "url"]);
    return {
      id: pickString(record, ["id", "key", "name"]) ?? `artifact-${index + 1}`,
      name:
        pickString(record, ["name", "filename", "label"]) ??
        basename(objectKey) ??
        `artifact-${index + 1}`,
      kind: pickString(record, ["kind", "type"]) ?? "artifact",
      contentType: pickString(record, ["content_type", "contentType"]),
      sizeBytes: pickNumber(record, [
        "byte_size",
        "byteSize",
        "size_bytes",
        "size",
      ]),
      // Only absolute URLs are usable as links; object keys are storage paths.
      uri: uri && /^https?:\/\//i.test(uri) ? uri : null,
      objectKey,
      sha256: pickString(record, ["sha256", "hash", "checksum"]),
      createdAt: toIsoString(record, ["created_at", "createdAt"]),
    } satisfies Artifact;
  });
}

function normaliseReproducibility(
  record: Record<string, unknown>,
  artifacts: Artifact[],
): Reproducibility {
  const repro = pickRecord(record, ["reproducibility", "repro", "provenance"]);
  const source = Object.keys(repro).length > 0 ? { ...record, ...repro } : record;

  const toolVersions: { name: string; version: string }[] = [];
  const parserVersion = pickString(source, ["parser_version", "parserVersion"]);
  const rulesetVersion = pickString(source, ["ruleset_version", "rulesetVersion"]);
  const modelVersion = pickString(source, ["model_version", "modelVersion"]);
  for (const entry of pickArray(source, ["tool_versions", "toolVersions", "tools"])) {
    const tool = asRecord(entry);
    const name = pickString(tool, ["name", "tool", "key"]);
    const version = pickString(tool, ["version", "value"]);
    if (!name && !version) continue;
    toolVersions.push({ name: name ?? "unknown", version: version ?? "—" });
  }
  // Only fall back to the scan-level versions when the backend did not report
  // an explicit tool list.
  if (toolVersions.length === 0) {
    if (parserVersion) toolVersions.push({ name: "parser", version: parserVersion });
    if (rulesetVersion) toolVersions.push({ name: "ruleset", version: rulesetVersion });
    if (modelVersion) toolVersions.push({ name: "model", version: modelVersion });
  }

  // The opcode table is fork-keyed, so the fork identifies the table used.
  const fork = pickString(source, ["fork"]);
  const opcodeTableVersion =
    pickString(source, [
      "opcode_table_version",
      "opcodeTableVersion",
      "opcodes_version",
      "opcode_table_schema_version",
    ]) ?? fork;

  // The bytecode artifact carries the SHA-256 of the analysed bytecode, which
  // is the input hash a reproduction has to match.
  const bytecodeArtifact = artifacts.find(
    (artifact) => artifact.kind.toLowerCase() === "bytecode",
  );
  const bytecodeHash =
    pickString(source, ["bytecode_hash", "bytecodeHash", "code_hash"]) ??
    bytecodeArtifact?.sha256 ??
    null;

  const environment = pickRecord(source, [
    "environment",
    "env",
    "runtime_environment",
  ]);
  const env: Record<string, string> = {};
  for (const [key, value] of Object.entries(environment)) {
    if (
      typeof value === "string" ||
      typeof value === "number" ||
      typeof value === "boolean"
    ) {
      env[key] = String(value);
    }
  }
  if (fork) env["evm_fork"] = fork;
  const bytecodeSource = pickString(source, ["bytecode_source", "bytecodeSource"]);
  if (bytecodeSource) env["bytecode_source"] = bytecodeSource;

  return {
    toolVersions,
    opcodeTableVersion,
    bytecodeHash,
    rulesetVersion,
    modelVersion,
    featureSchemaVersion: pickString(source, [
      "feature_schema_version",
      "featureSchemaVersion",
    ]),
    environment: env,
  };
}

function normaliseJobs(value: unknown): ScanJobInfo[] {
  return toArray(value).map((entry, index) => {
    const record = asRecord(entry);
    return {
      id: pickString(record, ["id", "job_id"]) ?? `job-${index + 1}`,
      jobType: pickString(record, ["job_type", "jobType", "type"]) ?? "scan",
      queueName: pickString(record, ["queue_name", "queueName"]),
      status: pickString(record, ["status", "state"]) ?? "unknown",
      attempt: pickNumber(record, ["attempt"]),
      startedAt: toIsoString(record, ["started_at", "startedAt"]),
      finishedAt: toIsoString(record, ["finished_at", "finishedAt", "completed_at"]),
      durationMs: pickNumber(record, ["duration_ms", "durationMs"]),
    } satisfies ScanJobInfo;
  });
}

function normaliseScanDetail(value: unknown): ScanDetail {
  const record = asRecord(value);
  const summary = normaliseScanSummary(value);
  const artifacts = normaliseArtifacts(pickArray(record, ["artifacts", "files"]));
  const findings = pickArray(record, ["findings"]).map(normaliseFinding);
  const jobs = normaliseJobs(pickArray(record, ["jobs"]));

  const coverage = pickRecord(record, ["coverage", "graph_coverage"]);
  let coverageValue: ScanDetail["coverage"] = null;
  if (Object.keys(coverage).length > 0) {
    coverageValue = {
      resolvedJumps: pickNumber(coverage, ["resolved_jumps", "resolvedJumps"]),
      unresolvedJumps: pickNumber(coverage, [
        "unresolved_jumps",
        "unresolvedJumps",
      ]),
    };
  } else {
    // The pipeline reports unresolved edges as an analysis-limitation finding.
    const limitation = findings.find(
      (finding) => finding.category === "analysis_limitation",
    );
    const unresolved = limitation?.edgeCounts?.unresolvedEdgeCount;
    if (typeof unresolved === "number") {
      coverageValue = { resolvedJumps: null, unresolvedJumps: unresolved };
    }
  }

  const durationMs =
    summary.durationMs ??
    jobs.find((job) => job.durationMs !== null)?.durationMs ??
    null;

  return {
    ...summary,
    durationMs,
    stages: normaliseStages(record, artifacts, findings),
    artifacts,
    findings,
    jobs,
    reproducibility: normaliseReproducibility(record, artifacts),
    warnings: pickArray(record, ["warnings", "parser_warnings"])
      .map((warning) =>
        typeof warning === "string"
          ? warning
          : pickString(asRecord(warning), ["message", "detail"]),
      )
      .filter((warning): warning is string => typeof warning === "string"),
    coverage: coverageValue,
    correspondence: normaliseCorrespondence(
      pickRecord(record, ["correspondence", "correspondence_proof"]),
      summary.id,
    ),
  };
}

/* ------------------------------------------------------------------ */
/* Correspondence proof                                                 */
/* ------------------------------------------------------------------ */

/**
 * Normalise a correspondence proof.
 *
 * A missing proof is `null`, not a fabricated one. A proof whose status the
 * backend did not report defaults to "skipped" - the honest reading of "the
 * check did not run", and never "mismatch", which would be an accusation.
 */
function normaliseCorrespondence(
  value: Record<string, unknown>,
  scanId: string,
): CorrespondenceProof | null {
  if (Object.keys(value).length === 0) return null;
  const raw = value["status"];
  const statusText = typeof raw === "string" ? raw.toLowerCase() : "";
  const status = (
    CORRESPONDENCE_STATUSES as readonly string[]
  ).includes(statusText)
    ? (statusText as CorrespondenceStatus)
    : "skipped";

  return {
    scanId: pickString(value, ["scan_id", "scanId"]) ?? scanId,
    status,
    skipped: pickString(value, ["skipped", "skipped_reason", "reason"]),
    compilerVersion: pickString(value, ["compiler_version", "compilerVersion"]),
    sourcePath: pickString(value, ["source_path", "sourcePath"]),
    runtimeSha256: pickString(value, ["runtime_sha256", "runtimeSha256"]),
    executableSha256: pickString(value, [
      "executable_sha256",
      "executableSha256",
    ]),
    metadataSha256: pickString(value, ["metadata_sha256", "metadataSha256"]),
    runtimeByteSize: pickNumber(value, ["runtime_byte_size", "runtimeByteSize"]),
    executableByteSize: pickNumber(value, [
      "executable_byte_size",
      "executableByteSize",
    ]),
    instructionCount: pickNumber(value, ["instruction_count", "instructionCount"]),
    mappedInstructionCount: pickNumber(value, [
      "mapped_instruction_count",
      "mappedInstructionCount",
    ]),
  };
}

/**
 * Fetch the stored source-to-bytecode correspondence proof for a scan.
 *
 * `null` means no proof has been established. It does not mean the source
 * failed to match - that is a separate, explicit status.
 */
export async function getCorrespondence(
  id: string,
): Promise<ApiResult<CorrespondenceProof | null>> {
  const result = await request<unknown>(
    `/scans/${encodeURIComponent(id)}/correspondence`,
  );
  if (!result.ok) return result;
  return {
    ok: true,
    data: normaliseCorrespondence(asRecord(result.data), id),
  };
}

/* ------------------------------------------------------------------ */
/* Mythril (manual, on-demand)                                         */
/* ------------------------------------------------------------------ */

/**
 * Request an on-demand Mythril deep analysis for a scan.
 *
 * Mythril is manual-only by decision: it runs out of process, on its own
 * queue, with its own budget, and never as part of a standard scan. The
 * response reports that the work was *queued* - it says nothing about what
 * Mythril will find, and a later run that produced no verdict must not be
 * read as "clean".
 */
export async function triggerMythril(
  id: string,
): Promise<ApiResult<MythrilRunRequest>> {
  const result = await request<unknown>(
    `/scans/${encodeURIComponent(id)}/mythril`,
    {
      method: "POST",
      body: JSON.stringify({}),
    },
  );
  if (!result.ok) return result;
  const record = asRecord(result.data);
  return {
    ok: true,
    data: {
      scanId: pickString(record, ["scan_id", "scanId"]) ?? id,
      jobId: pickString(record, ["job_id", "jobId"]),
      status: pickString(record, ["status"]) ?? "queued",
      queue: pickString(record, ["queue", "queue_name", "queueName"]),
      message: pickString(record, ["message", "detail"]),
    },
  };
}

/* ------------------------------------------------------------------ */
/* Correspondence (manual, on-demand)                                 */
/* ------------------------------------------------------------------ */

/**
 * Request an on-demand source-to-bytecode correspondence proof.
 *
 * The proof recompiles the contract's verified source and compares it with
 * the deployed runtime, so it is a compiler run rather than a bytecode scan.
 * It is therefore manual-only, on its own queue, with its own budget.
 *
 * The response reports that the work was *queued*. It does not license a
 * source claim: only a proof with the `established` status does that, and a
 * missing proof is not a mismatch.
 */
export async function triggerCorrespondence(
  id: string,
): Promise<ApiResult<CorrespondenceRunRequest>> {
  const result = await request<unknown>(
    `/scans/${encodeURIComponent(id)}/correspondence`,
    {
      method: "POST",
      body: JSON.stringify({}),
    },
  );
  if (!result.ok) return result;
  const record = asRecord(result.data);
  return {
    ok: true,
    data: {
      scanId: pickString(record, ["scan_id", "scanId"]) ?? id,
      jobId: pickString(record, ["job_id", "jobId"]),
      status: pickString(record, ["status"]) ?? "queued",
      queue: pickString(record, ["queue", "queue_name", "queueName"]),
      message: pickString(record, ["message", "detail"]),
    },
  };
}

/**
 * The same-origin URL of the PDF report for a scan.
 *
 * The report has to be fetched server-side. The browser cannot present the
 * server-only `API_KEY`, so a direct link to the backend would come back
 * unauthorised. The route handler at `/api/scans/[id]/report` attaches the
 * key and streams the PDF back.
 */
export function scanReportUrl(id: string): string {
  return `/api/scans/${encodeURIComponent(id)}/report`;
}

/**
 * Fetch the PDF report for a scan as raw bytes.
 *
 * The report is binary, so it cannot go through the JSON `request` helper.
 * The server-only API key is attached here and the bytes are handed back to
 * the route handler, which streams them to the browser.
 */
export async function fetchScanReport(
  id: string,
): Promise<ApiResult<{ bytes: Uint8Array; sha256: string | null }>> {
  const url = `${API_BASE_URL}${API_PREFIX}/scans/${encodeURIComponent(
    id,
  )}/report.pdf`;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), REPORT_TIMEOUT_MS);
  try {
    const response = await fetch(url, {
      signal: controller.signal,
      cache: "no-store",
      headers: {
        Accept: "application/pdf",
        ...(API_KEY ? { "X-API-Key": API_KEY } : {}),
      },
    });

    if (!response.ok) {
      const detail = await readDetail(response);
      return {
        ok: false,
        error: {
          kind: response.status === 404 ? "not_found" : "http",
          message:
            response.status === 404
              ? "The backend has no report endpoint for this scan."
              : `The backend responded with HTTP ${response.status}.`,
          status: response.status,
          detail,
        },
      };
    }

    const bytes = new Uint8Array(await response.arrayBuffer());
    return {
      ok: true,
      data: { bytes, sha256: response.headers.get("X-Report-SHA256") },
    };
  } catch (error) {
    const aborted = error instanceof Error && error.name === "AbortError";
    return {
      ok: false,
      error: {
        kind: "network",
        message: aborted
          ? `The backend did not produce a report within ${REPORT_TIMEOUT_MS / 1000}s.`
          : `Could not reach the backend at ${API_BASE_URL}.`,
        detail: error instanceof Error ? error.message : undefined,
      },
    };
  } finally {
    clearTimeout(timeout);
  }
}

function normaliseFinding(value: unknown): Finding {
  const record = asRecord(value);
  const evidenceRecord = pickRecord(record, ["evidence"]);
  const byteOffsets = [
    ...pickArray(evidenceRecord, ["byte_offsets", "byteOffsets", "offsets"]),
    ...pickArray(record, ["byte_offsets", "byteOffsets", "offsets"]),
  ]
    .map((offset) => (typeof offset === "number" ? offset : Number(offset)))
    .filter((offset) => Number.isFinite(offset));

  // The baseline detectors report single instruction offsets by name.
  for (const key of ["callOffset", "storageWriteOffset", "instructionOffset"]) {
    const value = pickNumber(evidenceRecord, [key]);
    if (value !== null && !byteOffsets.includes(value)) byteOffsets.push(value);
  }
  byteOffsets.sort((a, b) => a - b);

  const signals = [
    ...pickArray(evidenceRecord, ["signals"]),
    ...pickArray(record, ["signals"]),
  ].filter((signal): signal is string => typeof signal === "string");

  const edgeCounts: Record<string, number> = {};
  for (const key of ["edgeCount", "unresolvedEdgeCount"]) {
    const value = pickNumber(evidenceRecord, [key]);
    if (value !== null) edgeCounts[key] = value;
  }

  const confidenceRaw = pickNumber(record, ["confidence", "score"]);
  const confidence =
    confidenceRaw === null
      ? null
      : confidenceRaw > 0 && confidenceRaw <= 1
        ? confidenceRaw
        : confidenceRaw > 1
          ? confidenceRaw / 100
          : confidenceRaw;

  return {
    id: pickString(record, ["id", "finding_id", "findingId"]) ?? "unknown",
    scanId: pickString(record, ["scan_id", "scanId"]),
    contractAddress:
      pickString(record, [
        "contract_address",
        "contractAddress",
        "address",
        "target_address",
      ]) ?? "—",
    chainId: pickNumber(record, ["chain_id", "chainId", "chain"]),
    severity: toSeverity(record["severity"]),
    confidence,
    reviewStatus: toReviewStatus(
      record["status"] ?? record["review_status"] ?? record["reviewStatus"],
    ),
    category:
      pickString(record, ["category", "weakness", "class"]) ?? "uncategorised",
    title:
      pickString(record, ["title", "summary", "name"]) ??
      pickString(record, ["category"]) ??
      "Untitled finding",
    description: pickString(record, ["description"]),
    detectorId: pickString(record, [
      "detector_id",
      "detectorId",
      "rule_id",
      "ruleId",
    ]),
    source: pickString(record, ["source"]) ?? "rule",
    detectorVersion: pickString(record, [
      "detector_version",
      "detectorVersion",
      "rule_version",
    ]),
    functionSignature:
      pickString(record, [
        "function_signature",
        "functionSignature",
        "function",
        "signature",
      ]) ??
      pickString(evidenceRecord, [
        "function_signature",
        "functionSignature",
        "function",
        "signature",
      ]),
    byteOffsets,
    fileRef:
      pickString(record, [
        "file_ref",
        "fileRef",
        "location",
        "source_ref",
        "file",
      ]) ??
      pickString(evidenceRecord, ["file_ref", "fileRef", "location", "source_ref"]),
    createdAt: toIsoString(record, [
      "created_at",
      "createdAt",
      "first_seen_at",
      "detected_at",
    ]),
    evidence: signals,
    edgeCounts,
    limitations: pickString(record, ["limitations", "caveats"]),
    reproductionStatus: pickString(record, [
      "reproduction_status",
      "reproductionStatus",
      "repro_status",
    ]),
    experimental: pickBoolean(record, [
      "experimental",
      "is_experimental",
      "ml_based",
    ]),
  };
}

function normaliseCreatedScan(value: unknown): CreatedScan {
  const record = asRecord(value);
  return {
    id: pickString(record, ["id", "scan_id", "scanId"]) ?? "unknown",
    status: toScanStatus(record["status"]),
    statusUrl: pickString(record, ["status_url", "statusUrl", "url"]),
  };
}

/** Exported for tests: normalise raw backend payloads into the taxonomy. */
export const __testing = {
  normaliseFinding,
  normaliseScanSummary,
  normaliseScanDetail,
  normaliseArtifacts,
  normaliseStages,
  normaliseCorrespondence,
  countSeverities,
  toSeverity,
};