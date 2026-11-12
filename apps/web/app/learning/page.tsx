import { ApiUnreachable } from "@/components/ApiUnreachable";
import {
  API_BASE_URL,
  type ApiError,
  describeApiError,
  getLearningStatus,
} from "@/lib/api";

export const metadata = { title: "Learning" };
export const dynamic = "force-dynamic";

/**
 * What the model has been given to work with.
 *
 * The model ranks findings; it never decides a verdict. It is only
 * installed when the reviewed corpus is large enough to be judged on
 * held-out families, and when it is refused the reason is shown here
 * rather than hidden in a log.
 */
export default async function LearningPage() {
  const result = await getLearningStatus();

  if (!result.ok) {
    const error: ApiError = result.error;
    return (
      <div className="space-y-4">
        <h1 className="text-2xl font-semibold text-[var(--cs-fg)]">Learning</h1>
        <ApiUnreachable
          title={describeApiError(error).title}
          message={describeApiError(error).message}
          detail={error.detail ?? undefined}
          baseUrl={API_BASE_URL}
        />
      </div>
    );
  }

  const status = result.data;
  const reviewed = status.reviewed;
  const cycle = status.lastCycle;
  const model = status.model;

  const facts: Array<[string, string]> = [
    ["Reviewed findings", String(reviewed.total)],
    ["Confirmed", String(reviewed.confirmed)],
    ["False positives", String(reviewed.falsePositive)],
    ["Contracts settled", String(reviewed.contracts)],
    ["Issue categories", String(reviewed.categories)],
  ];

  return (
    <div className="space-y-8">
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold text-[var(--cs-fg)]">Learning</h1>
        <p className="text-sm text-[var(--cs-muted)]">
          The model ranks findings; it never decides a verdict. It is installed
          only when the reviewed corpus is large enough to be judged on held-out
          families, and when it is refused the reason is written down.
        </p>
      </header>

      <section aria-labelledby="reviewed-heading" className="space-y-3">
        <h2
          id="reviewed-heading"
          className="text-lg font-medium text-[var(--cs-fg)]"
        >
          What has been reviewed
        </h2>
        <dl className="grid gap-3 sm:grid-cols-3">
          {facts.map(([label, value]) => (
            <div
              key={label}
              className="rounded-lg border border-[var(--cs-border)] p-4"
            >
              <dt className="text-sm text-[var(--cs-muted)]">{label}</dt>
              <dd className="text-2xl font-semibold text-[var(--cs-fg)]">{value}</dd>
            </div>
          ))}
        </dl>
        <p className="text-sm text-[var(--cs-muted)]">
          A review is a person&rsquo;s decision. Only those decisions are
          training truth, so this number moves only as people settle findings
          in triage.
        </p>
      </section>

      <section aria-labelledby="model-heading" className="space-y-3">
        <h2 id="model-heading" className="text-lg font-medium text-[var(--cs-fg)]">
          The model
        </h2>
        {model ? (
          <div className="space-y-2 rounded-lg border border-[var(--cs-border)] p-4">
            <p className="text-sm text-[var(--cs-fg)]">
              Installed &mdash; <code>{model.manifestId || "unnamed manifest"}</code>
            </p>
            {Object.entries(model.payload)
              .filter(([, value]) =>
                ["number", "string", "boolean"].includes(typeof value),
              )
              .slice(0, 8)
              .map(([key, value]) => (
                <p key={key} className="text-sm text-[var(--cs-muted)]">
                  {key.replace(/_/g, " ")}: {String(value)}
                </p>
              ))}
          </div>
        ) : (
          <div className="space-y-2 rounded-lg border border-[var(--cs-border)] p-4">
            <p className="text-sm text-[var(--cs-fg)]">No model is installed.</p>
            <p className="text-sm text-[var(--cs-muted)]">
              Nothing is ranked, and nothing is decided, until the reviewed
              corpus can be judged. Every finding still gets its severity and
              its evidence from the rules.
            </p>
          </div>
        )}
      </section>

      <section aria-labelledby="cycle-heading" className="space-y-3">
        <h2 id="cycle-heading" className="text-lg font-medium text-[var(--cs-fg)]">
          The last learning cycle
        </h2>
        {cycle ? (
          <div className="space-y-2 rounded-lg border border-[var(--cs-border)] p-4">
            <p className="text-sm text-[var(--cs-fg)]">
              {cycle.records} contract{cycle.records === 1 ? "" : "s"} exported
              from the reviewed labels &mdash;{" "}
              {cycle.promotable ? "promotable" : "not promotable"}
              {cycle.installed ? ", and installed" : ""}.
            </p>
            {cycle.gateReason ? (
              <p className="text-sm text-[var(--cs-muted)]">{cycle.gateReason}</p>
            ) : null}
          </div>
        ) : (
          <div className="space-y-2 rounded-lg border border-[var(--cs-border)] p-4">
            <p className="text-sm text-[var(--cs-fg)]">
              No learning cycle has been run yet.
            </p>
            <p className="text-sm text-[var(--cs-muted)]">
              The cycle exports the reviewed labels, trains a candidate, and
              measures it on families it has not seen. It refuses to install a
              model that cannot be shown to be precise.
            </p>
          </div>
        )}
      </section>
    </div>
  );
}
