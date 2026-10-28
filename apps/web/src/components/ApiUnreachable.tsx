import type { ReactNode } from "react";

export interface ApiUnreachableProps {
  /** Heading of the panel. Defaults to "Backend unreachable". */
  title?: string;
  message?: string;
  detail?: string;
  baseUrl?: string;
  /** Actionable next step shown at the bottom of the panel. */
  hint?: ReactNode;
}

/**
 * Rendered whenever the FastAPI backend cannot be reached, so the UI degrades
 * gracefully instead of throwing during render or build.
 */
export function ApiUnreachable({
  title = "Backend unreachable",
  message,
  detail,
  baseUrl,
  hint,
}: ApiUnreachableProps) {
  return (
    <div
      role="alert"
      className="rounded-lg border border-[var(--cs-danger)]/50 bg-[var(--cs-danger)]/10 px-5 py-4"
    >
      <p className="flex items-center gap-2 text-sm font-semibold text-[var(--cs-fg)]">
        <span aria-hidden="true" className="text-[var(--cs-danger)]">
          ⚠
        </span>
        {title}
      </p>
      <p className="mt-1 text-sm text-[var(--cs-muted)]">
        {message ?? "The CyberStratum API did not respond, so live data cannot be shown."}
      </p>
      {baseUrl ? (
        <p className="mt-2 text-xs text-[var(--cs-muted)]">
          API base URL:{" "}
          <code className="rounded bg-[var(--cs-raised)] px-1.5 py-0.5 font-mono">
            {baseUrl}
          </code>
        </p>
      ) : null}
      {detail ? (
        <p className="mt-2 font-mono text-xs text-[var(--cs-muted)]">{detail}</p>
      ) : null}
      {hint ? (
        <div className="mt-3 text-xs text-[var(--cs-muted)]">{hint}</div>
      ) : (
        <p className="mt-3 text-xs text-[var(--cs-muted)]">
          Start the API with{" "}
          <code className="rounded bg-[var(--cs-raised)] px-1.5 py-0.5 font-mono">
            uvicorn app.main:app --port 8000
          </code>{" "}
          from <code className="font-mono">apps/api</code>, then reload this page.
        </p>
      )}
    </div>
  );
}