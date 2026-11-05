"""Serving the installed model's manifest.

The manifest is the auditable copy of the model: what it was trained on,
with what splits, at what fingerprint. A finding attributed to the model
is only meaningful if the manifest behind it can be retrieved, so the
manifest is a first-class, fetchable object rather than a row of prose in
a report.

The endpoint distinguishes the states that matter:

* **404** - no model is installed. That is a fact, not a failure.
* **503** - a model is configured but its manifest cannot be read. That is
  a broken installation, and it is reported as one. It is never reported
  as "no model".
* **200** - the manifest, with the digest of the exact file it was read
  from, so a reader can prove they hold the same manifest.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status

from app.core.security import CurrentPrincipal
from app.services.model_manifest import ModelManifestError, read_model_manifest

router = APIRouter(prefix="/api/v1/models", tags=["models"])


@router.get(
    "/manifest",
    summary="Return the installed model's auditable manifest",
    responses={
        200: {"description": "The manifest and the digest of the file it was read from."},
        404: {"description": "No model is installed."},
        503: {"description": "A model is configured but its manifest cannot be read."},
    },
)
def get_model_manifest(principal: CurrentPrincipal) -> dict[str, Any]:
    """Return the installed model's manifest.

    The response carries the manifest's own content, the digest of the
    file it came from, and the identifier a report cites. A report that
    quotes this digest can be checked against this endpoint later.
    """
    try:
        manifest = read_model_manifest()
    except ModelManifestError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The model manifest is configured but cannot be read.",
        ) from exc

    if manifest is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No model is installed.",
        )

    return {
        "manifest_id": manifest.manifest_id,
        "sha256": manifest.sha256,
        "path": manifest.path,
        "manifest": manifest.payload,
    }


__all__ = ["router"]
