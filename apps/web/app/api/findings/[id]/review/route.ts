import { NextResponse } from "next/server";
import { reviewFinding } from "@/lib/api";

export const dynamic = "force-dynamic";

/**
 * Server-side proxy for a human review verdict.
 *
 * The browser posts here; the request to the FastAPI backend is made from
 * the server so the `X-API-Key` stays out of the client bundle and the
 * session cookie stays in the browser.
 *
 * A verdict made here is the label the machine learning pipeline learns
 * from, so the route refuses to invent one: the backend requires a reason
 * for a false-positive verdict, and this route passes the reviewer's
 * note through untouched.
 */
export async function POST(
  request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;

  let body: { status?: string; note?: string | null };
  try {
    body = (await request.json()) as { status?: string; note?: string | null };
  } catch {
    return NextResponse.json(
      { detail: "The request body could not be read as JSON." },
      { status: 400 },
    );
  }

  const status = body.status;
  if (
    status !== "confirmed" &&
    status !== "false_positive" &&
    status !== "needs_more_evidence" &&
    status !== "triage"
  ) {
    return NextResponse.json(
      { detail: "That is not a review verdict." },
      { status: 422 },
    );
  }

  const result = await reviewFinding(id, {
    status,
    note: body.note ?? null,
  });
  if (!result.ok) {
    const statusCode =
      result.error.kind === "network" ? 503 : (result.error.status ?? 502);
    return NextResponse.json(
      {
        detail: result.error.detail ?? result.error.message,
        kind: result.error.kind,
      },
      { status: statusCode },
    );
  }

  return NextResponse.json(result.data, { status: 200 });
}
