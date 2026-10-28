import { NextResponse } from "next/server";
import { API_BASE_URL, API_PREFIX, createScan } from "@/lib/api";

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

  const body = (payload ?? {}) as Record<string, unknown>;
  const contractAddress = String(body.contractAddress ?? "").trim();
  const chainId = Number(body.chainId);
  const fork = String(body.fork ?? "").trim();

  if (!contractAddress) {
    return NextResponse.json(
      { detail: "contractAddress is required." },
      { status: 400 },
    );
  }
  if (!Number.isFinite(chainId)) {
    return NextResponse.json({ detail: "chainId must be a number." }, { status: 400 });
  }

  const result = await createScan({
    contractAddress,
    chainId,
    fork: fork || "cancun",
    labels: Array.isArray(body.labels) ? body.labels.map(String) : [],
    bytecodeHex: typeof body.bytecodeHex === "string" ? body.bytecodeHex : undefined,
    enableExperimentalMl:
      typeof body.enableExperimentalMl === "boolean"
        ? body.enableExperimentalMl
        : undefined,
  });

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
