import { NextResponse } from "next/server";
import { API_BASE_URL, API_PREFIX, createScan } from "@/lib/api";
import { validateScanPayload } from "@/lib/scan-request";

export const dynamic = "force-dynamic";

/**
 * Server-side proxy for scan creation.
 *
 * The browser posts to this route; the actual request to the FastAPI backend is
 * made from the server, so `NEXT_PUBLIC_API_BASE_URL` is read at runtime
 * rather than being inlined into the client bundle at build time.
 */
export async function POST(request: Request) {
  let payload: unknown;
  try {
    payload = await request.json();
  } catch {
    return NextResponse.json(
      { detail: "Request body must be valid JSON." },
      { status: 400 },
    );
  }

  // A scan needs something to analyse: an address, a source to compile,
  // or bytes. Which of them it is changes what the scan can promise, so
  // the mode is decided here rather than guessed at the backend.
  const validated = validateScanPayload(payload);
  if (!validated.ok) {
    return NextResponse.json({ detail: validated.error }, { status: 400 });
  }

  const result = await createScan(validated.value);

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
