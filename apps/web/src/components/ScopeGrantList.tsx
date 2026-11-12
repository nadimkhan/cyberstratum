"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import type { ScopeGrantSummary } from "@/lib/types";

/**
 * What a workspace has declared, and a way to take a declaration back.
 *
 * A declaration that was made in error has to be withdrawable: an
 * address pasted wrongly, a programme that has ended, a chain that was
 * never in bounds. Each of them is a statement that is no longer true,
 * and a registry that can only grow will keep making it.
 *
 * Withdrawing is the workspace's own decision, and it names the
 * workspace it acts in — a declaration belongs to one tenant.
 */
export function ScopeGrantList({
  grants,
  workspaceId,
}: {
  grants: ScopeGrantSummary[];
  workspaceId: string;
}) {
  const router = useRouter();
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  async function withdraw(grantId: string) {
    setBusy(grantId);
    setFailed(false);
    setMessage(null);

    try {
      const response = await fetch(
        `/api/scope/grants/${encodeURIComponent(grantId)}?workspace_id=${encodeURIComponent(workspaceId)}`,
        { method: "DELETE" },
      );
      const payload = (await response.json()) as { detail?: string };
      if (!response.ok) {
        setFailed(true);
        setMessage(payload.detail ?? `The backend responded with HTTP ${response.status}.`);
        return;
      }
      setMessage("The declaration was withdrawn.");
      router.refresh();
    } catch {
      setFailed(true);
      setMessage("The declaration could not be withdrawn.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-2">
      <ul className="space-y-2">
        {grants.map((grant) => (
          <li key={grant.id} className="rounded-lg border border-[var(--cs-border)] p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <p className="text-sm text-[var(--cs-fg)]">
                  <span className="font-mono">{grant.kind}</span> &middot;{" "}
                  <span className="font-mono">{grant.value}</span>
                </p>
                <p className="mt-1 text-xs text-[var(--cs-muted)]">
                  {grant.safeHarbour
                    ? "Safe harbour accepted"
                    : "No safe-harbour declaration"}
                  {grant.chainId ? ` · chain ${grant.chainId}` : ""}
                  {grant.reference ? ` · ${grant.reference}` : ""}
                  {grant.expiresAt ? ` · expires ${grant.expiresAt}` : ""}
                </p>
              </div>
              <button
                type="button"
                onClick={() => withdraw(grant.id)}
                disabled={busy !== null}
                className="rounded-md border border-[var(--cs-border)] px-2 py-1 text-xs text-[var(--cs-muted)] hover:text-[var(--cs-fg)] disabled:opacity-60"
              >
                {busy === grant.id ? "Withdrawing…" : "Withdraw"}
              </button>
            </div>
          </li>
        ))}
      </ul>
      {message ? (
        <p
          role={failed ? "alert" : "status"}
          className={
            failed ? "text-sm text-[var(--cs-danger)]" : "text-sm text-[var(--cs-ok)]"
          }
        >
          {message}
        </p>
      ) : null}
    </div>
  );
}
