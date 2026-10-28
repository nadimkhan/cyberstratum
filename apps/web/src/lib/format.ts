/** Shared display formatters.
 *
 * All of these are pure and safe to run on the server or the client.
 */

/** Format an ISO timestamp in the user's locale (UTC values are stored, UTC assumed). */
export function formatDateTime(value: string | number | Date | null | undefined): string {
  const date = toDate(value);
  if (!date) return "—";
  return new Intl.DateTimeFormat("en-GB", {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "UTC",
  }).format(date);
}

/** Short date only, e.g. `12 Mar 2026`. */
export function formatDate(value: string | number | Date | null | undefined): string {
  const date = toDate(value);
  if (!date) return "—";
  return new Intl.DateTimeFormat("en-GB", {
    year: "numeric",
    month: "short",
    day: "2-digit",
    timeZone: "UTC",
  }).format(date);
}

/** Relative time such as `3 minutes ago` / `in 2 days`. */
export function formatRelativeTime(
  value: string | number | Date | null | undefined,
  now: Date = new Date(),
): string {
  const date = toDate(value);
  if (!date) return "—";
  const deltaSeconds = Math.round((date.getTime() - now.getTime()) / 1000);
  const absolute = Math.abs(deltaSeconds);
  const units: [Intl.RelativeTimeFormatUnit, number][] = [
    ["second", 60],
    ["minute", 60],
    ["hour", 24],
    ["day", 7],
    ["week", 4.34524],
    ["month", 12],
    ["year", Number.POSITIVE_INFINITY],
  ];
  let amount = deltaSeconds;
  for (const [unit, limit] of units) {
    if (Math.abs(amount) < limit || unit === "year") {
      return new Intl.RelativeTimeFormat("en", { numeric: "auto" }).format(
        Math.round(amount),
        unit,
      );
    }
    amount /= limit;
  }
  return new Intl.RelativeTimeFormat("en", { numeric: "auto" }).format(
    Math.round(amount),
    "year",
  );
  void absolute;
}

const BYTE_UNITS = ["B", "KB", "MB", "GB", "TB"];

/** Human-readable byte size, e.g. `1.4 KB`. */
export function formatBytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined || !Number.isFinite(bytes)) return "—";
  if (bytes < 0) return "—";
  let value = bytes;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < BYTE_UNITS.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  const decimals = unitIndex === 0 ? 0 : value < 10 ? 1 : 0;
  return `${value.toFixed(decimals)} ${BYTE_UNITS[unitIndex]}`;
}

/** Shorten a sha256/keccak hash to `0x1234abcd…ef12`. */
export function shortHash(hash: string | null | undefined, lead = 6, tail = 4): string {
  if (!hash) return "—";
  const trimmed = hash.trim();
  if (trimmed.length <= lead + tail + 1) return trimmed;
  return `${trimmed.slice(0, lead)}…${trimmed.slice(-tail)}`;
}

/** Shorten a contract address to `0x1234…abcd`, keeping the `0x` prefix. */
export function shortAddress(address: string | null | undefined): string {
  if (!address) return "—";
  const trimmed = address.trim();
  if (trimmed.length <= 12) return trimmed;
  return `${trimmed.slice(0, 6)}…${trimmed.slice(-4)}`;
}

/** Format a chain id, e.g. `1 (mainnet)` when the chain is known. */
export function formatChainId(chainId: number | null | undefined): string {
  if (chainId === null || chainId === undefined || !Number.isFinite(chainId)) return "—";
  const known: Record<number, string> = {
    1: "mainnet",
    10: "optimism",
    56: "bnb",
    137: "polygon",
    8453: "base",
    42161: "arbitrum",
    11155111: "sepolia",
  };
  const name = known[chainId];
  return name ? `${chainId} (${name})` : String(chainId);
}

/** Format a duration in milliseconds, e.g. `1.2 s` or `340 ms`. */
export function formatDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || !Number.isFinite(ms) || ms < 0) return "—";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  const seconds = ms / 1000;
  if (seconds < 60) return `${seconds.toFixed(1)} s`;
  const minutes = Math.floor(seconds / 60);
  const rest = Math.round(seconds % 60);
  return `${minutes}m ${rest}s`;
}

/** Format a 0..1 confidence as a percentage, e.g. `72%`. */
export function formatConfidence(confidence: number | null | undefined): string {
  if (confidence === null || confidence === undefined || !Number.isFinite(confidence)) return "—";
  const percent = confidence <= 1 ? confidence * 100 : confidence;
  return `${Math.round(percent)}%`;
}

/** Format a risk score (0-100) with one decimal place. */
export function formatRiskScore(score: number | null | undefined): string {
  if (score === null || score === undefined || !Number.isFinite(score)) return "—";
  return score.toFixed(1);
}

/** Truncate a long string with an ellipsis. */
export function truncate(value: string | null | undefined, max = 80): string {
  if (!value) return "—";
  if (value.length <= max) return value;
  return `${value.slice(0, max - 1)}…`;
}

/** Convert a comma or whitespace separated label list into a trimmed array. */
export function parseLabels(value: string | null | undefined): string[] {
  if (!value) return [];
  return value
    .split(/[,\n]/)
    .map((label) => label.trim())
    .filter((label) => label.length > 0);
}

/** Join labels for display. */
export function formatLabels(labels: readonly string[] | null | undefined): string {
  if (!labels || labels.length === 0) return "—";
  return labels.join(", ");
}

function toDate(value: string | number | Date | null | undefined): Date | null {
  if (value === null || value === undefined || value === "") return null;
  const date = value instanceof Date ? value : new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}
