import { ApiUnreachable } from "@/components/ApiUnreachable";
import {
  API_BASE_URL,
  type ApiError,
  describeApiError,
  getNotices,
} from "@/lib/api";
import type { ThirdPartyComponent } from "@/lib/types";

export const metadata = { title: "Notices" };
export const dynamic = "force-dynamic";

/**
 * Who this product is built on.
 *
 * A notice that only names a licence asks the reader to take the
 * posture on trust, so each component is shown with the three facts
 * that decide it: whether it is imported into this product, whether it
 * is modified, and whether it is ever handed to a customer. A
 * copyleft-licensed tool that is none of those three cannot reach this
 * product's own source, and the reader can see that here rather than
 * being told it.
 */
function facts(component: ThirdPartyComponent): string {
  const used: string[] = [];
  if (component.imported) used.push("imported");
  if (component.modified) used.push("modified");
  if (component.conveyedToCustomers) used.push("handed to customers");
  return used.length > 0 ? used.join(", ") : "never imported, never modified, never shipped";
}

export default async function NoticesPage() {
  const result = await getNotices();

  if (!result.ok) {
    const error: ApiError = result.error;
    return (
      <div className="space-y-4">
        <h1 className="text-2xl font-semibold text-[var(--cs-fg)]">Notices</h1>
        <ApiUnreachable
          title={describeApiError(error).title}
          message={describeApiError(error).message}
          detail={error.detail ?? undefined}
          baseUrl={API_BASE_URL}
        />
      </div>
    );
  }

  const notices = result.data;

  return (
    <div className="space-y-8">
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold text-[var(--cs-fg)]">Notices</h1>
        <p className="text-sm text-[var(--cs-muted)]">{notices.description}</p>
      </header>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold text-[var(--cs-fg)]">Components</h2>
        <ul className="space-y-3">
          {notices.components.map((component) => (
            <li
              key={component.name}
              className="rounded-lg border border-[var(--cs-border)] p-4 space-y-2"
            >
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <p className="text-sm text-[var(--cs-fg)]">
                  <span className="font-semibold">{component.name}</span>{" "}
                  <span className="font-mono text-xs text-[var(--cs-muted)]">
                    {component.version}
                  </span>
                </p>
                <p className="text-xs font-mono text-[var(--cs-muted)]">
                  {component.spdxId}
                </p>
              </div>
              <p className="text-xs text-[var(--cs-muted)]">{component.role}</p>
              <p className="text-sm text-[var(--cs-fg)]">{component.usage}</p>
              <p className="text-xs text-[var(--cs-muted)]">How it is used: {facts(component)}</p>
              {component.note ? (
                <p className="text-xs text-[var(--cs-muted)]">{component.note}</p>
              ) : null}
              <p className="text-xs">
                <a
                  href={component.upstreamUrl}
                  className="text-[var(--cs-accent)] underline"
                  rel="noreferrer noopener"
                  target="_blank"
                >
                  {component.upstreamUrl}
                </a>
                {" · "}
                <a
                  href={component.licenseUrl}
                  className="text-[var(--cs-accent)] underline"
                  rel="noreferrer noopener"
                  target="_blank"
                >
                  licence
                </a>
              </p>
            </li>
          ))}
        </ul>
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold text-[var(--cs-fg)]">Datasets</h2>
        <ul className="space-y-3">
          {notices.datasets.map((dataset) => (
            <li
              key={dataset.dataset}
              className="rounded-lg border border-[var(--cs-border)] p-4 space-y-2"
            >
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <p className="text-sm text-[var(--cs-fg)]">
                  <span className="font-semibold">{dataset.dataset}</span>
                </p>
                <p className="text-xs font-mono text-[var(--cs-muted)]">
                  {dataset.spdxId}
                </p>
              </div>
              <p className="text-xs text-[var(--cs-muted)]">
                Redistribution: {dataset.redistribution}
              </p>
              <p className="text-xs text-[var(--cs-muted)]">
                Derived artifacts may be redistributed:{" "}
                {dataset.derivedArtifactsMayBeRedistributed ? "yes" : "no"}
                {dataset.perRepositoryAuditRequired
                  ? " · this dataset needs a per-repository licence audit before its labels can be used"
                  : ""}
              </p>
              {dataset.note ? (
                <p className="text-xs text-[var(--cs-muted)]">{dataset.note}</p>
              ) : null}
              <p className="text-xs">
                <a
                  href={dataset.upstreamUrl}
                  className="text-[var(--cs-accent)] underline"
                  rel="noreferrer noopener"
                  target="_blank"
                >
                  {dataset.upstreamUrl}
                </a>
                {" · "}
                <a
                  href={dataset.licenseUrl}
                  className="text-[var(--cs-accent)] underline"
                  rel="noreferrer noopener"
                  target="_blank"
                >
                  licence
                </a>
              </p>
            </li>
          ))}
        </ul>
      </section>

      {notices.note ? (
        <p className="text-xs text-[var(--cs-muted)]">{notices.note}</p>
      ) : null}
    </div>
  );
}
