/** Canonical domain types for the CyberStratum web UI.
 *
 * The FastAPI backend is the source of truth; these types are the normalised
 * shape the UI consumes. `src/lib/api.ts` is responsible for mapping whatever
 * the backend returns (snake_case / camelCase, bare arrays or `{data: []}`
 * envelopes) into these structures.
 */

/** Severity taxonomy. Order is significant: most severe first. */
export const SEVERITY_ORDER = ["critical", "high", "medium", "low", "info"] as const;
export type Severity = (typeof SEVERITY_ORDER)[number];

/** Canonical scan lifecycle states. */
export const SCAN_STATUSES = [
  "queued",
  "running",
  "completed",
  "partial",
  "failed",
  "cancelled",
] as const;
export type ScanStatus = (typeof SCAN_STATUSES)[number];

/** Analyst triage state for a candidate finding. */
export const REVIEW_STATUSES = [
  "new",
  "triage",
  "confirmed",
  "false_positive",
  "needs_evidence",
] as const;
export type ReviewStatus = (typeof REVIEW_STATUSES)[number];

/** Pipeline stage state. */
export type StageStatus = "pending" | "running" | "completed" | "failed" | "skipped";

export interface ScanStage {
  key: string;
  label: string;
  status: StageStatus;
  startedAt: string | null;
  endedAt: string | null;
  durationMs: number | null;
  version: string | null;
  message: string | null;
}

export interface Artifact {
  id: string;
  name: string;
  kind: string;
  contentType: string | null;
  sizeBytes: number | null;
  /** Absolute URL when the artifact is downloadable, otherwise null. */
  uri: string | null;
  /** Storage key of the artifact inside the object store. */
  objectKey: string | null;
  sha256: string | null;
  createdAt: string | null;
}

/** A queue job backing a scan. */
export interface ScanJobInfo {
  id: string;
  jobType: string;
  queueName: string | null;
  status: string;
  attempt: number | null;
  startedAt: string | null;
  finishedAt: string | null;
  durationMs: number | null;
}

export interface ToolVersion {
  name: string;
  version: string;
}

export interface Reproducibility {
  toolVersions: ToolVersion[];
  opcodeTableVersion: string | null;
  bytecodeHash: string | null;
  rulesetVersion: string | null;
  modelVersion: string | null;
  featureSchemaVersion: string | null;
  environment: Record<string, string>;
}

export interface SeverityCounts {
  critical: number;
  high: number;
  medium: number;
  low: number;
  info: number;
}

export interface ScanSummary {
  id: string;
  contractAddress: string;
  targetId: string | null;
  chainId: number | null;
  fork: string | null;
  bytecodeSource: string | null;
  status: ScanStatus;
  createdAt: string | null;
  startedAt: string | null;
  completedAt: string | null;
  durationMs: number | null;
  riskScore: number | null;
  findingCounts: SeverityCounts;
  totalFindings: number;
  requestedBy: string | null;
  labels: string[];
  parserVersion: string | null;
  rulesetVersion: string | null;
  modelVersion: string | null;
  /** Whether the source engine audited this contract's verified source. */
  sourceAudited: boolean;
  /** Why the source engine did not run, when it did not. */
  sourceAuditSkipped: string | null;
  error: string | null;
}

export interface ScanDetail extends ScanSummary {
  stages: ScanStage[];
  artifacts: Artifact[];
  findings: Finding[];
  jobs: ScanJobInfo[];
  reproducibility: Reproducibility;
  warnings: string[];
  coverage: { resolvedJumps: number | null; unresolvedJumps: number | null } | null;
}

export interface Finding {
  id: string;
  scanId: string | null;
  contractAddress: string;
  chainId: number | null;
  severity: Severity;
  confidence: number | null;
  reviewStatus: ReviewStatus;
  category: string;
  title: string;
  description: string | null;
  detectorId: string | null;
  detectorVersion: string | null;
  /** Which engine produced the finding: "rule", "slither" or "ml". */
  source: string;
  functionSignature: string | null;
  byteOffsets: number[];
  fileRef: string | null;
  createdAt: string | null;
  evidence: string[];
  edgeCounts: Record<string, number>;
  limitations: string | null;
  reproductionStatus: string | null;
  experimental: boolean;
}

export interface CreateScanInput {
  contractAddress: string;
  chainId: number;
  fork: string;
  labels?: string[];
  bytecodeHex?: string;
  enableExperimentalMl?: boolean;
}

export interface CreatedScan {
  id: string;
  status: ScanStatus;
  statusUrl: string | null;
}
