"""The weakness taxonomy, as it is served.

The classes come from a frozen registry, so the schemas say where each
one came from and who is making the claim about the correspondence. A
reviewer can therefore check the correspondence instead of taking it on
trust.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class WeaknessAlso(BaseModel):
    """Another class the same detector corresponds to."""

    swc_id: str
    title: str
    cwe_ids: list[str] = Field(default_factory=list)


class WeaknessRead(BaseModel):
    """The weakness class of one finding's detector.

    Attributes:
        swc_id: The canonical identifier, such as ``SWC-107``.
        title: The class name.
        severity: The registry's own severity, when it records one. It
            is not this product's severity: that comes from the
            detector.
        cwe_ids: The CWE classes the registry relates it to.
        basis: Why the detector corresponds to this class.
        source: Who is making the claim.
        also: Any further classes the detector corresponds to.
    """

    swc_id: str
    title: str
    severity: str | None = None
    cwe_ids: list[str] = Field(default_factory=list)
    basis: str
    source: str
    also: list[WeaknessAlso] = Field(default_factory=list)


class WeaknessTaxonomyEntry(BaseModel):
    """One class in the taxonomy."""

    swc_id: str
    title: str
    severity: str | None = None
    cwe_ids: list[str] = Field(default_factory=list)
    related_swc_ids: list[str] = Field(default_factory=list)


class WeaknessTaxonomyResponse(BaseModel):
    """The whole taxonomy, and where it came from."""

    version: str
    description: str
    provenance: dict[str, object]
    items: list[WeaknessTaxonomyEntry] = Field(default_factory=list)
    total: int = 0


__all__ = [
    "WeaknessAlso",
    "WeaknessRead",
    "WeaknessTaxonomyEntry",
    "WeaknessTaxonomyResponse",
]
