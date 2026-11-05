import Link from "next/link";

export interface SignInButtonProps {
  /** Email of the signed-in user, or `null` when nobody is signed in. */
  email?: string | null;
  /** Optional display name, shown ahead of the email when present. */
  displayName?: string | null;
}

/**
 * The sign-in control.
 *
 * Signed out, it offers Google sign-in: the link goes to this app's own
 * `/api/auth/google` route, which redirects to the backend, which redirects
 * back with a one-time ticket. No credential is ever handled in the browser.
 *
 * Signed in, it shows who is signed in and offers a sign-out button. Sign-out
 * is a plain POST form so it works without client-side JavaScript.
 */
export function SignInButton({ email, displayName }: SignInButtonProps) {
  if (!email) {
    return (
      <Link
        href="/api/auth/google"
        className="rounded-md border border-[var(--cs-border)] bg-[var(--cs-surface)] px-3 py-2 text-sm font-medium text-[var(--cs-fg)] hover:border-[var(--cs-accent)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--cs-accent)]"
      >
        Sign in with Google
      </Link>
    );
  }

  return (
    <div className="flex items-center gap-3">
      <span className="text-sm text-[var(--cs-muted)]">
        <span className="text-[var(--cs-fg)]">{displayName || email}</span>
        {displayName ? ` · ${email}` : null}
      </span>
      <form method="post" action="/api/auth/logout">
        <button
          type="submit"
          className="rounded-md border border-[var(--cs-border)] bg-[var(--cs-surface)] px-3 py-2 text-sm font-medium text-[var(--cs-muted)] hover:border-[var(--cs-accent)] hover:text-[var(--cs-fg)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--cs-accent)]"
        >
          Sign out
        </button>
      </form>
    </div>
  );
}
