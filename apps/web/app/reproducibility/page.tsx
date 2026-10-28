import Link from "next/link";
import { ApiUnreachable } from "@/components/ApiUnreachable";
import { EmptyState } from "@/components/EmptyState";
import { API_BASE_URL, describeApiError, listScans } from "@/lib/api";
import { formatChainId, formatDateTime, shortAddress } from "@/lib/format";

export const dynamic = "force-dynamic";

export const metadata = { title: "Reproducibility" };

export default async function ReproducibilityPage() {
  const result = await listScans({ limit: 200 });

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold text-[var(--cs-fg)]">Reproducibility</h1>
        <p className="mt-1 text-sm text-[var(--cs-muted)]">
          Pinned versions for every scan, so a result can be re-run and compared byte for byte.
        </p>
      </header>

      {!result.ok ? (
        <ApiUnreachable
          title={describeApiError(result.error).title}
          message={describeApiError(result.error).message}
          detail={result.error.detail ?? undefined}
          baseUrl={API_BASE_URL}
        />
      ) : result.data.items.length === 0 ? (
        <EmptyState
          title="Nothing to reproduce yet"
          description="Queue a scan to record tool versions, the opcode table version and the bytecode hash."
          action={{ label: "Queue a scan", href: "/scans/new" }}
        />
      ) : (
        <div className="overflow-x-auto rounded-lg border border-[var(--cs-border)]">
          <table className="w-full border-collapse text-left text-sm">
            <caption className="sr-only">Scans with their pinned analysis versions</caption>
            <thead>
              <tr className="border-b border-[var(--cs-border)] bg-[var(--cs-raised)] text-xs uppercase tracking-wide text-[var(--cs-muted)]">
                <th scope="col" className="px-3 py-2 font-medium">Scan</th>
                <th scope="col" className="px-3 py-2 font-medium">Contract</th>
                <th scope="col" className="px-3 py-2 font-medium">Chain</th>
                <th scope="col" className="px-3 py-2 font-medium">Fork</th>
                <th scope="col" className="px-3 py-2 font-medium">Parser</th>
                <th scope="col" className="px-3 py-2 font-medium">Ruleset</th>
                <th scope="col" className="px-3 py-2 font-medium">Created</th>
              </tr>
            </thead>
            <tbody>
              {result.data.items.map((scan) => (
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
                  <td className="px-3 py-2 font-mono text-xs">{scan.fork ?? "—"}</td>
                  <td className="px-3 py-2 font-mono text-xs">{scan.parserVersion ?? "—"}</td>
                  <td className="px-3 py-2 font-mono text-xs">{scan.rulesetVersion ?? "—"}</td>
                  <td className="px-3 py-2 text-xs">{formatDateTime(scan.createdAt)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}