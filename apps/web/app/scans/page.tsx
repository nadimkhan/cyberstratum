import Link from "next/link";
import { ApiUnreachable } from "@/components/ApiUnreachable";
import { EmptyState } from "@/components/EmptyState";
import { ScanTable } from "@/components/ScanTable";
import { API_BASE_URL, describeApiError, listScans } from "@/lib/api";

export const dynamic = "force-dynamic";

export const metadata = { title: "Scans" };

export default async function ScansPage() {
  const result = await listScans({ limit: 200 });

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-[var(--cs-fg)]">Scans</h1>
          <p className="mt-1 text-sm text-[var(--cs-muted)]">
            Every bytecode scan queued in this environment, with its pipeline status.
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
          title="No scans yet"
          description="Queue a scan to analyse contract bytecode and surface candidate findings."
          action={{ label: "Queue a scan", href: "/scans/new" }}
        />
      ) : (
        <div className="space-y-2">
          <p className="text-xs text-[var(--cs-muted)]">
            {result.data.total} scan{result.data.total === 1 ? "" : "s"} in total.
          </p>
          <ScanTable scans={result.data.items} caption="All scans" />
        </div>
      )}
    </div>
  );
}