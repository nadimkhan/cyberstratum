"use client";

import { useState } from "react";

/**
 * Triggers an on-demand Mythril deep analysis for a scan.
 *
 * Mythril is manual-only by decision. It runs out of process, on its own
 * queue, with its own budget, and never as part of a standard scan. The
 * button therefore says "queued" when it succeeds - it does not claim the
 * contract was analysed, and it certainly does not claim the contract is
 * clean.
 */
export function MythrilRunButton({ scanId }: { scanId: string }) {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  async function run() {
    setBusy(true);
    setMessage(null);
    setFailed(false);
    try {
      const response = await fetch(
        `/api/scans/${encodeURIComponent(scanId)}/mythril`,
        { method: "POST" },
      );
      const payload = (await response.json().catch(() => null)) as
        | { detail?: string; message?: string }
        | null;
      if (!response.ok) {
        setFailed(true);
        setMessage(
          payload?.detail ??
            payload?.message ??
            `The backend responded with HTTP ${response.status}.`,
        );
        return;
      }
      setMessage(
        payload?.message ??
          "Mythril deep analysis queued. It runs out of process on its own queue and will not change this scan until it completes.",
      );
    } catch (error) {
      setFailed(true);
      setMessage(
        error instanceof Error ? error.message : "The request could not be sent.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-2">
      <button
        type="button"
        onClick={run}
        disabled={busy}
        className="rounded-md border border-[var(--cs-border)] bg-[var(--cs-raised)] px-3 py-1.5 text-sm text-[var(--cs-fg)] transition hover:border-[var(--cs-accent)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--cs-accent)] disabled:cursor-not-allowed disabled:opacity-60"
      >
        {busy ? "Requesting…" : "Run Mythril deep analysis"}
      </button>
      {message ? (
        <p
          role="status"
          className={
            failed
              ? "text-sm text-[var(--cs-danger)]"
              : "text-sm text-[var(--cs-muted)]"
          }
        >
          {message}
        </p>
      ) : null}
    </div>
  );
}
