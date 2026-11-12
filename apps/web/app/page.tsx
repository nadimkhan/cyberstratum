import Link from "next/link";
import { ApiUnreachable } from "@/components/ApiUnreachable";
import { EmptyState } from "@/components/EmptyState";
import { RiskScoreGauge } from "@/components/RiskScoreGauge";
import { ScanTable } from "@/components/ScanTable";
import { SeverityBadge } from "@/components/SeverityBadge";
import { SignInButton } from "@/components/SignInButton";
import {
  API_BASE_URL,
  describeApiError,
  getFindingsSummary,
  listScans,
} from "@/lib/api";
import { fetchCurrentUser } from "@/lib/auth";
import { formatChainId, formatRelativeTime, shortAddress } from "@/lib/format";
import { emptySeverityCounts, estimateRiskScore, SEVERITY_META } from "@/lib/severity";
import { SEVERITY_ORDER, type SeverityCounts } from "@/lib/types";

export const dynamic = "force-dynamic";

export const metadata = { title: "Overview" };

export default async function DashboardPage({
  searchParams,
}: {
  searchParams: Promise<{ auth?: string }>;
}) {
  const [scansResult, summaryResult, session, params] = await Promise.all([
    listScans({ limit: 50 }),
    getFindingsSummary(),
    fetchCurrentUser(),
    searchParams,
  ]);

  const backendDown = !scansResult.ok && !summaryResult.ok;
  const scans = scansResult.ok ? scansResult.data.items : [];
  const totalScans = scansResult.ok ? scansResult.data.total : 0;

  const severityCounts: SeverityCounts = summaryResult.ok
    ? summaryResult.data.bySeverity
    : emptySeverityCounts();
  const totalFindings = summaryResult.ok ? summaryResult.data.total : 0;

  const awaitingTriage = summaryResult.ok
    ? (summaryResult.data.byStatus["new"] ?? 0) +
      (summaryResult.data.byStatus["triage"] ?? 0)
    : 0;

  // The summary names which detectors fire and which chains they fire on.
  // Both breakdowns link into the findings list with the filter already
  // applied, so the overview is a way into the work and not a dead end.
  const summary = summaryResult.ok ? summaryResult.data : null;
  const topDetectors = summary ? summary.byDetector.slice(0, 8) : [];
  const topChains = summary ? summary.byChain.slice(0, 8) : [];

  const scoredScans = scans.filter((scan) => scan.totalFindings > 0);
  const averageRiskScore =
    scoredScans.length > 0
      ? scoredScans.reduce((sum, scan) => {
          const score = scan.riskScore ?? estimateRiskScore(scan.findingCounts);
          return sum + score;
        }, 0) / scoredScans.length
      : null;

  const needsAttention = scans.filter(
    (scan) => scan.status === "failed" || scan.status === "partial",
  );

  return (
    <div className="space-y-8">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-[var(--cs-fg)]">Overview</h1>
          <p className="mt-1 text-sm text-[var(--cs-muted)]">
            Is the system healthy, and what needs attention?
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <Link
            href="/scans/new"
            className="rounded-md bg-[var(--cs-accent)] px-3 py-2 text-sm font-semibold text-[var(--cs-accent-fg)] hover:opacity-90 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--cs-accent)]"
          >
            New scan
          </Link>
          <SignInButton
            email={session?.user.email ?? null}
            displayName={session?.user.displayName ?? null}
          />
        </div>
      </header>

      {params.auth === "failed" ? (
        <p
          role="status"
          className="rounded-md border border-[var(--cs-border)] bg-[var(--cs-surface)] px-3 py-2 text-sm text-[var(--cs-muted)]"
        >
          Sign-in did not complete. No session was created - you can try again.
        </p>
      ) : null}

      {backendDown ? (
        <ApiUnreachable
          title="Backend unreachable"
          message="The dashboard cannot load live data because the CyberStratum API is not responding."
          baseUrl={API_BASE_URL}
        />
      ) : null}

      {!backendDown && !scansResult.ok ? (
        <ApiUnreachable
          title={describeApiError(scansResult.error).title}
          message={describeApiError(scansResult.error).message}
          detail={scansResult.error.detail ?? undefined}
          baseUrl={API_BASE_URL}
        />
      ) : null}

      <section aria-labelledby="kpi-heading">
        <h2 id="kpi-heading" className="sr-only">
          Key metrics
        </h2>
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <KpiCard
            title="Total scans"
            value={String(totalScans)}
            hint={`${scans.filter((scan) => scan.status === "completed").length} completed`}
          />
          <KpiCard
            title="Candidate findings"
            value={String(totalFindings)}
            hint={`${awaitingTriage} awaiting triage`}
            href="/findings"
          />
          <KpiCard
            title="Average risk score"
            value={averageRiskScore === null ? "—" : averageRiskScore.toFixed(1)}
            hint="0-100, higher is worse"
          />
          <KpiCard
            title="Needs attention"
            value={String(needsAttention.length)}
            hint="failed or partial scans"
          />
        </div>
      </section>

      <section aria-labelledby="severity-heading" className="space-y-3">
        <h2 id="severity-heading" className="text-lg font-semibold text-[var(--cs-fg)]">
          Findings by severity
        </h2>
        <ul className="flex flex-wrap gap-3" role="list">
          {SEVERITY_ORDER.map((severity) => (
            <li key={severity}>
              <Link
                href={`/findings?severity=${severity}`}
                className="flex min-w-[9rem] flex-col gap-1 rounded-lg border border-[var(--cs-border)] bg-[var(--cs-surface)] p-3 hover:border-[var(--cs-accent)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--cs-accent)]"
              >
                <SeverityBadge severity={severity} />
                <span className="font-mono text-2xl font-semibold tabular-nums text-[var(--cs-fg)]">
                  {severityCounts[severity]}
                </span>
                <span className="text-xs text-[var(--cs-muted)]">{SEVERITY_META[severity].label}</span>
              </Link>
            </li>
          ))}
        </ul>
      </section>

      {topDetectors.length > 0 ? (
        <section aria-labelledby="detectors-heading" className="space-y-3">
          <h2 id="detectors-heading" className="text-lg font-semibold text-[var(--cs-fg)]">
            What we find most
          </h2>
          <ul className="space-y-1">
            {topDetectors.map((row) => (
              <li key={row.detectorId}>
                <Link
                  href={`/findings?detector=${encodeURIComponent(row.detectorId)}`}
                  className="flex items-baseline justify-between gap-3 rounded-md border border-[var(--cs-border)] bg-[var(--cs-surface)] px-3 py-2 text-sm hover:border-[var(--cs-accent)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--cs-accent)]"
                >
                  <span className="font-mono text-xs text-[var(--cs-fg)]">{row.detectorId}</span>
                  <span className="font-mono text-sm tabular-nums text-[var(--cs-muted)]">
                    {row.count}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {topChains.length > 0 ? (
        <section aria-labelledby="chains-heading" className="space-y-3">
          <h2 id="chains-heading" className="text-lg font-semibold text-[var(--cs-fg)]">
            Where the findings are
          </h2>
          <ul className="space-y-1">
            {topChains.map((row) => (
              <li key={row.chainId}>
                <Link
                  href={`/findings?chain=${row.chainId}`}
                  className="flex items-baseline justify-between gap-3 rounded-md border border-[var(--cs-border)] bg-[var(--cs-surface)] px-3 py-2 text-sm hover:border-[var(--cs-accent)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--cs-accent)]"
                >
                  <span className="text-[var(--cs-fg)]">{row.chainName}</span>
                  <span className="font-mono text-sm tabular-nums text-[var(--cs-muted)]">
                    {row.count}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <section aria-labelledby="recent-scans-heading" className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 id="recent-scans-heading" className="text-lg font-semibold text-[var(--cs-fg)]">
            Recent scans
          </h2>
          <Link
            href="/scans"
            className="text-sm text-[var(--cs-accent)] underline underline-offset-2 hover:opacity-90 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--cs-accent)]"
          >
            View all scans
          </Link>
        </div>
        {scans.length === 0 ? (
          <EmptyState
            title="No scans yet"
            description="Queue your first bytecode scan to start building a findings history."
            action={{ label: "Queue a scan", href: "/scans/new" }}
          />
        ) : (
          <ScanTable scans={scans.slice(0, 10)} caption="Recent scans" />
        )}
      </section>

      <section aria-labelledby="attention-heading" className="space-y-3">
        <h2 id="attention-heading" className="text-lg font-semibold text-[var(--cs-fg)]">
          Needs attention
        </h2>
        {needsAttention.length === 0 ? (
          <p className="text-sm text-[var(--cs-muted)]">
            Nothing needs attention right now.
          </p>
        ) : (
          <ul className="space-y-2" role="list">
            {needsAttention.map((scan) => (
              <li
                key={scan.id}
                className="flex flex-wrap items-center gap-3 rounded-lg border border-[var(--cs-border)] bg-[var(--cs-surface)] px-3 py-2"
              >
                <Link
                  href={`/scans/${encodeURIComponent(scan.id)}`}
                  className="font-mono text-sm text-[var(--cs-accent)] underline underline-offset-2 hover:opacity-90 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--cs-accent)]"
                >
                  {scan.id}
                </Link>
                <span className="font-mono text-xs text-[var(--cs-muted)]">
                  {shortAddress(scan.contractAddress)} · {formatChainId(scan.chainId)}
                </span>
                <span className="ml-auto text-xs text-[var(--cs-muted)]">
                  {scan.error ?? `status: ${scan.status}`} ·{" "}
                  {formatRelativeTime(scan.createdAt)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section aria-labelledby="risk-heading" className="rounded-lg border border-[var(--cs-border)] bg-[var(--cs-surface)] p-4">
        <h2 id="risk-heading" className="text-lg font-semibold text-[var(--cs-fg)]">
          Risk
        </h2>
        <div className="mt-2 flex flex-wrap items-center gap-6">
          <RiskScoreGauge
            score={averageRiskScore}
            estimated={scans.some((scan) => scan.riskScore === null)}
            label="Average risk score"
          />
          <p className="max-w-md text-sm text-[var(--cs-muted)]">
            A high score means many high-severity candidate findings were detected. Scores
            estimated locally are marked as such; the API is the source of truth.
          </p>
        </div>
      </section>
    </div>
  );
}

function KpiCard({
  title,
  value,
  hint,
  href,
}: {
  title: string;
  value: string;
  hint?: string;
  href?: string;
}) {
  const inner = (
    <>
      <span className="text-xs uppercase tracking-wide text-[var(--cs-muted)]">{title}</span>
      <span className="mt-1 block font-mono text-3xl font-semibold tabular-nums text-[var(--cs-fg)]">
        {value}
      </span>
      {hint ? <span className="mt-1 block text-xs text-[var(--cs-muted)]">{hint}</span> : null}
    </>
  );

  return (
    <div className="rounded-lg border border-[var(--cs-border)] bg-[var(--cs-surface)] p-4">
      {href ? (
        <Link
          href={href}
          className="block rounded focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--cs-accent)]"
        >
          {inner}
        </Link>
      ) : (
        inner
      )}
    </div>
  );
}