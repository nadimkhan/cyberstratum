/**
 * The rules of a verdict applied to many findings.
 *
 * This module is deliberately free of server-only imports so that the
 * browser and the server can agree on the rules without the browser
 * needing anything from the server.
 */

/** The verdicts a reviewer can record. */
export type BulkVerdict = "confirmed" | "false_positive" | "needs_more_evidence" | "triage";

/**
 * What is wrong with a verdict, if anything.
 *
 * A false-positive verdict needs a reason: without one it cannot be
 * told apart from a mistaken verdict, and neither is usable as ground
 * truth for the machine learning pipeline.
 */
export function bulkVerdictProblem(status: BulkVerdict, note: string): string | null {
  if (status === "false_positive" && !note.trim()) {
    return "A false-positive verdict needs a reason: without one it cannot be told apart from a mistaken verdict.";
  }
  return null;
}
