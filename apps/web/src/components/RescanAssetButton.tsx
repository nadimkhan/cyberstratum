"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

export interface RescanAssetButtonProps {
  assetId: string;
}

/**
 * Queue another scan of a tracked address.
 *
 * The new scan is attached to the asset, so the history grows: this is
 * how a user checks that the fix they shipped actually moved the number.
 */
export function RescanAssetButton({ assetId }: RescanAssetButtonProps) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onClick() {
    setBusy(true);
    setError(null);
    try {
      const response = await fetch(`/api/assets/${encodeURIComponent(assetId)}/scan`, {
        method: "POST",
      });
      if (!response.ok) {
        const payload = (await response.json().catch(() => null)) as {
          detail?: string;
        } | null;
        setError(payload?.detail ?? `The scan could not be queued (HTTP ${response.status}).`);
        setBusy(false);
        return;
      }
      router.refresh();
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : "Unexpected error while queueing the scan.",
      );
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col items-end gap-1">
      <button
        type="button"
        onClick={onClick}
        disabled={busy}
        className="rounded-md bg-[var(--cs-accent)] px-3 py-2 text-sm font-semibold text-[var(--cs-accent-fg)] hover:opacity-90 disabled:opacity-60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--cs-accent)]"
      >
        {busy ? "Queueing…" : "Scan again"}
      </button>
      {error ? (
        <p role="alert" className="text-xs text-[var(--cs-danger)]">
          {error}
        </p>
      ) : null}
    </div>
  );
}
