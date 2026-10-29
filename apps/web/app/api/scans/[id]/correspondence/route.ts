import { NextResponse } from "next/server";
import { triggerCorrespondence } from "@/lib/api";

export const dynamic = "force-dynamic";

/**
 * Server-side proxy for the on-demand source-to-bytecode correspondence proof.
 *
 * The browser posts here; the request to the FastAPI backend is made from
 * the server so the `X-API-Key` stays out of the client bundle.
 *
 * The response reports that the work was *queued*. It licenses no source
 * claim: only a proof with the `established` status does that, and a missing
 * proof is not evidence of a mismatch.
 */
export async function POST(
  _request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;

  const result = await triggerCorrespondence(id);
  if (!result.ok) {
    const status =
      result.error.kind === "network" ? 503 : (result.error.status ?? 502);
    return NextResponse.json(
      {
        detail: result.error.detail ?? result.error.message,
        kind: result.error.kind,
      },
      { status },
    );
  }

  return NextResponse.json(result.data, { status: 202 });
}
