import { NextResponse } from "next/server";
import { DEFAULT_SESSION_MAX_AGE_SECONDS, exchangeTicket } from "@/lib/auth";
import { SESSION_COOKIE_NAME } from "@/lib/api";

export const dynamic = "force-dynamic";

/**
 * Complete the Google sign-in handshake.
 *
 * The backend redirects here with a single-use `ticket`. The ticket is
 * exchanged server-side for a session token, which is stored in an HttpOnly
 * cookie. The token is never returned to the browser in the response body,
 * and the ticket is never persisted.
 */
export async function GET(request: Request) {
  const ticket = new URL(request.url).searchParams.get("ticket");

  if (!ticket) {
    return NextResponse.redirect(new URL("/?auth=failed", request.url), 302);
  }

  const result = await exchangeTicket(ticket);

  if (!result.ok) {
    // The failure reason is deliberately not surfaced: it could contain
    // backend detail the browser has no business seeing.
    return NextResponse.redirect(new URL("/?auth=failed", request.url), 302);
  }

  const response = NextResponse.redirect(new URL("/", request.url), 302);
  response.cookies.set({
    name: SESSION_COOKIE_NAME,
    value: result.sessionToken,
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge: result.maxAgeSeconds || DEFAULT_SESSION_MAX_AGE_SECONDS,
  });

  return response;
}
