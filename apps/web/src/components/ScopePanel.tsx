import type { ScopeStatus } from "@/lib/types";

/**
 * The authorisation a scan was made under.
 *
 * Three honest answers, and only three:
 *
 * - in scope: the workspace had declared this target, so what was found
 *   may be disclosed under that programme.
 * - out of scope: the workspace had declared a scope, and this target was
 *   not in it. The analysis may exist, but it is not the workspace's to
 *   disclose.
 * - unknown: the workspace had declared no scope at all. Nothing is
 *   known either way, and unknown is never quietly read as permission.
 *
 * The panel says which of the three applies. It never turns "unknown"
 * into a green light.
 */
export function ScopePanel({ status }: { status: ScopeStatus }) {
  const tone =
    status === "in_scope"
      ? {
          border: "var(--cs-ok)",
          background: "var(--cs-ok-soft)",
          foreground: "var(--cs-ok)",
          label: "In scope",
          note: "This target was covered by an authorised scope grant when the scan was queued.",
        }
      : status === "out_of_scope"
        ? {
            border: "var(--cs-warning)",
            background: "var(--cs-warning-soft)",
            foreground: "var(--cs-warning)",
            label: "Out of scope",
            note: "The workspace declared a scope, and this target was not covered by it. The analysis is not authorised for disclosure.",
          }
        : {
            border: "var(--cs-border)",
            background: "var(--cs-surface)",
            foreground: "var(--cs-muted)",
            label: "Scope unknown",
            note: "No scope has been declared for this workspace, so nothing is known about authorisation either way. This is not permission.",
          };

  return (
    <section
      aria-label="Authorised scope"
      className="rounded-lg border bg-[var(--cs-surface)] p-4"
      style={{ borderColor: tone.border, background: tone.background }}
    >
      <div className="flex flex-wrap items-baseline gap-2">
        <h2 className="text-sm font-semibold" style={{ color: tone.foreground }}>
          {tone.label}
        </h2>
        <span className="text-xs text-[var(--cs-muted)]">Authorised scope</span>
      </div>
      <p className="mt-1 text-sm text-[var(--cs-muted)]">{tone.note}</p>
    </section>
  );
}
