import { REVIEW_STATUS_META, SCAN_STATUS_META } from "@/lib/status";
import type { ReviewStatus, ScanStatus } from "@/lib/types";

export interface StatusBadgeProps {
  status: ScanStatus;
  size?: "sm" | "md";
}

/** Scan lifecycle badge. Colour is paired with a text label, never used alone. */
export function StatusBadge({ status, size = "md" }: StatusBadgeProps) {
  const meta = SCAN_STATUS_META[status];
  return (
    <span
      aria-label={`Scan status: ${meta.label}`}
      title={`Scan status: ${meta.label}`}
      className={[
        "inline-flex items-center gap-1.5 rounded-full font-medium ring-1 ring-inset",
        meta.badge,
        size === "sm" ? "px-2 py-0.5 text-xs" : "px-2.5 py-1 text-sm",
      ].join(" ")}
    >
      <span aria-hidden="true" className={`h-2 w-2 rounded-full ${meta.dot}`} />
      {meta.label}
    </span>
  );
}

export interface ReviewStatusBadgeProps {
  status: ReviewStatus;
  size?: "sm" | "md";
}

/** Analyst triage badge for a candidate finding. */
export function ReviewStatusBadge({ status, size = "md" }: ReviewStatusBadgeProps) {
  const meta = REVIEW_STATUS_META[status];
  return (
    <span
      aria-label={`Review status: ${meta.label}`}
      title={`Review status: ${meta.label}`}
      className={[
        "inline-flex items-center rounded-full font-medium ring-1 ring-inset",
        meta.badge,
        size === "sm" ? "px-2 py-0.5 text-xs" : "px-2.5 py-1 text-sm",
      ].join(" ")}
    >
      {meta.label}
    </span>
  );
}
