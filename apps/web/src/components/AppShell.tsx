import Link from "next/link";
import type { ReactNode } from "react";

const NAV_ITEMS: { href: string; label: string }[] = [
  { href: "/", label: "Overview" },
  { href: "/scans", label: "Scans" },
  { href: "/assets", label: "Assets" },
  { href: "/findings", label: "Findings" },
  { href: "/triage", label: "Triage" },
  { href: "/learning", label: "Learning" },
  { href: "/scope", label: "Scope" },
  { href: "/discovery", label: "Discovery" },
  { href: "/reproducibility", label: "Reproducibility" },
  { href: "/scans/new", label: "New scan" },
];

/**
 * Global shell: sidebar navigation plus the main content region
 * (design document section 11.1).
 */
export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col md:flex-row">
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded focus:bg-[var(--cs-accent)] focus:px-3 focus:py-2 focus:text-[var(--cs-accent-fg)]"
      >
        Skip to main content
      </a>

      <nav
        aria-label="Primary"
        className="border-b border-[var(--cs-border)] bg-[var(--cs-surface)] md:w-56 md:shrink-0 md:border-b-0 md:border-r"
      >
        <div className="px-4 py-4">
          <Link
            href="/"
            className="block rounded text-lg font-semibold tracking-tight text-[var(--cs-fg)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--cs-accent)]"
          >
            CyberStratum
          </Link>
          <p className="mt-0.5 text-xs text-[var(--cs-muted)]">
            Analyse bytecode. Review evidence.
          </p>
        </div>
        <ul className="px-2 pb-3 md:px-3">
          {NAV_ITEMS.map((item) => (
            <li key={item.href}>
              <Link
                href={item.href}
                className="block rounded-md px-3 py-2 text-sm text-[var(--cs-muted)] hover:bg-[var(--cs-raised)] hover:text-[var(--cs-fg)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--cs-accent)]"
              >
                {item.label}
              </Link>
            </li>
          ))}
        </ul>
      </nav>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-3 border-b border-[var(--cs-border)] bg-[var(--cs-surface)] px-4 py-3">
          <span className="rounded-full bg-[var(--cs-raised)] px-2.5 py-1 text-xs font-medium text-[var(--cs-muted)]">
            local environment
          </span>
          <p className="text-xs text-[var(--cs-muted)]">
            Candidate findings require analyst validation before they are treated as confirmed.
          </p>
        </header>
        <main id="main-content" className="min-w-0 flex-1 px-4 py-6 md:px-8">
          {children}
        </main>
      </div>
    </div>
  );
}