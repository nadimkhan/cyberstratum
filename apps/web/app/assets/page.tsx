import Link from "next/link";
import { ApiUnreachable } from "@/components/ApiUnreachable";
import { EmptyState } from "@/components/EmptyState";
import { API_BASE_URL, describeApiError, listAssets } from "@/lib/api";
import { formatDateTime, formatRelativeTime, shortAddress } from "@/lib/format";

export const dynamic = "force-dynamic";

export const metadata = { title: "Assets" };

const KIND_LABEL: Record<string, string> = {
  owned: "Your contract",
  watched: "Watched",
  discovered: "Discovered",
};

export default async function AssetsPage() {
  const result = await listAssets({ limit: 200 });

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-[var(--cs-fg)]">Assets</h1>
          <p className="mt-1 text-sm text-[var(--cs-muted)]">
            Every address this workspace keeps a history for: your own contracts, the
            wallets you watch, and the contracts the autonomous sweep discovers.
          </p>
        </div>
        <Link
          href="/scans/new"
          className="rounded-md bg-[var(--cs-accent)] px-3 py-2 text-sm font-semibold text-[var(--cs-accent-fg)] hover:opacity-90 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--cs-accent)]"
        >
          New scan
        </Link>
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
          title="No assets yet"
          description="Scan a contract and it starts keeping a history: every scan, every finding, dated."
          action={{ label: "Queue a scan", href: "/scans/new" }}
        />
      ) : (
        <div className="space-y-3">
          <p className="text-xs text-[var(--cs-muted)]">
            {result.data.total} asset{result.data.total === 1 ? "" : "s"} tracked.
          </p>
          <ul className="space-y-2">
            {result.data.items.map((detail) => (
              <li key={detail.asset.id}>
                <Link
                  href={`/assets/${encodeURIComponent(detail.asset.id)}`}
                  className="block rounded-md border border-[var(--cs-border)] bg-[var(--cs-surface)] px-4 py-3 hover:border-[var(--cs-accent)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--cs-accent)]"
                >
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <span className="font-mono text-sm text-[var(--cs-fg)]">
                      {shortAddress(detail.asset.address)}
                    </span>
                    <span className="rounded-full bg-[var(--cs-raised)] px-2 py-0.5 text-xs text-[var(--cs-muted)]">
                      {KIND_LABEL[detail.asset.kind] ?? detail.asset.kind}
                    </span>
                  </div>
                  {detail.asset.label ? (
                    <p className="mt-1 text-sm text-[var(--cs-fg)]">{detail.asset.label}</p>
                  ) : null}
                  <dl className="mt-2 flex flex-wrap gap-x-6 gap-y-1 text-xs text-[var(--cs-muted)]">
                    <div className="flex gap-1.5">
                      <dt>Scans</dt>
                      <dd className="text-[var(--cs-fg)]">{detail.progress.scanCount}</dd>
                    </div>
                    <div className="flex gap-1.5">
                      <dt>Findings</dt>
                      <dd className="text-[var(--cs-fg)]">{detail.progress.findingCount}</dd>
                    </div>
                    <div className="flex gap-1.5">
                      <dt>Open</dt>
                      <dd className="text-[var(--cs-fg)]">{detail.progress.openFindingCount}</dd>
                    </div>
                    <div className="flex gap-1.5">
                      <dt>Last scanned</dt>
                      <dd className="text-[var(--cs-fg)]">
                        {detail.progress.lastScannedAt
                          ? formatRelativeTime(detail.progress.lastScannedAt)
                          : "never"}
                      </dd>
                    </div>
                    <div className="flex gap-1.5">
                      <dt>First seen</dt>
                      <dd className="text-[var(--cs-fg)]">{formatDateTime(detail.asset.firstSeenAt)}</dd>
                    </div>
                  </dl>
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
