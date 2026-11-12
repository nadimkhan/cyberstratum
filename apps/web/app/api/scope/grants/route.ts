import { NextResponse } from "next/server";
import { createScopeGrant } from "@/lib/api";

export const dynamic = "force-dynamic";

/**
 * Server-side proxy for declaring the authorised scope of a workspace.
 *
 * The browser posts here; the request to the FastAPI backend is made
 * from the server, so the service key stays out of the client bundle
 * and the session cookie stays in the browser.
 *
 * The workspace is named in the request, and it has to be: a
 * declaration that applied to every workspace at once would not be a
 * declaration, and one that silently reached another tenant's scope
 * would be worse than none at all. The backend refuses a request that
 * does not name one.
 */
export async function POST(request: Request) {
  let body: {
    workspace_id?: string | null;
    kind?: string;
    value?: string;
    chain_id?: number | null;
    safe_harbour?: boolean;
    reference?: string | null;
  };
  try {
    body = (await request.json()) as {
      workspace_id?: string | null;
      kind?: string;
      value?: string;
      chain_id?: number | null;
      safe_harbour?: boolean;
      reference?: string | null;
    };
  } catch {
    return NextResponse.json(
      { detail: "The request body could not be read as JSON." },
      { status: 400 },
    );
  }

  const workspaceId = (body.workspace_id ?? "").trim();
  if (!workspaceId) {
    return NextResponse.json(
      { detail: "Name the workspace this declaration belongs to." },
      { status: 422 },
    );
  }

  const result = await createScopeGrant(workspaceId, {
    kind: (body.kind ?? "").trim(),
    value: (body.value ?? "").trim(),
    chainId: body.chain_id ?? null,
    safeHarbour: body.safe_harbour ?? false,
    reference: (body.reference ?? "").trim() || null,
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

  return NextResponse.json(result.data, { status: 201 });
}
