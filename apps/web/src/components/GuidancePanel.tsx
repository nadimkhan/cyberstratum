import type { Guidance } from "@/lib/types";

/**
 * The explanation that belongs to a finding.
 *
 * It says what the pattern is, why it matters, what to change, and when
 * the pattern is expected -- the last of which is what keeps the
 * product from crying wolf.
 *
 * It is used in two places on purpose: beside a finding, and inside the
 * triage queue, where a reviewer decides whether the finding is real.
 * The advice is what makes that decision possible without a search.
 */
export function GuidancePanel({ guidance }: { guidance?: Guidance }) {
  if (!guidance) return null;
  return (
    <details className="mt-2 max-w-prose rounded border border-[var(--cs-border)] bg-[var(--cs-raised)] px-2 py-1.5 text-xs text-[var(--cs-muted)]">
      <summary className="cursor-pointer font-medium text-[var(--cs-fg)]">
        What this means, and what to do about it
      </summary>
      <dl className="mt-2 space-y-2">
        <div>
          <dt className="font-semibold text-[var(--cs-fg)]">What it means</dt>
          <dd>{guidance.whatItMeans}</dd>
        </div>
        <div>
          <dt className="font-semibold text-[var(--cs-fg)]">Why it matters</dt>
          <dd>{guidance.whyItMatters}</dd>
        </div>
        <div>
          <dt className="font-semibold text-[var(--cs-fg)]">How to fix it</dt>
          <dd>{guidance.howToFix}</dd>
        </div>
        <div>
          <dt className="font-semibold text-[var(--cs-fg)]">When it is not a problem</dt>
          <dd>{guidance.falsePositivePatterns}</dd>
        </div>
        <div>
          <dt className="font-semibold text-[var(--cs-fg)]">References</dt>
          <dd>{guidance.references}</dd>
        </div>
      </dl>
    </details>
  );
}
