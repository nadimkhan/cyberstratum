"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { scopeGrantProblem, SCOPE_GRANT_KINDS, type ScopeGrantKind } from "@/lib/scope";

/**
 * Declare what a workspace is allowed to look at.
 *
 * The declaration is the answer to a question the product has to be
 * able to answer honestly: was this workspace welcome to examine this
 * target? A workspace that has declared nothing has not been refused
 * and has not been permitted, and the product says "unknown" rather
 * than choosing for it.
 *
 * The workspace is part of the declaration. A scope that applied to
 * every workspace at once would not be a scope.
 */
export function ScopeGrantForm({ workspaceId }: { workspaceId: string }) {
  const router = useRouter();
  const [kind, setKind] = useState<ScopeGrantKind>("contract");
  const [value, setValue] = useState("");
  const [chainId, setChainId] = useState("1");
  const [safeHarbour, setSafeHarbour] = useState(false);
  const [reference, setReference] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  async function declare() {
    const problem = scopeGrantProblem(kind, value, chainId);
    if (problem) {
      setFailed(true);
      setMessage(problem);
      return;
    }

    setBusy(true);
    setFailed(false);
    setMessage(null);

    try {
      const response = await fetch("/api/scope/grants", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          workspace_id: workspaceId,
          kind,
          value: value.trim(),
          chain_id: kind === "chain" ? Number(chainId.trim()) : Number(chainId.trim()) || null,
          safe_harbour: safeHarbour,
          reference: reference.trim() || null,
        }),
      });
      const payload = (await response.json()) as { detail?: string };
      if (!response.ok) {
        setFailed(true);
        setMessage(payload.detail ?? `The backend responded with HTTP ${response.status}.`);
        return;
      }
      setValue("");
      setReference("");
      setMessage("The declaration was recorded.");
      router.refresh();
    } catch {
      setFailed(true);
      setMessage("The declaration could not be sent.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="space-y-3 rounded-lg border border-[var(--cs-border)] p-4">
      <h2 className="text-sm font-semibold text-[var(--cs-fg)]">
        Declare what is in bounds
      </h2>
      <p className="text-sm text-[var(--cs-muted)]">
        A declaration says what this workspace may examine and disclose. Until
        one exists, every scan is recorded as &ldquo;scope unknown&rdquo; &mdash;
        which is neither permission nor refusal.
      </p>

      <div className="grid gap-3 sm:grid-cols-2">
        <label className="block space-y-1 text-sm">
          <span className="text-[var(--cs-muted)]">Kind</span>
          <select
            value={kind}
            onChange={(event) => setKind(event.target.value as ScopeGrantKind)}
            className="w-full rounded-md border border-[var(--cs-border)] bg-[var(--cs-surface)] px-2 py-1 text-sm"
          >
            {SCOPE_GRANT_KINDS.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </label>

        <label className="block space-y-1 text-sm">
          <span className="text-[var(--cs-muted)]">
            {kind === "contract"
              ? "Contract address"
              : kind === "chain"
                ? "Chain id"
                : "Programme"}
          </span>
          <input
            value={value}
            onChange={(event) => setValue(event.target.value)}
            placeholder={
              kind === "contract"
                ? "0x…"
                : kind === "chain"
                  ? "1"
                  : "Example Bug Bounty"
            }
            className="w-full rounded-md border border-[var(--cs-border)] bg-[var(--cs-surface)] px-2 py-1 font-mono text-sm"
          />
        </label>

        {kind !== "contract" ? (
          <label className="block space-y-1 text-sm">
            <span className="text-[var(--cs-muted)]">Chain id</span>
            <input
              value={chainId}
              onChange={(event) => setChainId(event.target.value)}
              className="w-full rounded-md border border-[var(--cs-border)] bg-[var(--cs-surface)] px-2 py-1 font-mono text-sm"
            />
          </label>
        ) : null}

        <label className="block space-y-1 text-sm">
          <span className="text-[var(--cs-muted)]">Where it is published</span>
          <input
            value={reference}
            onChange={(event) => setReference(event.target.value)}
            placeholder="https://…"
            className="w-full rounded-md border border-[var(--cs-border)] bg-[var(--cs-surface)] px-2 py-1 text-sm"
          />
        </label>
      </div>

      <label className="flex items-center gap-2 text-sm text-[var(--cs-muted)]">
        <input
          type="checkbox"
          checked={safeHarbour}
          onChange={(event) => setSafeHarbour(event.target.checked)}
        />
        The programme&rsquo;s safe-harbour rules were read and accepted
      </label>

      <button
        type="button"
        onClick={declare}
        disabled={busy}
        className="rounded-md bg-[var(--cs-accent)] px-3 py-1.5 text-sm font-medium text-[var(--cs-accent-fg)] disabled:opacity-60"
      >
        {busy ? "Recording…" : "Record the declaration"}
      </button>

      {message ? (
        <p
          role={failed ? "alert" : "status"}
          className={
            failed
              ? "text-sm text-[var(--cs-danger)]"
              : "text-sm text-[var(--cs-ok)]"
          }
        >
          {message}
        </p>
      ) : null}
    </section>
  );
}
