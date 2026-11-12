"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { bulkVerdictProblem } from "@/lib/bulk-review";
import type { WorkspaceSummary } from "@/lib/types";

/**
 * Settle every open finding of one detector at once.
 *
 * A reviewer who has read one naming-convention finding and decided
 * that it is a style question has decided the same thing about the
 * others of its kind. Recording that once is what makes a reviewed
 * corpus possible at all.
 *
 * The rules are the rules of a single verdict: a false positive needs a
 * reason, and the reason is recorded on every finding the action
 * touches. A finding that has already been settled is not overwritten.
 *
 * The workspace is part of the action, because a verdict belongs to one
 * tenant. The reviewer says whose findings they are settling, and the
 * backend refuses a bulk action that does not know.
 */
export function BulkReviewPanel({
  detectorId,
  count,
  workspaces,
  workspaceId,
}: {
  detectorId: string;
  count: number;
  workspaces: WorkspaceSummary[];
  workspaceId: string | null;
}) {
  const router = useRouter();
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const [selected, setSelected] = useState<string | null>(workspaceId);

  async function settle(status: "confirmed" | "false_positive") {
    const trimmed = note.trim();
    const problem = bulkVerdictProblem(status, trimmed);
    if (problem) {
      setFailed(true);
      setMessage(problem);
      return;
    }
    if (!selected) {
      setFailed(true);
      setMessage("Choose the workspace these findings belong to before settling them.");
      return;
    }

    setBusy(true);
    setFailed(false);
    setMessage(null);

    try {
      const response = await fetch("/api/findings/review-bulk", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          detector_id: detectorId,
          status,
          note: trimmed || null,
          workspace_id: selected,
        }),
      });
      const payload = (await response.json()) as {
        applied?: number;
        skipped?: number;
        detail?: string;
      };
      if (!response.ok) {
        setFailed(true);
        setMessage(payload.detail ?? `The backend responded with HTTP ${response.status}.`);
        return;
      }
      const applied = payload.applied ?? 0;
      setMessage(
        `${applied} finding${applied === 1 ? "" : "s"} settled${
          payload.skipped ? `, ${payload.skipped} already settled and left alone` : ""
        }.`,
      );
      setNote("");
      router.refresh();
    } catch {
      setFailed(true);
      setMessage("The bulk review could not reach the backend.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rounded-lg border border-[var(--cs-border)] bg-[var(--cs-raised)] p-3">
      <p className="text-xs font-medium text-[var(--cs-fg)]">
        Settle all {count} open finding{count === 1 ? "" : "s"} of this detector
      </p>
      <p className="mt-1 text-xs text-[var(--cs-muted)]">
        One verdict, recorded on every one of them, with your reason. Findings you have
        already settled are left alone.
      </p>

      {workspaces.length > 0 ? (
        <label className="mt-2 block text-xs text-[var(--cs-muted)]">
          Workspace
          <select
            value={selected ?? ""}
            onChange={(event) => setSelected(event.target.value || null)}
            className="mt-1 w-full rounded border border-[var(--cs-border)] bg-[var(--cs-surface)] px-2 py-1 text-xs text-[var(--cs-fg)]"
          >
            <option value="">Choose a workspace</option>
            {workspaces.map((workspace) => (
              <option key={workspace.id} value={workspace.id}>
                {workspace.name} ({workspace.openFindings} open)
              </option>
            ))}
          </select>
        </label>
      ) : null}

      <textarea
        value={note}
        onChange={(event) => setNote(event.target.value)}
        rows={2}
        placeholder="Reason (required for a false positive)"
        className="mt-2 w-full rounded border border-[var(--cs-border)] bg-[var(--cs-surface)] px-2 py-1 text-xs text-[var(--cs-fg)]"
      />
      <div className="mt-2 flex flex-wrap gap-2">
        <button
          type="button"
          disabled={busy}
          onClick={() => settle("confirmed")}
          className="rounded border border-[var(--cs-border)] px-2 py-1 text-xs font-medium text-[var(--cs-fg)] disabled:opacity-50"
        >
          Confirm all
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => settle("false_positive")}
          className="rounded border border-[var(--cs-border)] px-2 py-1 text-xs font-medium text-[var(--cs-fg)] disabled:opacity-50"
        >
          Mark all false positive
        </button>
      </div>
      {message ? (
        <p className={`mt-2 text-xs ${failed ? "text-red-400" : "text-[var(--cs-muted)]"}`}>
          {message}
        </p>
      ) : null}
    </div>
  );
}
