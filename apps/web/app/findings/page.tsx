import { ApiUnreachable } from "@/components/ApiUnreachable";
import { EmptyState } from "@/components/EmptyState";
import { FindingTable } from "@/components/FindingTable";
import {
  API_BASE_URL,
  describeApiError,
  getFindingsSummary,
  getGuidanceMap,
  listFindings,
} from "@/lib/api";
import { toSeverity } from "@/lib/severity";
import { SEVERITY_ORDER, type Severity } from "@/lib/types";

export const dynamic = "force-dynamic";

export const metadata = { title: "Findings" };

export default async function FindingsPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = await searchParams;
  const rawSeverity = Array.isArray(params.severity) ? params.severity[0] : params.severity;
  // The severity filter is enforced server-side by the API; the table keeps a
  // client-side copy so the operator can narrow further without a round trip.
  const severity: Severity | null =
    rawSeverity && (SEVERITY_ORDER as readonly string[]).includes(rawSeverity)
      ? toSeverity(rawSeverity)
      : null;

  // The detector and chain filters come from the URL, so a breakdown on the
  // overview page links straight to the findings it describes.
  const rawDetector = Array.isArray(params.detector) ? params.detector[0] : params.detector;
  const rawChain = Array.isArray(params.chain) ? params.chain[0] : params.chain;
  const detector = rawDetector?.trim() ? rawDetector : undefined;
  const parsedChain = rawChain ? Number(rawChain) : Number.NaN;
  const chainId = Number.isFinite(parsedChain) ? parsedChain : undefined;

  const [result, guidanceResult, summaryResult] = await Promise.all([
    listFindings({
      severity: severity ?? undefined,
      detectorId: detector,
      chainId,
      limit: 200,
    }),
    getGuidanceMap(),
    getFindingsSummary(),
  ]);
  const summary = summaryResult.ok ? summaryResult.data : null;
  // The guidance is fetched on the server, so every finding arrives with
  // the explanation of what to do about it.
  const guidance = guidanceResult.ok ? guidanceResult.data : {};

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold text-[var(--cs-fg)]">Findings</h1>
        <p className="mt-1 text-sm text-[var(--cs-muted)]">
          Candidate findings across every scan. Severity and confidence are separate signals: a
          high score does not mean a confirmed vulnerability.
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
          title="No candidate findings"
          description="Findings appear here once a scan completes its rules analysis."
          action={{ label: "Queue a scan", href: "/scans/new" }}
        />
      ) : (
        <div className="space-y-2">
          <p className="text-xs text-[var(--cs-muted)]">
            {result.data.total} finding{result.data.total === 1 ? "" : "s"} in total
            {severity ? `, filtered to ${severity} severity` : ""}
            {detector ? `, from ${detector}` : ""}
            {chainId !== undefined ? `, on chain ${chainId}` : ""}.
          </p>
          {summary && (summary.byDetector.length > 0 || summary.byChain.length > 0) ? (
            <form
              method="get"
              className="flex flex-wrap items-end gap-3 rounded-lg border border-[var(--cs-border)] bg-[var(--cs-surface)] p-3"
            >
              {severity ? <input type="hidden" name="severity" value={severity} /> : null}
              <div className="space-y-1">
                <label
                  htmlFor="detector-filter"
                  className="block text-xs font-medium text-[var(--cs-muted)]"
                >
                  Detector
                </label>
                <select
                  id="detector-filter"
                  name="detector"
                  defaultValue={detector ?? ""}
                  className="rounded-md border border-[var(--cs-border)] bg-[var(--cs-bg)] px-2 py-1 text-sm text-[var(--cs-fg)]"
                >
                  <option value="">Every detector</option>
                  {summary.byDetector.map((row) => (
                    <option key={row.detectorId} value={row.detectorId}>
                      {row.detectorId} ({row.count})
                    </option>
                  ))}
                </select>
              </div>
              <div className="space-y-1">
                <label
                  htmlFor="chain-filter"
                  className="block text-xs font-medium text-[var(--cs-muted)]"
                >
                  Chain
                </label>
                <select
                  id="chain-filter"
                  name="chain"
                  defaultValue={chainId !== undefined ? String(chainId) : ""}
                  className="rounded-md border border-[var(--cs-border)] bg-[var(--cs-bg)] px-2 py-1 text-sm text-[var(--cs-fg)]"
                >
                  <option value="">Every chain</option>
                  {summary.byChain.map((row) => (
                    <option key={row.chainId} value={row.chainId}>
                      {row.chainName} ({row.count})
                    </option>
                  ))}
                </select>
              </div>
              <button
                type="submit"
                className="rounded-md border border-[var(--cs-border)] px-3 py-1 text-sm text-[var(--cs-fg)] hover:border-[var(--cs-accent)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--cs-accent)]"
              >
                Narrow the list
              </button>
            </form>
          ) : null}
          <FindingTable findings={result.data.items} guidance={guidance} caption="All findings" />
        </div>
      )}
    </div>
  );
}