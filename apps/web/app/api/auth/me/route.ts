import { NextResponse } from "next/server";
import { fetchCurrentUser } from "@/lib/auth";

export const dynamic = "force-dynamic";

/**
 * Report the signed-in user.
 *
 * Returns the user and their workspace when a valid session cookie is
 * present, and `401` when there is no session. The session token itself is
 * never part of the response body.
 */
export async function GET() {
  const session = await fetchCurrentUser();

  if (!session) {
    return NextResponse.json({ detail: "Not signed in." }, { status: 401 });
  }

  return NextResponse.json(
    {
      user: session.user,
      workspace: session.workspace,
      expires_at: session.expiresAt,
    },
    { status: 200, headers: { "Cache-Control": "no-store" } },
  );
}
