import { NextResponse } from "next/server";
import { API_BASE_URL, API_PREFIX, rescanAsset } from "@/lib/api";

export const dynamic = "force-dynamic";

/**
 * Server-side proxy for queueing another scan of a tracked asset.
 */
export async function POST(
  _request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const result = await rescanAsset(id);

  if (!result.ok) {
    const status = result.error.kind === "network" ? 503 : result.error.status ?? 502;
    return NextResponse.json(
      {
        detail: result.error.detail ?? result.error.message,
        kind: result.error.kind,
        apiBaseUrl: API_BASE_URL,
        apiPrefix: API_PREFIX,
      },
      { status },
    );
  }

  return NextResponse.json(result.data, { status: 202 });
}
