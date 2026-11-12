import Link from "next/link";
import { ApiUnreachable } from "@/components/ApiUnreachable";
import { ScopeGrantForm } from "@/components/ScopeGrantForm";
import { ScopeGrantList } from "@/components/ScopeGrantList";
import {
  API_BASE_URL,
  type ApiError,
  type ApiResult,
  describeApiError,
  listScopeGrants,
  listWorkspaces,
} from "@/lib/api";
import type { ScopeGrantSummary } from "@/lib/types";

export const metadata = { title: "Authorised scope" };
export const dynamic = "force-dynamic";

/**
 * What this workspace is allowed to look at.
 *
 * A workspace declares the programmes, chains and contracts that are in
 * bounds for it. The product records, at the moment a scan is queued,
 * what that declaration said about the target — so a report can say
 * whether the analysis was made with permission or not.
 *
 * There are three answers and only three: in scope, out of scope, and
 * unknown. Unknown is the one that matters. A workspace that has
 * declared nothing has neither been permitted nor refused, and the
 * product says so rather than choosing for it.
 *
 * The workspace is chosen rather than assumed. A declaration belongs to
 * one tenant, and an operator who does not say whose scope they are
 * reading is reading the wrong one.
 */
export default async function ScopePage({
  searchParams,
}: {
  searchParams: Promise<{ workspace?: string }>;
}) {
  const { workspace: requested } = await searchParams;
  const [workspacesResult] = await Promise.all([listWorkspaces()]);

  if (!workspacesResult.ok) {
    const error: ApiError = workspacesResult.error;
    return (
      <div className="space-y-4">
        <h1 className="text-2xl font-semibold text-[var(--cs-fg)]">
          Authorised scope
        </h1>
        <ApiUnreachable
          title={describeApiError(error).title}
          message={describeApiError(error).message}
          detail={error.detail ?? undefined}
          baseUrl={API_BASE_URL}
        />
      </div>
    );
  }

  const workspaces = workspacesResult.data;
  const chosen =
    workspaces.find((workspace) => workspace.id === requested) ?? workspaces[0];

  const grantsResult: ApiResult<ScopeGrantSummary[]> = chosen
    ? await listScopeGrants(chosen.id)
    : { ok: true, data: [] };

  if (!grantsResult.ok) {
    const error: ApiError = grantsResult.error;
    return (
      <div className="space-y-4">
        <h1 className="text-2xl font-semibold text-[var(--cs-fg)]">
          Authorised scope
        </h1>
        <ApiUnreachable
          title={describeApiError(error).title}
          message={describeApiError(error).message}
          detail={error.detail ?? undefined}
          baseUrl={API_BASE_URL}
        />
      </div>
    );
  }

  const grants = grantsResult.data;

  return (
    <div className="space-y-8">
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold text-[var(--cs-fg)]">
          Authorised scope
        </h1>
        <p className="text-sm text-[var(--cs-muted)]">
          What a workspace is allowed to examine and disclose. Until a
          declaration exists, every scan it queues is recorded as
          &ldquo;scope unknown&rdquo; &mdash; which is neither permission nor
          refusal, and is never quietly read as permission.
        </p>
      </header>

      {workspaces.length > 1 ? (
        <nav aria-label="Workspace" className="space-y-2">
          <p className="text-sm text-[var(--cs-muted)]">
            A declaration belongs to one workspace, so choose whose scope you
            are reading.
          </p>
          <ul className="flex flex-wrap gap-2">
            {workspaces.map((workspace) => {
              const active = chosen?.id === workspace.id;
              return (
                <li key={workspace.id}>
                  <Link
                    href={`/scope?workspace=${encodeURIComponent(workspace.id)}`}
                    aria-current={active ? "page" : undefined}
                    className={
                      active
                        ? "rounded-md border border-[var(--cs-accent)] bg-[var(--cs-raised)] px-3 py-1 text-sm text-[var(--cs-fg)]"
                        : "rounded-md border border-[var(--cs-border)] px-3 py-1 text-sm text-[var(--cs-muted)] hover:text-[var(--cs-fg)]"
                    }
                  >
                    {workspace.name}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>
      ) : null}

      {chosen ? (
        <p className="text-sm text-[var(--cs-muted)]">
          The scope of <span className="font-medium text-[var(--cs-fg)]">{chosen.name}</span>.
        </p>
      ) : null}

      <section aria-labelledby="grants-heading" className="space-y-3">
        <h2 id="grants-heading" className="text-lg font-medium text-[var(--cs-fg)]">
          What has been declared
        </h2>
        {grants.length === 0 ? (
          <p className="rounded-lg border border-[var(--cs-border)] p-4 text-sm text-[var(--cs-muted)]">
            Nothing has been declared. Every scan this workspace queues will be
            recorded as &ldquo;scope unknown&rdquo;, and its report will say
            that the analysis is not authorised for disclosure.
          </p>
        ) : (
          <ScopeGrantList grants={grants} workspaceId={chosen?.id ?? ""} />
        )}
      </section>

      {chosen ? (
        <ScopeGrantForm workspaceId={chosen.id} />
      ) : (
        <p className="text-sm text-[var(--cs-muted)]">
          There is no workspace to declare a scope for.
        </p>
      )}

      <p className="text-xs text-[var(--cs-muted)]">
        Declaring a scope does not authorise anything else. Transactions, exploit
        execution and disclosure submission stay disabled without explicit
        authorisation.
      </p>
    </div>
  );
}
