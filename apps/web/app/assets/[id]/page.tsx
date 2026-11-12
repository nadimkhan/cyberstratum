import Link from "next/link";
import { notFound } from "next/navigation";
import { ApiUnreachable } from "@/components/ApiUnreachable";
import { RescanAssetButton } from "@/components/RescanAssetButton";
import { API_BASE_URL, describeApiError, getAssetHistory } from "@/lib/api";
import { formatDateTime, shortAddress } from "@/lib/format";

export const dynamic = "force-dynamic";

export const metadata = { title: "Asset" };

const KIND_LABEL: Record<string, string> = {
  owned: "Your contract",
  watched: "Watched",
  discovered: "Discovered",
};

export default async function AssetDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const result = await getAssetHistory(id);

  if (!result.ok) {
    if (result.error.kind === "not_found") notFound();
    return (
      <div className="space-y-6">
        <ApiUnreachable
          title={describeApiError(result.error).title}
          message={describeApiError(result.error).message}
          detail={result.error.detail ?? undefined}
          baseUrl={API_BASE_URL}
        />
      </div>
    );
  }

  const { asset, progress, timeline, evmChainId } = result.data;

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <Link href="/assets" className="text-xs text-[var(--cs-muted)] hover:text-[var(--cs-fg)]">
            &larr; All assets
          </Link>
          <h1 className="mt-1 text-2xl font-semibold text-[var(--cs-fg)]">
            {asset.label || shortAddress(asset.address)}
          </h1>
          <p className="mt-1 font-mono text-sm text-[var(--cs-muted)]">{asset.address}</p>
        </div>
        <RescanAssetButton assetId={asset.id} />
      </header>

      <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <div className="rounded-md border border-[var(--cs-border)] bg-[var(--cs-surface)] px-4 py-3">
          <p className="text-xs text-[var(--cs-muted)]">Scans</p>
          <p className="mt-1 text-xl font-semibold text-[var(--cs-fg)]">{progress.scanCount}</p>
        </div>
        <div className="rounded-md border border-[var(--cs-border)] bg-[var(--cs-surface)] px-4 py-3">
          <p className="text-xs text-[var(--cs-muted)]">Findings</p>
          <p className="mt-1 text-xl font-semibold text-[var(--cs-fg)]">{progress.findingCount}</p>
        </div>
        <div className="rounded-md border border-[var(--cs-border)] bg-[var(--cs-surface)] px-4 py-3">
          <p className="text-xs text-[var(--cs-muted)]">Open findings</p>
          <p className="mt-1 text-xl font-semibold text-[var(--cs-fg)]">
            {progress.openFindingCount}
          </p>
        </div>
        <div className="rounded-md border border-[var(--cs-border)] bg-[var(--cs-surface)] px-4 py-3">
          <p className="text-xs text-[var(--cs-muted)]">Chain</p>
          <p className="mt-1 text-xl font-semibold text-[var(--cs-fg)]">{evmChainId}</p>
        </div>
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold text-[var(--cs-fg)]">Progress</h2>
        <dl className="flex flex-wrap gap-x-8 gap-y-2 text-sm">
          <div className="flex gap-2">
            <dt className="text-[var(--cs-muted)]">Kind</dt>
            <dd className="text-[var(--cs-fg)]">{KIND_LABEL[asset.kind] ?? asset.kind}</dd>
          </div>
          <div className="flex gap-2">
            <dt className="text-[var(--cs-muted)]">First seen</dt>
            <dd className="text-[var(--cs-fg)]">{formatDateTime(asset.firstSeenAt)}</dd>
          </div>
          <div className="flex gap-2">
            <dt className="text-[var(--cs-muted)]">Last scanned</dt>
            <dd className="text-[var(--cs-fg)]">{formatDateTime(progress.lastScannedAt)}</dd>
          </div>
        </dl>
        {asset.notes ? (
          <p className="text-sm text-[var(--cs-muted)]">{asset.notes}</p>
        ) : null}
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold text-[var(--cs-fg)]">History</h2>
        {timeline.length === 0 ? (
          <p className="text-sm text-[var(--cs-muted)]">
            No scan has been taken against this address yet.
          </p>
        ) : (
          <ol className="space-y-2">
            {timeline.map((entry) => (
              <li
                key={entry.scanId}
                className="rounded-md border border-[var(--cs-border)] bg-[var(--cs-surface)] px-4 py-3"
              >
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <Link
                    href={`/scans/${encodeURIComponent(entry.scanId)}`}
                    className="font-mono text-sm text-[var(--cs-fg)] hover:text-[var(--cs-accent)]"
                  >
                    {shortAddress(entry.scanId)}
                  </Link>
                  <time
                    dateTime={entry.createdAt ?? undefined}
                    className="text-xs text-[var(--cs-muted)]"
                  >
                    {formatDateTime(entry.createdAt)}
                  </time>
                </div>
                <div className="mt-1 flex flex-wrap items-center gap-3 text-xs text-[var(--cs-muted)]">
                  <span className="rounded-full bg-[var(--cs-raised)] px-2 py-0.5 text-[var(--cs-fg)]">
                    {entry.status}
                  </span>
                  <span>
                    {entry.findingCount} finding{entry.findingCount === 1 ? "" : "s"}
                  </span>
                  {Object.entries(entry.bySeverity).map(([severity, count]) => (
                    <span key={severity}>
                      {severity}: {count}
                    </span>
                  ))}
                </div>
              </li>
            ))}
          </ol>
        )}
      </section>
    </div>
  );
}
