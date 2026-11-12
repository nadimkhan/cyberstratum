import { ApiUnreachable } from "@/components/ApiUnreachable";
import { EmptyState } from "@/components/EmptyState";
import { FindingReviewPanel } from "@/components/FindingReviewPanel";
import { ReviewStatusBadge } from "@/components/StatusBadge";
import { SeverityBadge } from "@/components/SeverityBadge";
import { API_BASE_URL, describeApiError, listFindings } from "@/lib/api";
import { formatDateTime, shortAddress } from "@/lib/format";

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
 * The page is server-rendered and the verdict controls are a client
 * component, so the service key never reaches the browser and the
 * session cookie never leaves it.
 */
export default async function TriagePage() {
  const result = await listFindings({ limit: 200 });

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
        <ul className="space-y-3">
          {open.map((finding) => (
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
                  <dd className="inline">
                    {shortAddress(finding.contractAddress)}
                  </dd>
                </div>
                <div>
                  <dt className="inline font-medium">Chain: </dt>
                  <dd className="inline">{finding.chainId ?? "—"}</dd>
                </div>
                <div>
                  <dt className="inline font-medium">Found: </dt>
                  <dd className="inline">{formatDateTime(finding.createdAt)}</dd>
                </div>
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
      )}
    </div>
  );
}
