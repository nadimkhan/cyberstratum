import { NextResponse } from "next/server";
import { signOut } from "@/lib/auth";
import { SESSION_COOKIE_NAME } from "@/lib/api";

export const dynamic = "force-dynamic";

/**
 * End the human session.
 *
 * The backend session is revoked with the bearer token, and the local cookie
 * is cleared regardless of what the backend says: a cookie the backend has
 * already forgotten is better than a cookie that outlives the session.
 */
export async function POST(request: Request) {
  await signOut();

  const response = NextResponse.redirect(new URL("/", request.url), 302);
  response.cookies.set({
    name: SESSION_COOKIE_NAME,
    value: "",
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge: 0,
  });

  return response;
}
