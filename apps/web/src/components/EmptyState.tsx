import Link from "next/link";
import type { ReactNode } from "react";

export interface EmptyStateProps {
  title: string;
  description: string;
  /** One clear next action, per the design document's content rules. */
  action?: { label: string; href: string };
  children?: ReactNode;
}

export function EmptyState({ title, description, action, children }: EmptyStateProps) {
  return (
    <div
      role="status"
      className="flex flex-col items-center gap-3 rounded-lg border border-dashed border-[var(--cs-border)] bg-[var(--cs-surface)] px-6 py-12 text-center"
    >
      <p className="text-base font-semibold text-[var(--cs-fg)]">{title}</p>
      <p className="max-w-md text-sm text-[var(--cs-muted)]">{description}</p>
      {action ? (
        <Link
          href={action.href}
          className="mt-1 inline-flex items-center rounded-md bg-[var(--cs-accent)] px-3 py-1.5 text-sm font-semibold text-[var(--cs-accent-fg)] hover:opacity-90 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--cs-accent)]"
        >
          {action.label}
        </Link>
      ) : null}
      {children}
    </div>
  );
}
