"use client";

import { useState } from "react";

/**
 * Requests an on-demand source-to-bytecode correspondence proof.
 *
 * The proof recompiles the contract's verified source and compares the
 * result with the deployed runtime, so it is a compiler run rather than a
 * bytecode scan. It is manual-only, on its own queue, with its own budget.
 *
 * The button reports "queued" when it succeeds. It does not claim that a
 * source line may be cited: only a proof whose status is `established`
 * licenses that, and a missing proof is not evidence of a mismatch.
 */
export function CorrespondenceRunButton({ scanId }: { scanId: string }) {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  async function run() {
    setBusy(true);
    setMessage(null);
    setFailed(false);
    try {
      const response = await fetch(
        `/api/scans/${encodeURIComponent(scanId)}/correspondence`,
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
          "Correspondence proof queued. Until a proof with the 'established' status exists, no source line may be cited for this scan.",
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
        {busy ? "Requesting…" : "Prove source-to-bytecode correspondence"}
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
