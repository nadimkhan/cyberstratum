import { SEVERITY_META } from "@/lib/severity";
import type { Severity } from "@/lib/types";

export interface SeverityBadgeProps {
  severity: Severity;
  /** Optional extra context, e.g. the number of findings. */
  count?: number;
  size?: "sm" | "md";
}

/**
 * The only component that renders severity colour.
 *
 * Colour is never the sole signal: the severity word is always present and
 * the badge carries an `aria-label` for assistive technology.
 */
export function SeverityBadge({ severity, count, size = "md" }: SeverityBadgeProps) {
  const meta = SEVERITY_META[severity];
  const label =
    count === undefined
      ? `${meta.label} severity`
      : `${meta.label} severity, ${count} ${count === 1 ? "finding" : "findings"}`;

  return (
    <span
      role="listitem"
      aria-label={label}
      title={label}
      className={[
        "inline-flex items-center gap-1.5 rounded-full font-medium ring-1 ring-inset",
        meta.badge,
        size === "sm" ? "px-2 py-0.5 text-xs" : "px-2.5 py-1 text-sm",
      ].join(" ")}
    >
      <span aria-hidden="true" className="font-mono uppercase tracking-wide">
        {meta.label}
      </span>
      {count !== undefined ? (
        <span aria-hidden="true" className="font-mono tabular-nums opacity-80">
          {count}
        </span>
      ) : null}
    </span>
  );
}
