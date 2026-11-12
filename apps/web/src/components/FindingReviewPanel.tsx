"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

/**
 * The verdict controls for one finding.
 *
 * The verdict recorded here is the label the machine learning pipeline
 * learns from, so this panel is deliberately explicit about what each
 * verdict means:
 *
 * - **Confirmed** -- the finding is real. This is a positive label.
 * - **False positive** -- the finding is not real. A reason is required:
 *   a false positive with no reason cannot be told apart from a mistaken
 *   verdict, and neither is usable as ground truth.
 * - **Needs more evidence** -- the finding may be real and cannot be
 *   settled from what is in front of the reviewer.
 * - **In triage** -- nobody has looked at it yet.
 *
 * The panel never claims the review succeeded on its own: the backend
 * answers, and the page is refreshed from the answer.
 */

interface FindingReviewPanelProps {
  findingId: string;
  currentStatus: string;
  currentNote: string | null;
  disabled?: boolean;
}

/**
 * The front end calls the same status "needs_evidence" that the backend
 * calls "needs_more_evidence". The two are compared here so that the
 * button for the current verdict is the marked one.
 */
function sameVerdict(current: string, candidate: string): boolean {
  const normalise = (value: string) =>
    value === "needs_evidence" ? "needs_more_evidence" : value;
  return normalise(current) === normalise(candidate);
}

const VERDICTS: { value: string; label: string; hint: string }[] = [
  {
    value: "confirmed",
    label: "Confirm",
    hint: "The finding is real. This is a positive training label.",
  },
  {
    value: "false_positive",
    label: "False positive",
    hint: "The finding is not real. A reason is required.",
  },
  {
    value: "needs_more_evidence",
    label: "Needs more evidence",
    hint: "The finding may be real and cannot be settled from here.",
  },
  {
    value: "triage",
    label: "Needs triage",
    hint: "Nobody has looked at this yet.",
  },
];

export function FindingReviewPanel({
  findingId,
  currentStatus,
  currentNote,
  disabled = false,
}: FindingReviewPanelProps) {
  const router = useRouter();
  const [note, setNote] = useState(currentNote ?? "");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  async function submit(status: string) {
    const trimmed = note.trim();
    if (status === "false_positive" && !trimmed) {
      setFailed(true);
      setMessage(
        "A false-positive verdict needs a reason: without one it cannot be told apart from a mistaken verdict.",
      );
      return;
    }

    setBusy(true);
    setMessage(null);
    setFailed(false);
    try {
      const response = await fetch(
        `/api/findings/${encodeURIComponent(findingId)}/review`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ status, note: trimmed || null }),
        },
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
        `Verdict recorded: ${status.replace(/_/g, " ")}. It is stored with your name and the time.`,
      );
      router.refresh();
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
      <label
        htmlFor={`review-note-${findingId}`}
        className="block text-xs font-medium text-[var(--cs-muted)]"
      >
        Reason for the verdict
      </label>
      <textarea
        id={`review-note-${findingId}`}
        value={note}
        onChange={(event) => setNote(event.target.value)}
        rows={2}
        disabled={disabled || busy}
        placeholder="What did you check, and what did you conclude?"
        className="w-full rounded-md border border-[var(--cs-border)] bg-[var(--cs-raised)] px-2 py-1.5 text-sm text-[var(--cs-fg)] placeholder:text-[var(--cs-muted)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--cs-accent)] disabled:opacity-60"
      />
      <div className="flex flex-wrap gap-2">
        {VERDICTS.map((verdict) => (
          <button
            key={verdict.value}
            type="button"
            title={verdict.hint}
            onClick={() => submit(verdict.value)}
            disabled={disabled || busy}
            aria-current={sameVerdict(currentStatus, verdict.value) ? "true" : undefined}
            className={
              sameVerdict(currentStatus, verdict.value)
                ? "rounded-md border border-[var(--cs-accent)] bg-[var(--cs-raised)] px-3 py-1.5 text-sm font-medium text-[var(--cs-accent)] transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--cs-accent)] disabled:cursor-not-allowed disabled:opacity-60"
                : "rounded-md border border-[var(--cs-border)] bg-[var(--cs-raised)] px-3 py-1.5 text-sm text-[var(--cs-fg)] transition hover:border-[var(--cs-accent)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--cs-accent)] disabled:cursor-not-allowed disabled:opacity-60"
            }
          >
            {verdict.label}
          </button>
        ))}
      </div>
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
