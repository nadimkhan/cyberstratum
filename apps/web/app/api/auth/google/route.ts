import { NextResponse } from "next/server";
import { googleStartUrl, resolveRequestOrigin } from "@/lib/auth";

export const dynamic = "force-dynamic";

/**
 * Start the Google sign-in handshake.
 *
 * The browser is redirected to the backend's OAuth start endpoint. The
 * backend authenticates the user and redirects back to `redirect_uri` with a
 * one-time ticket, which this app then exchanges for a session.
 *
 * The origin is derived from the request headers (so the same deployment
 * works on Netlify, on localhost and behind a proxy) unless
 * `NEXT_PUBLIC_APP_URL` is configured. No domain is hardcoded.
 */
export async function GET(request: Request) {
  const origin = resolveRequestOrigin(
    request.headers,
    process.env.NEXT_PUBLIC_APP_URL,
  );

  if (!origin) {
    // Without an origin there is no valid redirect target, so the user is
    // sent back to the app with a failure flag rather than a stack trace.
    return NextResponse.redirect(new URL("/?auth=failed", request.url), 302);
  }

  const redirectUri = `${origin}/api/auth/callback`;
  return NextResponse.redirect(googleStartUrl(redirectUri), 302);
}
