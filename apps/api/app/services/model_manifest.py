"""Reading the installed model's manifest, so a report can cite it.

A report that says "a model looked at this contract" is only worth
something if it also says *which* model, and lets a reader fetch the
exact artefact that produced the finding. This module resolves the
installed model directory, reads the auditable manifest that sits
beside the model file, and returns a reference the report can cite.

Three states are kept apart, because collapsing them would be a lie:

* **No model is installed** - there is no manifest. That is a fact, and
  it is reported as ``None``. It is not an error, and it is never
  reported as a clean result.
* **A model is installed and its manifest is readable** - the manifest
  is returned with the digest of the file it came from.
* **A model is installed but its manifest cannot be read** - that is a
  failure. It is raised as :class:`ModelManifestError`, so that the API
  can answer "unavailable" rather than "no model".

The digest matters as much as the identifier: the manifest is the
auditable copy, and the digest is what lets a reader prove they are
looking at the same manifest the report was built from.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.config import Settings, get_settings


class ModelManifestError(RuntimeError):
    """The installed model's manifest could not be read."""


@dataclass(frozen=True, slots=True)
class ModelManifest:
    """The auditable manifest that sits beside an installed model."""

    manifest_id: str
    sha256: str
    path: str
    payload: dict[str, Any]

    def as_reference(self) -> dict[str, str]:
        """Return the reference shape the report renderer expects."""
        return {"manifest_id": self.manifest_id, "sha256": self.sha256}


def model_directory(settings: Settings | None = None) -> Path | None:
    """Return the installed model's directory, or ``None`` if there is none.

    A relative directory is resolved against the repository root, the same
    way the artefact store resolves its own root, so a configured model
    directory means the same thing wherever the service is started.
    """
    settings = settings or get_settings()
    raw = (settings.ml_model_dir or "").strip()
    if not raw:
        return None
    path = Path(raw)
    if not path.is_absolute():
        path = settings.repo_root / path
    return path


def read_model_manifest(settings: Settings | None = None) -> ModelManifest | None:
    """Return the installed model's manifest, or ``None`` if none is installed.

    Raises:
        ModelManifestError: when a model directory is configured but its
            manifest is missing or unreadable. That is a broken
            installation, and it is reported as a failure rather than as
            the absence of a model.
    """
    settings = settings or get_settings()
    directory = model_directory(settings)
    if directory is None:
        return None

    manifest_path = directory / "manifest.json"
    if not manifest_path.exists():
        raise ModelManifestError(
            f"No model manifest at {manifest_path}. The model directory is "
            "configured but does not hold a manifest."
        )

    try:
        raw = manifest_path.read_bytes()
    except OSError as exc:
        raise ModelManifestError(
            f"Failed to read the model manifest at {manifest_path}: {exc}"
        ) from exc

    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ModelManifestError(
            f"The model manifest at {manifest_path} is not valid JSON: {exc}"
        ) from exc

    if not isinstance(payload, dict):
        raise ModelManifestError(
            f"The model manifest at {manifest_path} is not a JSON object."
        )

    digest = hashlib.sha256(raw).hexdigest()
    manifest_id = str(
        payload.get("version")
        or payload.get("model_id")
        or payload.get("id")
        or manifest_path.parent.name
    )
    return ModelManifest(
        manifest_id=manifest_id,
        sha256=digest,
        path=str(manifest_path),
        payload=payload,
    )


__all__ = [
    "ModelManifest",
    "ModelManifestError",
    "model_directory",
    "read_model_manifest",
]
