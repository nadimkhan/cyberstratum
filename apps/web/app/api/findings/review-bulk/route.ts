import { NextResponse } from "next/server";
import { reviewFindingsBulk } from "@/lib/api";

export const dynamic = "force-dynamic";

/**
 * Server-side proxy for a verdict applied to many findings.
 *
 * The browser posts here; the request to the FastAPI backend is made
 * from the server, so the `X-API-Key` stays out of the client bundle
 * and the session cookie stays in the browser.
 *
 * The workspace is named in the request because a verdict belongs to
 * one tenant: a bulk action that reached every tenant would not be a
 * verdict. The backend refuses a bulk action whose workspace is not
 * known, so this route passes the reviewer's choice through untouched.
 */
export async function POST(request: Request) {
  let body: {
    detector_id?: string;
    status?: string;
    note?: string | null;
    workspace_id?: string | null;
  };
  try {
    body = (await request.json()) as {
      detector_id?: string;
      status?: string;
      note?: string | null;
      workspace_id?: string | null;
    };
  } catch {
    return NextResponse.json(
      { detail: "The request body could not be read as JSON." },
      { status: 400 },
    );
  }

  const detectorId = (body.detector_id ?? "").trim();
  if (!detectorId) {
    return NextResponse.json({ detail: "A detector id is required." }, { status: 422 });
  }

  const status = body.status;
  if (
    status !== "confirmed" &&
    status !== "false_positive" &&
    status !== "needs_more_evidence" &&
    status !== "triage"
  ) {
    return NextResponse.json({ detail: "That is not a review verdict." }, { status: 422 });
  }

  const result = await reviewFindingsBulk(
    detectorId,
    { status, note: body.note ?? null },
    body.workspace_id ?? null,
  );
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
