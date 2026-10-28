import Link from "next/link";
import { formatChainId, formatDateTime, formatDuration, shortAddress } from "@/lib/format";
import { SeverityBadge } from "./SeverityBadge";
import { StatusBadge } from "./StatusBadge";
import type { ScanSummary } from "@/lib/types";

export interface ScanTableProps {
  scans: readonly ScanSummary[];
  caption?: string;
}

/** Recent scans table (design document page 6). */
export function ScanTable({ scans, caption = "Scans" }: ScanTableProps) {
  return (
    <div className="overflow-x-auto rounded-lg border border-[var(--cs-border)]">
      <table className="w-full border-collapse text-left text-sm">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr className="border-b border-[var(--cs-border)] bg-[var(--cs-raised)] text-xs uppercase tracking-wide text-[var(--cs-muted)]">
            <th scope="col" className="px-3 py-2 font-medium">Scan</th>
            <th scope="col" className="px-3 py-2 font-medium">Contract</th>
            <th scope="col" className="px-3 py-2 font-medium">Chain</th>
            <th scope="col" className="px-3 py-2 font-medium">Status</th>
            <th scope="col" className="px-3 py-2 font-medium">Findings</th>
            <th scope="col" className="px-3 py-2 font-medium">Created</th>
            <th scope="col" className="px-3 py-2 font-medium">Duration</th>
          </tr>
        </thead>
        <tbody>
          {scans.map((scan) => (
            <tr
              key={scan.id}
              className="border-b border-[var(--cs-border)] last:border-0 hover:bg-[var(--cs-raised)]"
            >
              <th scope="row" className="px-3 py-2 font-mono text-xs font-normal">
                <Link
                  href={`/scans/${encodeURIComponent(scan.id)}`}
                  className="underline decoration-dotted underline-offset-2 hover:text-[var(--cs-accent)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--cs-accent)]"
                >
                  {scan.id}
                </Link>
              </th>
              <td className="px-3 py-2 font-mono text-xs">{shortAddress(scan.contractAddress)}</td>
              <td className="px-3 py-2 text-xs">{formatChainId(scan.chainId)}</td>
              <td className="px-3 py-2">
                <StatusBadge status={scan.status} size="sm" />
              </td>
              <td className="px-3 py-2">
                <span className="flex flex-wrap items-center gap-1">
                  <SeverityBadge severity="critical" count={scan.findingCounts.critical} size="sm" />
                  <SeverityBadge severity="high" count={scan.findingCounts.high} size="sm" />
                  <span className="font-mono text-xs text-[var(--cs-muted)]">
                    {scan.totalFindings} total
                  </span>
                </span>
              </td>
              <td className="px-3 py-2 text-xs">{formatDateTime(scan.createdAt)}</td>
              <td className="px-3 py-2 font-mono text-xs">{formatDuration(scan.durationMs)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
