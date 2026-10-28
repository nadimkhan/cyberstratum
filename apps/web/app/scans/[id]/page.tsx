import Link from "next/link";
import { notFound } from "next/navigation";
import { ApiUnreachable } from "@/components/ApiUnreachable";
import { EmptyState } from "@/components/EmptyState";
import { FindingTable } from "@/components/FindingTable";
import { RiskScoreGauge } from "@/components/RiskScoreGauge";
import { SeverityBadge } from "@/components/SeverityBadge";
import { StatusBadge } from "@/components/StatusBadge";
import { StageTimeline } from "@/components/StageTimeline";
import { API_BASE_URL, describeApiError, getScan, getScanFindings } from "@/lib/api";
import {
  formatBytes,
  formatChainId,
  formatDateTime,
  formatDuration,
  formatLabels,
  shortAddress,
  shortHash,
} from "@/lib/format";
import { estimateRiskScore } from "@/lib/severity";
import { SEVERITY_ORDER } from "@/lib/types";

export const dynamic = "force-dynamic";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return { title: `Scan ${id}` };
}

export default async function ScanDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const [scanResult, findingsResult] = await Promise.all([getScan(id), getScanFindings(id)]);

  if (!scanResult.ok) {
    if (scanResult.error.kind === "not_found") notFound();
    return (
      <div className="space-y-4">
        <h1 className="text-2xl font-semibold text-[var(--cs-fg)]">Scan {id}</h1>
        <ApiUnreachable
          title={describeApiError(scanResult.error).title}
          message={describeApiError(scanResult.error).message}
          detail={scanResult.error.detail ?? undefined}
          baseUrl={API_BASE_URL}
        />
        <Link
          href="/scans"
          className="text-sm text-[var(--cs-accent)] underline underline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--cs-accent)]"
        >
          Back to scans
        </Link>
      </div>
    );
  }

  const scan = scanResult.data;
  const findings = findingsResult.ok ? findingsResult.data : [];
  const riskScore = scan.riskScore ?? estimateRiskScore(scan.findingCounts);
  const riskEstimated = scan.riskScore === null;

  return (
    <div className="space-y-8">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-xs uppercase tracking-wide text-[var(--cs-muted)]">Scan</p>
          <h1 className="font-mono text-xl font-semibold text-[var(--cs-fg)]">{scan.id}</h1>
          <p className="mt-1 text-sm text-[var(--cs-muted)]">
            <span className="font-mono">{shortAddress(scan.contractAddress)}</span> ·{" "}
            {formatChainId(scan.chainId)} · fork {scan.fork ?? "—"}
          </p>
        </div>
        <div className="flex flex-col items-end gap-2">
          <StatusBadge status={scan.status} />
          <span className="text-xs text-[var(--cs-muted)]">
            Started {formatDateTime(scan.startedAt ?? scan.createdAt)} ·{" "}
            {formatDuration(scan.durationMs)}
          </span>
        </div>
      </header>

      {scan.error ? (
        <p
          role="alert"
          className="rounded-md bg-[var(--cs-danger-soft)] px-3 py-2 text-sm text-[var(--cs-danger)]"
        >
          {scan.error}
        </p>
      ) : null}

      <section aria-labelledby="summary-heading" className="space-y-3">
        <h2 id="summary-heading" className="text-lg font-semibold text-[var(--cs-fg)]">
          Summary
        </h2>
        <div className="grid gap-4 lg:grid-cols-[auto_1fr]">
          <div className="rounded-lg border border-[var(--cs-border)] bg-[var(--cs-surface)] p-4">
            <RiskScoreGauge score={riskScore} estimated={riskEstimated} />
          </div>
          <dl className="grid gap-x-6 gap-y-3 rounded-lg border border-[var(--cs-border)] bg-[var(--cs-surface)] p-4 sm:grid-cols-2">
            <Detail label="Total findings" value={String(scan.totalFindings)} />
            <Detail label="Requested by" value={scan.requestedBy ?? "—"} />
            <Detail label="Created" value={formatDateTime(scan.createdAt)} />
            <Detail label="Completed" value={formatDateTime(scan.completedAt)} />
            <Detail label="Labels" value={formatLabels(scan.labels)} />
            <Detail
              label="Graph coverage"
              value={
                scan.coverage
                  ? `${scan.coverage.resolvedJumps ?? "?"} resolved / ${
                      scan.coverage.unresolvedJumps ?? "?"
                    } unresolved jumps`
                  : "—"
              }
            />
          </dl>
        </div>
      </section>

      <section aria-labelledby="severity-heading" className="space-y-3">
        <h2 id="severity-heading" className="text-lg font-semibold text-[var(--cs-fg)]">
          Findings by severity
        </h2>
        <ul className="flex flex-wrap gap-3" role="list">
          {SEVERITY_ORDER.map((severity) => (
            <li key={severity}>
              <SeverityBadge severity={severity} count={scan.findingCounts[severity]} />
            </li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="pipeline-heading" className="space-y-3">
        <h2 id="pipeline-heading" className="text-lg font-semibold text-[var(--cs-fg)]">
          Pipeline trace
        </h2>
        <div className="rounded-lg border border-[var(--cs-border)] bg-[var(--cs-surface)] p-4">
          <StageTimeline stages={scan.stages} />
        </div>
      </section>

      <section aria-labelledby="findings-heading" className="space-y-3">
        <h2 id="findings-heading" className="text-lg font-semibold text-[var(--cs-fg)]">
          Findings
        </h2>
        {!findingsResult.ok ? (
          <ApiUnreachable
            title={describeApiError(findingsResult.error).title}
            message={describeApiError(findingsResult.error).message}
            detail={findingsResult.error.detail ?? undefined}
            baseUrl={API_BASE_URL}
          />
        ) : findings.length === 0 ? (
          <EmptyState
            title="No candidate findings"
            description="This scan produced no candidate findings. That is not proof the contract is safe."
            action={{ label: "View all findings", href: "/findings" }}
          />
        ) : (
          <FindingTable findings={findings} showFilters={false} caption={`Findings for scan ${scan.id}`} />
        )}
      </section>

      <section aria-labelledby="repro-heading" className="space-y-3">
        <h2 id="repro-heading" className="text-lg font-semibold text-[var(--cs-fg)]">
          Reproducibility
        </h2>
        <div className="rounded-lg border border-[var(--cs-border)] bg-[var(--cs-surface)] p-4">
          <dl className="grid gap-x-6 gap-y-3 sm:grid-cols-2">
            <Detail
              label="Bytecode hash"
              value={
                <span className="font-mono text-xs" title={scan.reproducibility.bytecodeHash ?? ""}>
                  {shortHash(scan.reproducibility.bytecodeHash, 14, 8)}
                </span>
              }
            />
            <Detail
              label="Opcode table version"
              value={scan.reproducibility.opcodeTableVersion ?? "—"}
            />
            <Detail label="Ruleset version" value={scan.reproducibility.rulesetVersion ?? "—"} />
            <Detail label="Model version" value={scan.reproducibility.modelVersion ?? "—"} />
            <Detail
              label="Feature schema version"
              value={scan.reproducibility.featureSchemaVersion ?? "—"}
            />
          </dl>

          <h3 className="mt-5 text-sm font-semibold text-[var(--cs-fg)]">Tool versions</h3>
          {scan.reproducibility.toolVersions.length === 0 ? (
            <p className="mt-1 text-sm text-[var(--cs-muted)]">
              The backend did not report tool versions for this scan.
            </p>
          ) : (
            <ul className="mt-2 space-y-1" role="list">
              {scan.reproducibility.toolVersions.map((tool) => (
                <li key={`${tool.name}-${tool.version}`} className="font-mono text-sm">
                  <span className="text-[var(--cs-muted)]">{tool.name}</span>{" "}
                  <span className="text-[var(--cs-fg)]">{tool.version}</span>
                </li>
              ))}
            </ul>
          )}

          {Object.keys(scan.reproducibility.environment).length > 0 ? (
            <>
              <h3 className="mt-5 text-sm font-semibold text-[var(--cs-fg)]">Environment</h3>
              <ul className="mt-2 space-y-1" role="list">
                {Object.entries(scan.reproducibility.environment).map(([key, value]) => (
                  <li key={key} className="font-mono text-sm">
                    <span className="text-[var(--cs-muted)]">{key}</span>{" "}
                    <span className="text-[var(--cs-fg)]">{value}</span>
                  </li>
                ))}
              </ul>
            </>
          ) : null}
        </div>
      </section>

      <section aria-labelledby="artifacts-heading" className="space-y-3">
        <h2 id="artifacts-heading" className="text-lg font-semibold text-[var(--cs-fg)]">
          Artifacts
        </h2>
        {scan.artifacts.length === 0 ? (
          <p className="text-sm text-[var(--cs-muted)]">No artifacts were reported for this scan.</p>
        ) : (
          <div className="overflow-x-auto rounded-lg border border-[var(--cs-border)]">
            <table className="w-full border-collapse text-left text-sm">
              <caption className="sr-only">Artifacts produced by this scan</caption>
              <thead>
                <tr className="border-b border-[var(--cs-border)] bg-[var(--cs-raised)] text-xs uppercase tracking-wide text-[var(--cs-muted)]">
                  <th scope="col" className="px-3 py-2 font-medium">Name</th>
                  <th scope="col" className="px-3 py-2 font-medium">Kind</th>
                  <th scope="col" className="px-3 py-2 font-medium">Size</th>
                  <th scope="col" className="px-3 py-2 font-medium">SHA-256</th>
                  <th scope="col" className="px-3 py-2 font-medium">Created</th>
                </tr>
              </thead>
              <tbody>
                {scan.artifacts.map((artifact) => (
                  <tr key={artifact.id} className="border-b border-[var(--cs-border)] last:border-0">
                    <th scope="row" className="px-3 py-2 font-mono text-xs font-normal">
                      {artifact.uri ? (
                        <a
                          href={artifact.uri}
                          className="underline decoration-dotted underline-offset-2 hover:text-[var(--cs-accent)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--cs-accent)]"
                        >
                          {artifact.name}
                        </a>
                      ) : (
                        artifact.name
                      )}
                    </th>
                    <td className="px-3 py-2 text-xs">{artifact.kind}</td>
                    <td className="px-3 py-2 font-mono text-xs">{formatBytes(artifact.sizeBytes)}</td>
                    <td className="px-3 py-2 font-mono text-xs">{shortHash(artifact.sha256)}</td>
                    <td className="px-3 py-2 text-xs">{formatDateTime(artifact.createdAt)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {scan.warnings.length > 0 ? (
        <section aria-labelledby="warnings-heading" className="space-y-3">
          <h2 id="warnings-heading" className="text-lg font-semibold text-[var(--cs-fg)]">
            Parser warnings
          </h2>
          <ul className="space-y-1 text-sm text-[var(--cs-muted)]" role="list">
            {scan.warnings.map((warning, index) => (
              <li key={`${index}-${warning}`}>• {warning}</li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}

function Detail({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs uppercase tracking-wide text-[var(--cs-muted)]">{label}</dt>
      <dd className="mt-0.5 text-sm text-[var(--cs-fg)]">{value}</dd>
    </div>
  );
}