import { ApiUnreachable } from "@/components/ApiUnreachable";
import { EmptyState } from "@/components/EmptyState";
import {
  API_BASE_URL,
  type ApiError,
  describeApiError,
  getDiscoveryCursors,
  getDiscoveryRuns,
} from "@/lib/api";
import { formatDateTime } from "@/lib/format";

export const metadata = { title: "Discovery" };
export const dynamic = "force-dynamic";

/**
 * What the autonomous mode has been doing.
 *
 * The product reads the chains on its own, finding contracts as they
 * are verified. That work is invisible until it is on a page: this is
 * how far each chain's feed has been read, which page comes next, and
 * what each cycle found -- including the chains it could not reach.
 */
export default async function DiscoveryPage() {
  const [cursorResult, runResult] = await Promise.all([
    getDiscoveryCursors(),
    getDiscoveryRuns(),
  ]);

  const unreachable = (error: ApiError) => (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold text-[var(--cs-fg)]">Discovery</h1>
      <ApiUnreachable
        title={describeApiError(error).title}
        message={describeApiError(error).message}
        detail={error.detail ?? undefined}
        baseUrl={API_BASE_URL}
      />
    </div>
  );

  if (!cursorResult.ok) return unreachable(cursorResult.error);
  if (!runResult.ok) return unreachable(runResult.error);

  const cursors = cursorResult.data;
  const runs = runResult.data;
  const contractsSeen = cursors.reduce((total, cursor) => total + cursor.contractsSeen, 0);

  return (
    <div className="space-y-8">
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold text-[var(--cs-fg)]">Discovery</h1>
        <p className="text-sm text-[var(--cs-muted)]">
          {cursors.length} chain{cursors.length === 1 ? "" : "s"} read,{" "}
          {contractsSeen} contracts seen. Each cycle takes the chains that
          were read longest ago, and the ones it has never seen come before
          any it has.
        </p>
      </header>

      <section aria-labelledby="chains-heading" className="space-y-3">
        <h2 id="chains-heading" className="text-lg font-semibold text-[var(--cs-fg)]">
          The chains
        </h2>
        {cursors.length === 0 ? (
          <EmptyState
            title="No chain has been read yet"
            description="A discovery cycle reads the newest verified contracts on each chain and queues a scan for each one."
          />
        ) : (
          <ul className="space-y-3">
            {cursors.map((cursor) => (
              <li
                key={cursor.chainId}
                className="space-y-2 rounded-lg border border-[var(--cs-border)] bg-[var(--cs-surface)] p-4"
              >
                <div className="flex flex-wrap items-baseline gap-2">
                  <span className="text-sm font-medium text-[var(--cs-fg)]">
                    {cursor.chainName}
                  </span>
                  <span className="text-xs text-[var(--cs-muted)]">
                    chain {cursor.chainId}
                  </span>
                </div>
                <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-[var(--cs-muted)] sm:grid-cols-4">
                  <div>
                    <dt className="inline font-medium">Contracts seen: </dt>
                    <dd className="inline">{cursor.contractsSeen}</dd>
                  </div>
                  <div>
                    <dt className="inline font-medium">Reading next: </dt>
                    <dd className="inline">page {cursor.nextPage}</dd>
                  </div>
                  <div>
                    <dt className="inline font-medium">Last verified: </dt>
                    <dd className="inline">{formatDateTime(cursor.lastVerifiedAt)}</dd>
                  </div>
                  <div>
                    <dt className="inline font-medium">Read at: </dt>
                    <dd className="inline">{formatDateTime(cursor.updatedAt)}</dd>
                  </div>
                </dl>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section aria-labelledby="runs-heading" className="space-y-3">
        <h2 id="runs-heading" className="text-lg font-semibold text-[var(--cs-fg)]">
          The cycles
        </h2>
        {runs.length === 0 ? (
          <EmptyState
            title="No cycle has run yet"
            description="A cycle reads the newest verified contracts and queues the scans."
          />
        ) : (
          <ul className="space-y-3">
            {runs.map((run) => (
              <li
                key={run.id}
                className="space-y-2 rounded-lg border border-[var(--cs-border)] bg-[var(--cs-surface)] p-4"
              >
                <div className="flex flex-wrap items-baseline gap-2">
                  <span className="text-sm font-medium text-[var(--cs-fg)]">
                    {run.status}
                  </span>
                  <span className="text-xs text-[var(--cs-muted)]">
                    {formatDateTime(run.startedAt)}
                  </span>
                </div>
                <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-[var(--cs-muted)] sm:grid-cols-4">
                  <div>
                    <dt className="inline font-medium">Chains: </dt>
                    <dd className="inline">
                      {run.chainsCovered} read
                      {run.chainsFailed > 0 ? `, ${run.chainsFailed} failed` : ""}
                    </dd>
                  </div>
                  <div>
                    <dt className="inline font-medium">Found: </dt>
                    <dd className="inline">{run.contractsFound}</dd>
                  </div>
                  <div>
                    <dt className="inline font-medium">New: </dt>
                    <dd className="inline">{run.contractsNew}</dd>
                  </div>
                  <div>
                    <dt className="inline font-medium">Updated: </dt>
                    <dd className="inline">{run.contractsUpdated}</dd>
                  </div>
                </dl>
                {run.errors.length > 0 ? (
                  <ul className="space-y-1 text-xs text-[var(--cs-muted)]">
                    {run.errors.map((error, index) => (
                      <li key={index}>
                        {error.chain_id ? `chain ${error.chain_id}: ` : ""}
                        {error.reason}
                      </li>
                    ))}
                  </ul>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
