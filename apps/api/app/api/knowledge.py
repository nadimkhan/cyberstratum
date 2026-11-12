"""The guidance endpoints: what a detector's finding means and what to do.

The guidance is the part of the product that turns a pattern into an
action. It is served from the same versioned content the report renders,
so the browser and the PDF cannot disagree.

The endpoints require a caller, like the findings they explain: the
knowledge base is the product's content, not a public document.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.core.security import CurrentPrincipal
from app.schemas.knowledge import GuidanceListResponse, GuidanceRead
from app.services.knowledge import guidance_for, load_seed

router = APIRouter(prefix="/api/v1/knowledge", tags=["knowledge"])


@router.get("", response_model=GuidanceListResponse, summary="List the guidance")
def list_guidance(principal: CurrentPrincipal) -> GuidanceListResponse:
    """Every guidance entry the product holds."""
    entries = [guidance.as_dict() for guidance in load_seed().values()]
    return GuidanceListResponse(
        items=[GuidanceRead.model_validate(entry) for entry in entries],
        total=len(entries),
    )


@router.get("/{detector_id}", response_model=GuidanceRead, summary="The guidance for a detector")
def get_guidance(detector_id: str, principal: CurrentPrincipal) -> GuidanceRead:
    """The guidance for one detector.

    A detector with no guidance answers ``404``: the product does not
    have advice for it, and a generic paragraph that says nothing would
    be worse than silence.
    """
    guidance = guidance_for(detector_id)
    if guidance is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"there is no guidance for detector {detector_id!r}; the "
                "finding is still reported, but nothing is known about what "
                "to do about it"
            ),
        )
    return GuidanceRead.model_validate(guidance.as_dict())
