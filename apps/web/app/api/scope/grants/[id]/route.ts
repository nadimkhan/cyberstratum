import { NextResponse } from "next/server";
import { withdrawScopeGrant } from "@/lib/api";

export const dynamic = "force-dynamic";

/**
 * Server-side proxy for withdrawing a declaration.
 *
 * A declaration that was made in error has to be withdrawable: an
 * address pasted wrongly, a programme that has ended, a chain that was
 * never in bounds. Each of them is a statement that is no longer true,
 * and a registry that can only grow will keep making it.
 *
 * The workspace is named in the request, because a declaration belongs
 * to one workspace and only that workspace may withdraw it. The backend
 * refuses a withdrawal that names none, and refuses one that names a
 * grant belonging to another workspace.
 */
export async function DELETE(
  request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const url = new URL(request.url);
  const workspaceId = (url.searchParams.get("workspace_id") ?? "").trim();
  if (!workspaceId) {
    return NextResponse.json(
      { detail: "Name the workspace this declaration belongs to." },
      { status: 422 },
    );
  }

  const result = await withdrawScopeGrant(workspaceId, id);
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

  return NextResponse.json({ withdrawn: true }, { status: 200 });
}
