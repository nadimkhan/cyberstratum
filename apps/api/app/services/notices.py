"""The third-party notices this product serves.

The notices are a record, not a decoration. They say which components
carry a copyleft licence, and they say the mechanical facts of how each
one is used: whether it is imported, whether it is modified, and
whether it is ever handed to a customer. A component that is none of
those three cannot impose a condition on this product's own licence,
and that is a fact a reader can check rather than take on trust.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

NOTICES_PATH = Path(__file__).resolve().parent.parent / "data" / "third_party_notices.json"


@dataclass(frozen=True)
class ThirdPartyNotices:
    """The notices, loaded from the versioned record."""

    version: str
    description: str
    note: str
    components: tuple[dict[str, Any], ...]
    datasets: tuple[dict[str, Any], ...]

    def as_dict(self) -> dict[str, Any]:
        """Return the notices as a plain dictionary."""
        return {
            "version": self.version,
            "description": self.description,
            "note": self.note,
            "components": list(self.components),
            "datasets": list(self.datasets),
        }

    @property
    def copyleft_components(self) -> tuple[str, ...]:
        """Return the names of the components carrying a copyleft licence."""
        return tuple(
            str(component.get("name"))
            for component in self.components
            if str(component.get("spdx_id", "")).startswith(("AGPL", "GPL", "SSPL"))
        )

    @property
    def unsafe_components(self) -> tuple[str, ...]:
        """Return the names of components that break the boundary.

        A component that is imported, modified, or handed to a customer
        is no longer merely an external tool. This is the thing the
        notices exist to make visible, so it is computed rather than
        written down.
        """
        copyleft = ("AGPL", "GPL", "SSPL")
        return tuple(
            str(component.get("name"))
            for component in self.components
            if str(component.get("spdx_id", "")).startswith(copyleft)
            and (
                component.get("imported")
                or component.get("modified")
                or component.get("conveyed_to_customers")
            )
        )


def load_notices(path: Path | None = None) -> ThirdPartyNotices:
    """Read the notices from the versioned record."""
    source = path or NOTICES_PATH
    payload = json.loads(source.read_text(encoding="utf-8"))
    return ThirdPartyNotices(
        version=str(payload.get("version", "")),
        description=str(payload.get("description", "")),
        note=str(payload.get("note", "")),
        components=tuple(payload.get("components", [])),
        datasets=tuple(payload.get("datasets", [])),
    )


__all__ = [
    "NOTICES_PATH",
    "ThirdPartyNotices",
    "load_notices",
]
