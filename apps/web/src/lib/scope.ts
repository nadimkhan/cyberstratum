/**
 * The authorised scope of a workspace, in the shape the product uses.
 *
 * The kind of a grant is one of three things:
 *
 * - `contract`: one address. The narrowest, and the safest.
 * - `chain`: every contract on one chain.
 * - `programme`: a programme, declared for the chain it was published
 *   for.
 *
 * The kind is decided here rather than in the browser, because a grant
 * of an unknown kind is not a grant, and a product that accepts one and
 * ignores it is worse than one that refuses it.
 */
export type ScopeGrantKind = "programme" | "contract" | "chain";

/** The three kinds a grant may have. */
export const SCOPE_GRANT_KINDS: ScopeGrantKind[] = [
  "contract",
  "chain",
  "programme",
];

/** One declared grant. */
export interface ScopeGrant {
  id: string;
  kind: ScopeGrantKind;
  value: string;
  chainId: number | null;
  safeHarbour: boolean;
  reference: string | null;
  expiresAt: string | null;
  createdAt: string;
}

/**
 * What the registry says about a target.
 *
 * The three answers are kept apart on purpose. `unknown` is not
 * `out_of_scope`, and it is not `in_scope`: a workspace that has
 * declared nothing has neither been permitted nor refused.
 */
export interface ScopeStatus {
  status: "in_scope" | "out_of_scope" | "unknown";
  reason: string;
  statement: string;
  safeHarbour: boolean;
  reference: string | null;
}

/**
 * Check a declaration before it is sent.
 *
 * Returns the problem in words, or `null` when the declaration is one
 * the registry can store. A chain grant needs a chain id; a contract
 * grant needs an address; a programme grant needs a name.
 */
export function scopeGrantProblem(
  kind: string,
  value: string,
  chainId: string,
): string | null {
  if (!SCOPE_GRANT_KINDS.includes(kind as ScopeGrantKind)) {
    return "Choose what kind of scope this is: a contract, a chain, or a programme.";
  }
  const trimmed = value.trim();
  if (!trimmed) {
    return "Say what this grant covers. A grant with nothing in it covers nothing.";
  }
  if (kind === "chain") {
    if (!/^\d+$/.test(chainId.trim())) {
      return "A chain grant needs the chain id it covers.";
    }
    return null;
  }
  if (kind === "contract") {
    if (!/^0x[0-9a-fA-F]{40}$/.test(trimmed)) {
      return "A contract grant needs a 0x address of 40 hex characters.";
    }
  }
  return null;
}

/**
 * Read the date a declaration stops applying.
 *
 * Returns the date in ISO form, or `null` when there is none. A date
 * that cannot be read is refused: a declaration whose expiry the
 * product did not understand would quietly become one that never ends.
 */
export function scopeExpiryProblem(raw: string): string | null {
  const trimmed = raw.trim();
  if (!trimmed) return null;
  const parsed = new Date(trimmed);
  if (Number.isNaN(parsed.getTime())) {
    return "The expiry is not a date this product can read.";
  }
  return null;
}
