import { NextResponse } from "next/server";
import { fetchScanReport } from "@/lib/api";

export const dynamic = "force-dynamic";

/**
 * Server-side proxy for the PDF report.
 *
 * The browser cannot present the server-only `API_KEY`, so the PDF is fetched
 * here on the server and streamed back. The report is binary, so this route
 * returns the raw bytes rather than JSON.
 *
 * The `X-Report-SHA256` header carries the digest the backend computed over
 * the PDF it rendered. It is echoed so a reader can confirm the document they
 * are holding is the one the backend produced.
 */
export async function GET(
  _request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;

  const result = await fetchScanReport(id);
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

  const { bytes, sha256 } = result.data;
  const body = new Uint8Array(bytes);

  return new NextResponse(body.buffer as ArrayBuffer, {
    status: 200,
    headers: {
      "Content-Type": "application/pdf",
      "Content-Disposition": `attachment; filename="cyberstratum-report-${id}.pdf"`,
      "Cache-Control": "no-store",
      ...(sha256 ? { "X-Report-SHA256": sha256 } : {}),
    },
  });
}
