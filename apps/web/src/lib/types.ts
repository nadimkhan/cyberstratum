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

/**
 * Outcome of a source-to-bytecode correspondence check.
 *
 * `mismatch` means the published source genuinely does not describe the
 * deployed contract. `unavailable` means the check could not be performed at
 * all - the compiler hung, crashed, was missing, or emitted non-JSON. The
 * two are kept apart on purpose: a tooling failure must never be reported as
 * evidence against a contract.
 */
export const CORRESPONDENCE_STATUSES = [
  "established",
  "skipped",
  "mismatch",
  "unavailable",
] as const;
export type CorrespondenceStatus = (typeof CORRESPONDENCE_STATUSES)[number];

/**
 * The stored evidence that a contract's published source compiles to its
 * deployed bytecode.
 *
 * This is the only thing that licenses the product to print an exact source
 * path and line against a finding. Without one, a finding is bytecode-only.
 */
export interface CorrespondenceProof {
  scanId: string;
  status: CorrespondenceStatus;
  /** Why the check did not run, when it did not. */
  skipped: string | null;
  compilerVersion: string | null;
  sourcePath: string | null;
  runtimeSha256: string | null;
  executableSha256: string | null;
  metadataSha256: string | null;
  runtimeByteSize: number | null;
  executableByteSize: number | null;
  instructionCount: number | null;
  mappedInstructionCount: number | null;
}

/** The response from requesting an on-demand Mythril deep analysis. */
export interface MythrilRunRequest {
  scanId: string;
  jobId: string | null;
  status: string;
  queue: string | null;
  message: string | null;
}

/**
 * The result of asking for an on-demand correspondence proof.
 *
 * `status` is `queued` and nothing more. A source line may only be claimed
 * once a proof with the `established` status exists, so this response never
 * licenses a source claim.
 */
export interface CorrespondenceRunRequest {
  scanId: string;
  jobId: string | null;
  status: string;
  queue: string | null;
  message: string | null;
}

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
  /** The model's per-category scores, when a model was applied. */
  modelScores: ScanModelScores;
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
  /**
   * Whether the Mythril engine ran for this scan. Mythril is manual-only, so
   * this is normally false - and a false value means "not run", never
   * "nothing found".
   */
  mythrilRan: boolean;
  /** Why Mythril did not run, when it did not. */
  mythrilSkipped: string | null;
  error: string | null;
}

/**
 * How much of the contract a scan actually reached.
 *
 * This is a measurement rather than a verdict: the counts say how
 * much was decoded and how far the static view travelled, so the
 * findings can be weighed against what was read.
 */
export interface ScanCoverage {
  /** Control-flow jumps the static view could follow to a target. */
  resolvedJumps: number | null;
  /** Control-flow jumps whose target is computed at run time. */
  unresolvedJumps: number | null;
  /** Instructions the disassembler decoded. */
  instructions: number | null;
  /** Bytes of executable code that were analysed. */
  executableBytes: number | null;
  /** Bytes of non-executable metadata that were set aside. */
  metadataBytes: number | null;
  /** Control-flow edges the static view followed. */
  edges: number | null;
  /** Notes taken while measuring coverage. */
  notes: string[];
}

/**
 * The installed model's per-category scores for a scan.
 *
 * These are ranking aids, not verdicts: the model says where to
 * look first, and the reviewer still decides what is true.
 */
export type ScanModelScores = Record<string, number> | null;

export interface ScanDetail extends ScanSummary {
  stages: ScanStage[];
  artifacts: Artifact[];
  findings: Finding[];
  jobs: ScanJobInfo[];
  reproducibility: Reproducibility;
  warnings: string[];
  coverage: ScanCoverage | null;
  /** The stored source-to-bytecode correspondence proof, when one exists. */
  correspondence: CorrespondenceProof | null;
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
  /** Who made the review verdict, when one has been made. */
  reviewedBy: string | null;
  /** When the review verdict was made. */
  reviewedAt: string | null;
  /** Why the verdict was made. A false-positive verdict always has one. */
  reviewNote: string | null;
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
/**
 * What a detector's finding means, and what to do about it.
 *
 * The guidance is the half of a finding that a reviewer acts on: the
 * pattern, the risk, the change, and -- the part that saves an
 * afternoon -- the circumstances in which the pattern is expected.
 */
export interface Guidance {
  detectorId: string;
  title: string;
  whatItMeans: string;
  whyItMatters: string;
  howToFix: string;
  falsePositivePatterns: string;
  references: string;
  defaultSeverity: Severity;
  version: string;
}

/** One workspace and how much of it is still waiting to be reviewed. */
export interface WorkspaceSummary {
  id: string;
  name: string;
  slug: string;
  openFindings: number;
}
