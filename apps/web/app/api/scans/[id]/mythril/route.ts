import { NextResponse } from "next/server";
import { triggerMythril } from "@/lib/api";

export const dynamic = "force-dynamic";

/**
 * Server-side proxy for the on-demand Mythril deep analysis.
 *
 * The browser posts here; the request to the FastAPI backend is made from
 * the server so the `X-API-Key` stays out of the client bundle.
 *
 * The response reports that the work was *queued*. It says nothing about what
 * Mythril will find, and it is deliberately not described as a success: a
 * Mythril run that later produces no verdict must not be read as "clean".
 */
export async function POST(
  _request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;

  const result = await triggerMythril(id);
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
