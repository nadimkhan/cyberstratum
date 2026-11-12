import Link from "next/link";
import { ApiUnreachable } from "@/components/ApiUnreachable";
import { BulkReviewPanel } from "@/components/BulkReviewPanel";
import { EmptyState } from "@/components/EmptyState";
import { FindingReviewPanel } from "@/components/FindingReviewPanel";
import { GuidancePanel } from "@/components/GuidancePanel";
import { ReviewStatusBadge } from "@/components/StatusBadge";
import { SeverityBadge } from "@/components/SeverityBadge";
import { API_BASE_URL, describeApiError, getGuidanceMap, listFindings, listWorkspaces } from "@/lib/api";
import { formatDateTime, shortAddress } from "@/lib/format";
import type { Finding } from "@/lib/types";

export const dynamic = "force-dynamic";

export const metadata = { title: "Triage" };

/**
 * The review queue.
 *
 * Every verdict recorded here becomes a label for the machine learning
 * pipeline, so the queue shows the findings that nobody has settled
 * yet: the ones still marked new, still in triage, or waiting for more
 * evidence. A confirmed finding and a false positive are both finished
 * work and are not shown here.
 *
 * The findings are grouped by detector, because a reviewer thinks in
 * detectors: one naming-convention finding teaches you what the other
 * seventeen of its kind mean. Each group carries the advice for its
 * detector and one action that settles the whole group.
 *
 * The page is server-rendered and the verdict controls are a client
 * component, so the service key never reaches the browser and the
 * session cookie never leaves it.
 */
export default async function TriagePage() {
  const [result, guidanceResult, workspacesResult] = await Promise.all([
    listFindings({ limit: 200 }),
    getGuidanceMap(),
    listWorkspaces(),
  ]);
  // A verdict recorded here becomes a label the model learns from, so the
  // reviewer is shown what the detector means -- and when the pattern is
  // expected -- before they settle it.
  const guidance = guidanceResult.ok ? guidanceResult.data : {};

  // A bulk verdict belongs to one tenant, so the reviewer chooses the
  // workspace whose findings they are settling. The workspace with the
  // most open findings is offered first, because that is the one the
  // queue was built from.
  const workspaces = workspacesResult.ok ? workspacesResult.data : [];
  const defaultWorkspace =
    workspaces.slice().sort((a, b) => b.openFindings - a.openFindings)[0]?.id ?? null;

  if (!result.ok) {
    return (
      <div className="space-y-6">
        <header>
          <h1 className="text-2xl font-semibold text-[var(--cs-fg)]">Triage</h1>
          <p className="mt-1 text-sm text-[var(--cs-muted)]">
            Findings nobody has settled yet.
          </p>
        </header>
        <ApiUnreachable
          title={describeApiError(result.error).title}
          message={describeApiError(result.error).message}
          detail={result.error.detail ?? undefined}
          baseUrl={API_BASE_URL}
        />
      </div>
    );
  }

  const open = result.data.items.filter(
    (finding) =>
      finding.reviewStatus !== "confirmed" &&
      finding.reviewStatus !== "false_positive",
  );

  // Grouped by detector: one group is one kind of finding, and the
  // advice and the bulk action belong to the group rather than to each
  // individual row.
  const groups = new Map<string, Finding[]>();
  for (const finding of open) {
    const key = finding.detectorId ?? "unknown";
    const bucket = groups.get(key);
    if (bucket) {
      bucket.push(finding);
    } else {
      groups.set(key, [finding]);
    }
  }

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold text-[var(--cs-fg)]">Triage</h1>
        <p className="mt-1 text-sm text-[var(--cs-muted)]">
          Findings nobody has settled yet. The verdict recorded here is the label the
          machine learning pipeline learns from, so a false positive needs a reason: without
          one it cannot be told apart from a mistaken verdict.
        </p>
      </header>

      {open.length === 0 ? (
        <EmptyState
          title="Nothing to triage"
          description="Every finding has been settled. New findings appear here as soon as a scan completes."
          action={{ label: "Queue a scan", href: "/scans/new" }}
        />
      ) : (
        <div className="space-y-8">
          {[...groups.entries()].map(([detectorId, findings]) => (
            <section key={detectorId} className="space-y-3">
              <header className="flex flex-wrap items-baseline gap-2">
                <h2 className="text-sm font-semibold text-[var(--cs-fg)]">{detectorId}</h2>
                <span className="text-xs text-[var(--cs-muted)]">
                  {findings.length} open finding{findings.length === 1 ? "" : "s"}
                </span>
              </header>

              {guidance[detectorId] ? <GuidancePanel guidance={guidance[detectorId]} /> : null}

              <BulkReviewPanel
                detectorId={detectorId}
                count={findings.length}
                workspaces={workspaces}
                workspaceId={defaultWorkspace}
              />

              <ul className="space-y-3">
                {findings.map((finding) => (
                  <li
                    key={finding.id}
                    className="space-y-3 rounded-lg border border-[var(--cs-border)] bg-[var(--cs-surface)] p-4"
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <SeverityBadge severity={finding.severity} />
                      <ReviewStatusBadge status={finding.reviewStatus} />
                      <span className="text-sm font-medium text-[var(--cs-fg)]">
                        {finding.title}
                      </span>
                    </div>

                    <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-[var(--cs-muted)] sm:grid-cols-4">
                      <div>
                        <dt className="inline font-medium">Detector: </dt>
                        <dd className="inline">{finding.detectorId ?? "—"}</dd>
                      </div>
                      <div>
                        <dt className="inline font-medium">Contract: </dt>
                        <dd className="inline">{shortAddress(finding.contractAddress)}</dd>
                      </div>
                      <div>
                        <dt className="inline font-medium">Chain: </dt>
                        <dd className="inline">{finding.chainId ?? "—"}</dd>
                      </div>
                      <div>
                        <dt className="inline font-medium">Found: </dt>
                        <dd className="inline">{formatDateTime(finding.createdAt)}</dd>
                      </div>
                      {finding.scanId ? (
                        <div>
                          <dt className="inline font-medium">Scan: </dt>
                          <dd className="inline">
                            {/* The scan page shows the evidence and the
                                source the finding points at, which is what
                                a reviewer needs before deciding. */}
                            <Link
                              href={`/scans/${finding.scanId}`}
                              className="text-[var(--cs-accent)] underline underline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--cs-accent)]"
                            >
                              open the scan
                            </Link>
                          </dd>
                        </div>
                      ) : null}
                    </dl>

                    {finding.description ? (
                      <p className="text-sm text-[var(--cs-fg)]">{finding.description}</p>
                    ) : null}

                    {finding.limitations ? (
                      <p className="text-xs text-[var(--cs-muted)]">
                        <span className="font-medium">Limitations: </span>
                        {finding.limitations}
                      </p>
                    ) : null}

                    <FindingReviewPanel
                      findingId={finding.id}
                      currentStatus={finding.reviewStatus}
                      currentNote={finding.reviewNote}
                    />
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      )}
    </div>
  );
}
