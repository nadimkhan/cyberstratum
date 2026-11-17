"""The third-party notices.

This endpoint is the product saying who it is built on. It requires a
caller, like the guidance it sits beside: a notice a customer cannot
read is not a notice.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.core.security import CurrentPrincipal
from app.schemas.notices import NoticesResponse
from app.services.notices import load_notices

router = APIRouter(prefix="/api/v1/notices", tags=["notices"])


@router.get("", response_model=NoticesResponse, summary="The third-party notices")
def list_notices(principal: CurrentPrincipal) -> NoticesResponse:
    """The components and datasets this product is built on."""
    return NoticesResponse.model_validate(load_notices().as_dict())


__all__ = ["router"]
