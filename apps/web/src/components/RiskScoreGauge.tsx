import { formatRiskScore } from "@/lib/format";

export interface RiskScoreGaugeProps {
  /** Risk score on a 0-100 scale. `null` renders an unknown state. */
  score: number | null;
  /** True when the score was derived locally rather than supplied by the API. */
  estimated?: boolean;
  label?: string;
  size?: number;
}

/**
 * Accessible risk-score gauge.
 *
 * The value is exposed as text as well as through the SVG, so screen readers
 * never depend on the graphic.
 */
export function RiskScoreGauge({
  score,
  estimated = false,
  label = "Risk score",
  size = 120,
}: RiskScoreGaugeProps) {
  const clamped = score === null ? null : Math.max(0, Math.min(100, score));
  const radius = 46;
  const circumference = Math.PI * radius; // semicircle
  const fraction = clamped === null ? 0 : clamped / 100;
  const dash = circumference * fraction;
  const display = clamped === null ? "—" : formatRiskScore(clamped);

  return (
    <figure className="flex flex-col items-center">
      <svg
        width={size}
        height={size / 2 + 18}
        viewBox="0 0 120 78"
        role="img"
        aria-label={`${label}: ${display}${estimated ? " (estimated)" : ""} out of 100`}
      >
        <path
          d="M 14 68 A 46 46 0 0 1 106 68"
          fill="none"
          stroke="var(--cs-border)"
          strokeWidth="10"
          strokeLinecap="round"
        />
        {clamped !== null ? (
          <path
            d="M 14 68 A 46 46 0 0 1 106 68"
            fill="none"
            stroke="var(--cs-accent)"
            strokeWidth="10"
            strokeLinecap="round"
            strokeDasharray={`${dash} ${circumference}`}
          />
        ) : null}
        <text
          x="60"
          y="60"
          textAnchor="middle"
          className="fill-[var(--cs-fg)] font-mono text-2xl font-semibold"
        >
          {display}
        </text>
      </svg>
      <figcaption className="mt-1 text-center text-xs text-[var(--cs-muted)]">
        {label}
        {estimated ? " (estimated)" : null}
      </figcaption>
    </figure>
  );
}
