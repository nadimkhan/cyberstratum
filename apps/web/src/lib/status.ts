import type { ScanStatus, ReviewStatus, StageStatus } from "./types";

/** The single place where scan status colour is defined. */
export interface StatusMeta {
  label: string;
  badge: string;
  dot: string;
}

export const SCAN_STATUS_META: Record<ScanStatus, StatusMeta> = {
  queued: {
    label: "Queued",
    badge: "bg-slate-100 text-slate-800 ring-slate-600/40 dark:bg-slate-500/20 dark:text-slate-100",
    dot: "bg-slate-500",
  },
  running: {
    label: "Running",
    badge: "bg-blue-100 text-blue-900 ring-blue-700/40 dark:bg-blue-500/20 dark:text-blue-100",
    dot: "bg-blue-500",
  },
  completed: {
    label: "Completed",
    badge: "bg-emerald-100 text-emerald-900 ring-emerald-700/40 dark:bg-emerald-500/20 dark:text-emerald-100",
    dot: "bg-emerald-600",
  },
  partial: {
    label: "Partial",
    badge: "bg-violet-100 text-violet-900 ring-violet-700/40 dark:bg-violet-500/20 dark:text-violet-100",
    dot: "bg-violet-600",
  },
  failed: {
    label: "Failed",
    badge: "bg-rose-100 text-rose-900 ring-rose-700/40 dark:bg-rose-500/20 dark:text-rose-100",
    dot: "bg-rose-600",
  },
  cancelled: {
    label: "Cancelled",
    badge: "bg-zinc-200 text-zinc-800 ring-zinc-600/40 dark:bg-zinc-500/25 dark:text-zinc-100",
    dot: "bg-zinc-500",
  },
};

export const REVIEW_STATUS_META: Record<ReviewStatus, { label: string; badge: string }> = {
  new: {
    label: "New",
    badge: "bg-slate-100 text-slate-800 ring-slate-600/40 dark:bg-slate-500/20 dark:text-slate-100",
  },
  triage: {
    label: "In triage",
    badge: "bg-blue-100 text-blue-900 ring-blue-700/40 dark:bg-blue-500/20 dark:text-blue-100",
  },
  confirmed: {
    label: "Confirmed",
    badge: "bg-emerald-100 text-emerald-900 ring-emerald-700/40 dark:bg-emerald-500/20 dark:text-emerald-100",
  },
  false_positive: {
    label: "False positive",
    badge: "bg-slate-200 text-slate-800 ring-slate-600/40 dark:bg-slate-500/25 dark:text-slate-100",
  },
  needs_evidence: {
    label: "Needs evidence",
    badge: "bg-teal-100 text-teal-900 ring-teal-700/40 dark:bg-teal-500/20 dark:text-teal-100",
  },
};

export const STAGE_STATUS_META: Record<StageStatus, { label: string; badge: string; dot: string }> = {
  pending: {
    label: "Pending",
    badge: "bg-slate-100 text-slate-700 ring-slate-600/30 dark:bg-slate-500/20 dark:text-slate-200",
    dot: "bg-slate-400",
  },
  running: {
    label: "Running",
    badge: "bg-blue-100 text-blue-900 ring-blue-700/30 dark:bg-blue-500/20 dark:text-blue-100",
    dot: "bg-blue-500",
  },
  completed: {
    label: "Completed",
    badge: "bg-emerald-100 text-emerald-900 ring-emerald-700/30 dark:bg-emerald-500/20 dark:text-emerald-100",
    dot: "bg-emerald-600",
  },
  failed: {
    label: "Failed",
    badge: "bg-rose-100 text-rose-900 ring-rose-700/30 dark:bg-rose-500/20 dark:text-rose-100",
    dot: "bg-rose-600",
  },
  skipped: {
    label: "Skipped",
    badge: "bg-zinc-100 text-zinc-700 ring-zinc-600/30 dark:bg-zinc-500/20 dark:text-zinc-200",
    dot: "bg-zinc-400",
  },
};

const SCAN_STATUS_ALIASES: Record<string, ScanStatus> = {
  queued: "queued",
  pending: "queued",
  created: "queued",
  scheduled: "queued",
  validating: "running",
  fetching_bytecode: "running",
  fetching: "running",
  disassembling: "running",
  disassembly: "running",
  building_cfg: "running",
  building_graph: "running",
  extracting_features: "running",
  running_detectors: "running",
  running_rules: "running",
  feature_extraction: "running",
  rules_analysis: "running",
  rules: "running",
  ml_inference: "running",
  normalising: "running",
  normalizing: "running",
  normalising_results: "running",
  normalizing_results: "running",
  running: "running",
  in_progress: "running",
  processing: "running",
  completed: "completed",
  complete: "completed",
  succeeded: "completed",
  success: "completed",
  done: "completed",
  partial: "partial",
  partial_success: "partial",
  failed: "failed",
  failure: "failed",
  error: "failed",
  cancelled: "cancelled",
  canceled: "cancelled",
  aborted: "cancelled",
};

export function toScanStatus(value: unknown): ScanStatus {
  if (typeof value !== "string") return "queued";
  const key = value.trim().toLowerCase().replace(/[\s-]+/g, "_");
  return SCAN_STATUS_ALIASES[key] ?? "queued";
}

const REVIEW_STATUS_ALIASES: Record<string, ReviewStatus> = {
  new: "new",
  open: "new",
  unreviewed: "new",
  triage: "triage",
  in_triage: "triage",
  in_review: "triage",
  confirmed: "confirmed",
  validated: "confirmed",
  true_positive: "confirmed",
  false_positive: "false_positive",
  falsepositive: "false_positive",
  rejected: "false_positive",
  needs_evidence: "needs_evidence",
  needs_more_evidence: "needs_evidence",
  needs_more_evidence_review: "needs_evidence",
  needs_evidence_review: "needs_evidence",
};

export function toReviewStatus(value: unknown): ReviewStatus {
  if (typeof value !== "string") return "new";
  const key = value.trim().toLowerCase().replace(/[\s-]+/g, "_");
  return REVIEW_STATUS_ALIASES[key] ?? "new";
}

export function toStageStatus(value: unknown): StageStatus {
  if (typeof value !== "string") return "pending";
  const key = value.trim().toLowerCase();
  if (key === "running" || key === "in_progress" || key === "active") return "running";
  if (key === "completed" || key === "complete" || key === "succeeded" || key === "success") {
    return "completed";
  }
  if (key === "failed" || key === "failure" || key === "error") return "failed";
  if (key === "skipped" || key === "not_applicable") return "skipped";
  return "pending";
}