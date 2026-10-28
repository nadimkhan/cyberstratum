"use client";

import { useMemo, useState } from "react";
import { SEVERITY_LABELS } from "@/lib/severity";
import { formatConfidence, formatDateTime, shortAddress } from "@/lib/format";
import { SEVERITY_ORDER, type Finding, type Severity } from "@/lib/types";
import { SeverityBadge } from "./SeverityBadge";
import { ReviewStatusBadge } from "./StatusBadge";

export interface FindingTableProps {
  findings: readonly Finding[];
  /** Hide the severity/confidence filter bar (used on the scan detail page). */
  showFilters?: boolean;
  caption?: string;
}

type SortKey = "severity" | "confidence" | "createdAt" | "title";

const SEVERITY_RANK: Record<Severity, number> = {
  critical: 0,
  high: 1,
  medium: 2,
  low: 3,
  info: 4,
};

/** Sortable, filterable findings table (design document page 8). */
export function FindingTable({ findings, showFilters = true, caption = "Findings" }: FindingTableProps) {
  const [severity, setSeverity] = useState<Severity | "all">("all");
  const [minConfidence, setMinConfidence] = useState(0);
  const [sortKey, setSortKey] = useState<SortKey>("severity");
  const [ascending, setAscending] = useState(false);

  const visible = useMemo(() => {
    const filtered = findings.filter((finding) => {
      if (severity !== "all" && finding.severity !== severity) return false;
      if (minConfidence > 0) {
        const confidence = finding.confidence ?? 0;
        if (confidence < minConfidence) return false;
      }
      return true;
    });

    const sorted = [...filtered];
    sorted.sort((a, b) => {
      let result = 0;
      switch (sortKey) {
        case "severity":
          result = SEVERITY_RANK[a.severity] - SEVERITY_RANK[b.severity];
          break;
        case "confidence":
          result = (a.confidence ?? -1) - (b.confidence ?? -1);
          break;
        case "createdAt":
          result =
            new Date(a.createdAt ?? 0).getTime() - new Date(b.createdAt ?? 0).getTime();
          break;
        case "title":
          result = a.title.localeCompare(b.title);
          break;
      }
      return ascending ? result : -result;
    });
    return sorted;
  }, [findings, severity, minConfidence, sortKey, ascending]);

  function toggleSort(key: SortKey) {
    if (key === sortKey) {
      setAscending((value) => !value);
    } else {
      setSortKey(key);
      setAscending(key === "title" || key === "createdAt");
    }
  }

  function sortIndicator(key: SortKey) {
    if (key !== sortKey) return "";
    return ascending ? " ▲" : " ▼";
  }

  return (
    <div className="space-y-3">
      {showFilters ? (
        <div className="flex flex-wrap items-end gap-4 rounded-lg border border-[var(--cs-border)] bg-[var(--cs-surface)] p-3">
          <div className="flex flex-col gap-1">
            <label
              htmlFor="finding-severity"
              className="text-xs font-medium text-[var(--cs-muted)]"
            >
              Severity
            </label>
            <select
              id="finding-severity"
              value={severity}
              onChange={(event) =>
                setSeverity(event.target.value as Severity | "all")
              }
              className="rounded-md border border-[var(--cs-border)] bg-[var(--cs-raised)] px-2 py-1.5 text-sm text-[var(--cs-fg)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--cs-accent)]"
            >
              <option value="all">All severities</option>
              {SEVERITY_LABELS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>

          <div className="flex flex-col gap-1">
            <label
              htmlFor="finding-confidence"
              className="text-xs font-medium text-[var(--cs-muted)]"
            >
              Minimum confidence: {Math.round(minConfidence * 100)}%
            </label>
            <input
              id="finding-confidence"
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={minConfidence}
              onChange={(event) => setMinConfidence(Number(event.target.value))}
              className="w-44 accent-[var(--cs-accent)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--cs-accent)]"
            />
          </div>

          <p className="ml-auto text-xs text-[var(--cs-muted)]" aria-live="polite">
            Showing {visible.length} of {findings.length} findings
          </p>
        </div>
      ) : null}

      <div className="overflow-x-auto rounded-lg border border-[var(--cs-border)]">
        <table className="w-full border-collapse text-left text-sm">
          <caption className="sr-only">{caption}</caption>
          <thead>
            <tr className="border-b border-[var(--cs-border)] bg-[var(--cs-raised)] text-xs uppercase tracking-wide text-[var(--cs-muted)]">
              <th scope="col" className="px-3 py-2 font-medium">
                <button
                  type="button"
                  onClick={() => toggleSort("severity")}
                  className="rounded focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--cs-accent)]"
                >
                  Severity{sortIndicator("severity")}
                </button>
              </th>
              <th scope="col" className="px-3 py-2 font-medium">
                <button
                  type="button"
                  onClick={() => toggleSort("title")}
                  className="rounded focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--cs-accent)]"
                >
                  Finding{sortIndicator("title")}
                </button>
              </th>
              <th scope="col" className="px-3 py-2 font-medium">
                <button
                  type="button"
                  onClick={() => toggleSort("confidence")}
                  className="rounded focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--cs-accent)]"
                >
                  Confidence{sortIndicator("confidence")}
                </button>
              </th>
              <th scope="col" className="px-3 py-2 font-medium">Detector</th>
              <th scope="col" className="px-3 py-2 font-medium">Function</th>
              <th scope="col" className="px-3 py-2 font-medium">Location</th>
              <th scope="col" className="px-3 py-2 font-medium">Review</th>
              <th scope="col" className="px-3 py-2 font-medium">
                <button
                  type="button"
                  onClick={() => toggleSort("createdAt")}
                  className="rounded focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--cs-accent)]"
                >
                  First seen{sortIndicator("createdAt")}
                </button>
              </th>
            </tr>
          </thead>
          <tbody>
            {visible.map((finding) => (
              <tr
                key={finding.id}
                className="border-b border-[var(--cs-border)] last:border-0 hover:bg-[var(--cs-raised)]"
              >
                <td className="px-3 py-2 align-top">
                  <SeverityBadge severity={finding.severity} size="sm" />
                </td>
                <th scope="row" className="px-3 py-2 align-top font-normal">
                  <span className="block font-medium text-[var(--cs-fg)]">{finding.title}</span>
                  <span className="block text-xs text-[var(--cs-muted)]">{finding.category}</span>
                  {finding.experimental ? (
                    <span className="mt-1 inline-block rounded bg-[var(--cs-raised)] px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-[var(--cs-muted)]">
                      experimental
                    </span>
                  ) : null}
                </th>
                <td className="px-3 py-2 align-top font-mono text-xs">
                  {formatConfidence(finding.confidence)}
                </td>
                <td className="px-3 py-2 align-top font-mono text-xs">
                  <EngineBadge source={finding.source} />
                  <span className="mt-0.5 block">{finding.detectorId ?? "—"}</span>
                  {finding.detectorVersion ? (
                    <span className="block text-[var(--cs-muted)]">v{finding.detectorVersion}</span>
                  ) : null}
                </td>
                <td className="px-3 py-2 align-top font-mono text-xs">
                  {finding.functionSignature ?? "—"}
                </td>
                <td className="px-3 py-2 align-top font-mono text-xs">
                  {finding.fileRef ? (
                    <span className="block">{finding.fileRef}</span>
                  ) : null}
                  {finding.byteOffsets.length > 0 ? (
                    <span className="block text-[var(--cs-muted)]">
                      offset {finding.byteOffsets.slice(0, 3).join(", ")}
                      {finding.byteOffsets.length > 3 ? "…" : ""}
                    </span>
                  ) : null}
                  {finding.byteOffsets.length === 0 && !finding.fileRef ? (
                    <span className="text-[var(--cs-muted)]">—</span>
                  ) : null}
                </td>
                <td className="px-3 py-2 align-top">
                  <ReviewStatusBadge status={finding.reviewStatus} size="sm" />
                  <span className="mt-1 block font-mono text-[10px] text-[var(--cs-muted)]">
                    {shortAddress(finding.contractAddress)}
                  </span>
                </td>
                <td className="px-3 py-2 align-top text-xs">
                  {formatDateTime(finding.createdAt)}
                </td>
              </tr>
            ))}
            {visible.length === 0 ? (
              <tr>
                <td colSpan={8} className="px-3 py-6 text-center text-sm text-[var(--cs-muted)]">
                  No findings match the current filters.
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export { SEVERITY_ORDER };

const ENGINE_LABELS: Record<string, string> = {
  rule: "bytecode",
  slither: "source",
  ml: "model",
};

const ENGINE_TITLES: Record<string, string> = {
  rule: "Found by the bytecode engine",
  slither: "Found by the source engine (Slither)",
  ml: "Found by the machine-learning model",
};

/**
 * Shows which engine produced a finding.
 *
 * The bytecode engine and the source engine are complementary: the first
 * sees the deployed runtime, the second sees the verified source. A
 * reader needs to know which one spoke.
 */
export function EngineBadge({ source }: { source: string }) {
  const label = ENGINE_LABELS[source] ?? source;
  const title = ENGINE_TITLES[source] ?? `Found by the ${source} engine`;
  return (
    <span
      title={title}
      className="inline-block rounded bg-[var(--cs-raised)] px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-[var(--cs-muted)]"
    >
      {label}
    </span>
  );
}
