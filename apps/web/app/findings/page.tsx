import { ApiUnreachable } from "@/components/ApiUnreachable";
import { EmptyState } from "@/components/EmptyState";
import { FindingTable } from "@/components/FindingTable";
import { API_BASE_URL, describeApiError, listFindings } from "@/lib/api";
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

  const result = await listFindings({
    severity: severity ?? undefined,
    limit: 200,
  });

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
            {severity ? `, filtered to ${severity} severity` : ""}.
          </p>
          <FindingTable findings={result.data.items} caption="All findings" />
        </div>
      )}
    </div>
  );
}