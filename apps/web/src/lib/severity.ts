import { SEVERITY_ORDER, type Severity, type SeverityCounts } from "./types";

/** The single place where severity colour is defined.
 *
 * Every component that renders severity must consume `SEVERITY_META` (or the
 * `SeverityBadge` component) rather than introducing its own colour, so the
 * palette stays consistent and stays WCAG AA compliant.
 */
export interface SeverityMeta {
  label: string;
  /** Tailwind classes for a filled badge. */
  badge: string;
  /** Tailwind classes for a low-emphasis (outline) variant. */
  outline: string;
  /** Text colour class used for severity words in tables and charts. */
  text: string;
  /** Numeric weight used when estimating a risk score. */
  weight: number;
}

export const SEVERITY_META: Record<Severity, SeverityMeta> = {
  critical: {
    label: "Critical",
    badge: "bg-red-100 text-red-900 ring-red-700/40 dark:bg-red-500/20 dark:text-red-100",
    outline: "text-red-800 ring-red-700/40 dark:text-red-200",
    text: "text-red-800 dark:text-red-300",
    weight: 40,
  },
  high: {
    label: "High",
    badge: "bg-orange-100 text-orange-900 ring-orange-700/40 dark:bg-orange-500/20 dark:text-orange-100",
    outline: "text-orange-800 ring-orange-700/40 dark:text-orange-200",
    text: "text-orange-800 dark:text-orange-300",
    weight: 20,
  },
  medium: {
    label: "Medium",
    badge: "bg-yellow-100 text-yellow-900 ring-yellow-700/40 dark:bg-yellow-500/20 dark:text-yellow-100",
    outline: "text-yellow-900 ring-yellow-700/40 dark:text-yellow-200",
    text: "text-yellow-900 dark:text-yellow-300",
    weight: 8,
  },
  low: {
    label: "Low",
    badge: "bg-sky-100 text-sky-900 ring-sky-700/40 dark:bg-sky-500/20 dark:text-sky-100",
    outline: "text-sky-800 ring-sky-700/40 dark:text-sky-200",
    text: "text-sky-800 dark:text-sky-300",
    weight: 3,
  },
  info: {
    label: "Info",
    badge: "bg-cyan-100 text-cyan-900 ring-cyan-700/40 dark:bg-cyan-500/25 dark:text-cyan-100",
    outline: "text-cyan-800 ring-cyan-700/40 dark:text-cyan-200",
    text: "text-cyan-800 dark:text-cyan-300",
    weight: 1,
  },
};

/**
 * Colours used by the severity badge, as concrete hex values.
 *
 * These mirror the Tailwind classes in `SEVERITY_META` and exist so the
 * accessibility test can compute real WCAG contrast ratios. Keep the two in
 * sync: `severity-colours.test.ts` asserts the palette is WCAG AA compliant
 * and that no other file defines a severity colour.
 */
export interface SeverityPalette {
  /** Badge background in the light palette. */
  lightBg: string;
  /** Badge text in the light palette. */
  lightFg: string;
  /** Badge background in the dark palette (composited over `--cs-surface`). */
  darkBg: string;
  /** Badge text in the dark palette. */
  darkFg: string;
}

export const SEVERITY_PALETTE: Record<Severity, SeverityPalette> = {
  critical: {
    lightBg: "#fee2e2",
    lightFg: "#7f1d1d",
    darkBg: "#411d20",
    darkFg: "#fee2e2",
  },
  high: {
    lightBg: "#ffedd5",
    lightFg: "#7c2d12",
    darkBg: "#412a15",
    darkFg: "#ffedd5",
  },
  medium: {
    lightBg: "#fef9c3",
    lightFg: "#713f12",
    darkBg: "#414123",
    darkFg: "#fef9c3",
  },
  low: {
    lightBg: "#e0f2fe",
    lightFg: "#0c4a6e",
    darkBg: "#0e3545",
    darkFg: "#e0f2fe",
  },
  info: {
    lightBg: "#cffafe",
    lightFg: "#164e63",
    darkBg: "#0f4048",
    darkFg: "#cffafe",
  },
};

/** Human-readable labels for every severity, used by filter controls. */
export const SEVERITY_LABELS: { value: Severity; label: string }[] = SEVERITY_ORDER.map(
  (s) => ({ value: s, label: SEVERITY_META[s].label }),
);

const SEVERITY_ALIASES: Record<string, Severity> = {
  critical: "critical",
  crit: "critical",
  blocker: "critical",
  high: "high",
  medium: "medium",
  med: "medium",
  moderate: "medium",
  low: "low",
  info: "info",
  informational: "info",
  information: "info",
  note: "info",
  none: "info",
  unknown: "info",
};

/** Normalise any severity string from the backend into the canonical taxonomy. */
export function toSeverity(value: unknown): Severity {
  if (typeof value !== "string") return "info";
  const key = value.trim().toLowerCase().replace(/[\s-]+/g, "_");
  if (key in SEVERITY_ALIASES) return SEVERITY_ALIASES[key];
  // Tolerate suffixes such as "medium_severity".
  const withoutSuffix = key.replace(/_(severity|level)$/, "");
  if (withoutSuffix in SEVERITY_ALIASES) return SEVERITY_ALIASES[withoutSuffix];
  return "info";
}

/** An empty severity histogram. */
export function emptySeverityCounts(): SeverityCounts {
  return { critical: 0, high: 0, medium: 0, low: 0, info: 0 };
}

/** Sum a list of severity labels into a histogram. */
export function countSeverities(values: readonly unknown[]): SeverityCounts {
  const counts = emptySeverityCounts();
  for (const value of values) counts[toSeverity(value)] += 1;
  return counts;
}

/**
 * Estimate a 0-100 risk score from a severity histogram.
 *
 * Used only when the backend does not supply its own risk score; the UI marks
 * such values as "estimated" so operators are never misled.
 */
export function estimateRiskScore(counts: SeverityCounts): number {
  let raw = 0;
  for (const severity of SEVERITY_ORDER) raw += counts[severity] * SEVERITY_META[severity].weight;
  // Saturating curve: 100 raw points maps to a score of 100.
  return Math.round(100 * (1 - Math.exp(-raw / 100)));
}
