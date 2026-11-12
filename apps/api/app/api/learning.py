"""The learning state: what has been reviewed, and what the model may say.

The model ranks findings; it never decides a verdict. It is only
installed when the reviewed corpus is large enough to be judged on
held-out families, and the gate says plainly when it is not.

This endpoint reports that state. It does not train anything and it
does not change any verdict: it says how much reviewed evidence there
is, what the last learning cycle concluded, and whether a model is
installed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.security import CurrentPrincipal, SessionDep, read_scope
from app.db.enums import FindingStatus
from app.db.models.scans import Finding

router = APIRouter(prefix="/api/v1/learning", tags=["learning"])

#: Where the learning cycle writes the outcome of its last run.
OUTCOME_FILENAME = "last_outcome.json"


def _last_outcome(settings: Any) -> dict[str, Any] | None:
    """Return the outcome of the last learning cycle, if there was one."""
    path = Path(settings.repo_root) / ".learning" / OUTCOME_FILENAME
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


@router.get(
    "/status",
    summary="Report the reviewed corpus and the state of the model",
)
def learning_status(session: SessionDep, principal: CurrentPrincipal) -> dict[str, Any]:
    """Report what has been reviewed and what the model may say."""
    settings = get_settings()

    workspace_filter = read_scope(principal, None)
    filters = []
    if workspace_filter is not None:
        filters.append(Finding.workspace_id == workspace_filter)

    status_rows = session.execute(
        select(Finding.status, func.count()).where(*filters).group_by(Finding.status)
    ).all()
    by_status = {str(status): int(count) for status, count in status_rows}

    confirmed = by_status.get(FindingStatus.CONFIRMED.value, 0)
    false_positive = by_status.get(FindingStatus.FALSE_POSITIVE.value, 0)
    reviewed_total = confirmed + false_positive

    contract_rows = session.execute(
        select(func.count(func.distinct(Finding.scan_id)))
        .select_from(Finding)
        .where(
            *filters,
            Finding.status.in_([FindingStatus.CONFIRMED, FindingStatus.FALSE_POSITIVE]),
        )
    ).all()
    reviewed_contracts = int(contract_rows[0][0]) if contract_rows else 0

    category_rows = session.execute(
        select(func.count(func.distinct(Finding.category)))
        .select_from(Finding)
        .where(
            *filters,
            Finding.status.in_([FindingStatus.CONFIRMED, FindingStatus.FALSE_POSITIVE]),
        )
    ).all()
    reviewed_categories = int(category_rows[0][0]) if category_rows else 0

    installed_model: dict[str, Any] | None = None
    try:
        from app.services.model_manifest import read_model_manifest

        manifest = read_model_manifest(settings)
    except Exception:  # pragma: no cover - a broken model must not hide the state
        manifest = None
    if manifest is not None:
        installed_model = {
            "manifest_id": manifest.manifest_id,
            "path": manifest.path,
            "payload": manifest.payload,
        }

    outcome = _last_outcome(settings)

    return {
        "reviewed": {
            "total": reviewed_total,
            "confirmed": confirmed,
            "false_positive": false_positive,
            "contracts": reviewed_contracts,
            "categories": reviewed_categories,
        },
        "model": installed_model,
        "last_cycle": outcome,
    }


__all__ = ["router"]
