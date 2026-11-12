"""Deciding whether a target was in an authorised scope.

The rule is deliberately simple and deliberately honest:

* a workspace that has declared no scope is **unknown** -- not
  "out of scope". Nothing has been claimed either way.
* a target covered by a live grant is **in scope**.
* a workspace that has declared scope, but this target is not covered
  by any of it, is **out of scope**.

"Unknown" is never reported as "out of scope" and never as "in
scope": a scanner that cannot tell the difference between a workspace
that has said nothing and one that has been refused is lying.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.scope import ScopeGrant

#: The target was covered by a grant.
IN_SCOPE = "in_scope"
#: The workspace has declared a scope, and this target is not in it.
OUT_OF_SCOPE = "out_of_scope"
#: The workspace has not declared a scope, or the grants have expired.
UNKNOWN_SCOPE = "unknown"

#: What the product says about each status.
SCOPE_STATEMENT: dict[str, str] = {
    IN_SCOPE: (
        "The target was covered by an authorised scope grant for this "
        "workspace when the scan was queued."
    ),
    OUT_OF_SCOPE: (
        "The target was not covered by any authorised scope grant for "
        "this workspace. The analysis is shown for the workspace's own "
        "use; it is not authorised for disclosure."
    ),
    UNKNOWN_SCOPE: (
        "This workspace has not declared an authorised scope, so the "
        "authorisation under which this scan was made is unknown. The "
        "analysis is shown for the workspace's own use; it is not "
        "authorised for disclosure."
    ),
}


@dataclass(frozen=True)
class ScopeDecision:
    """What the scope registry says about a target."""

    status: str
    reason: str
    grant_id: uuid.UUID | None = None
    reference: str | None = None
    safe_harbour: bool = False

    @property
    def statement(self) -> str:
        """The sentence a report should carry."""
        return SCOPE_STATEMENT.get(self.status, SCOPE_STATEMENT[UNKNOWN_SCOPE])


def _is_live(grant: ScopeGrant, now: datetime) -> bool:
    """Return whether a grant still applies."""
    return grant.expires_at is None or grant.expires_at > now


def _covers(grant: ScopeGrant, chain_id: int | None, address: str) -> bool:
    """Return whether a grant covers this chain and address."""
    if grant.kind == "contract":
        return bool(address) and grant.value.lower() == address.lower()
    if grant.kind == "chain":
        return chain_id is not None and grant.value == str(chain_id)
    if grant.kind == "programme":
        # A programme covers the chain it was declared for. It is a
        # broad declaration, and the workspace that made it is the one
        # that is answerable for it.
        return chain_id is not None and grant.chain_id == chain_id
    return False


def evaluate_scope(
    session: Session,
    workspace_id: uuid.UUID,
    *,
    chain_id: int | None,
    address: str,
) -> ScopeDecision:
    """Decide whether a target was in the workspace's authorised scope."""
    grants = list(
        session.execute(select(ScopeGrant).where(ScopeGrant.workspace_id == workspace_id))
        .scalars()
        .all()
    )

    if not grants:
        return ScopeDecision(
            status=UNKNOWN_SCOPE,
            reason="This workspace has not declared an authorised scope.",
        )

    now = datetime.now(UTC)
    live = [grant for grant in grants if _is_live(grant, now)]
    for grant in live:
        if _covers(grant, chain_id, address):
            return ScopeDecision(
                status=IN_SCOPE,
                reason=(f"Covered by a {grant.kind} grant declared by this workspace."),
                grant_id=grant.id,
                reference=grant.reference,
                safe_harbour=grant.safe_harbour,
            )

    if not live:
        return ScopeDecision(
            status=UNKNOWN_SCOPE,
            reason=(
                "Every scope grant this workspace declared has expired, so "
                "the authorisation is unknown."
            ),
        )

    return ScopeDecision(
        status=OUT_OF_SCOPE,
        reason=(
            "This workspace has declared an authorised scope, and this "
            "target is not covered by any of it."
        ),
    )


__all__ = [
    "IN_SCOPE",
    "OUT_OF_SCOPE",
    "SCOPE_STATEMENT",
    "UNKNOWN_SCOPE",
    "ScopeDecision",
    "evaluate_scope",
]
