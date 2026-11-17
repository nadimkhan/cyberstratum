"""The schemas for the third-party notices.

A notice that cannot be checked is not a notice. Every component
carries the mechanical facts of how it is used — imported, modified,
conveyed — so a reader can see the difference between a component that
imposes a condition and one that does not, without taking anyone's word
for it.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ThirdPartyComponent(BaseModel):
    """One component this product is built on."""

    name: str
    version: str
    spdx_id: str
    license_url: str
    upstream_url: str
    role: str
    imported: bool
    modified: bool
    conveyed_to_customers: bool
    usage: str
    note: str = ""


class ThirdPartyDataset(BaseModel):
    """One dataset this product draws on."""

    dataset: str
    spdx_id: str
    license_url: str
    upstream_url: str
    upstream_revision: str | None = None
    redistribution: str = "unspecified"
    derived_artifacts_may_be_redistributed: bool = False
    per_repository_audit_required: bool = False
    note: str = ""


class NoticesResponse(BaseModel):
    """Everything this product is built on, and how."""

    version: str
    description: str
    note: str = ""
    components: list[ThirdPartyComponent] = Field(default_factory=list)
    datasets: list[ThirdPartyDataset] = Field(default_factory=list)


__all__ = [
    "NoticesResponse",
    "ThirdPartyComponent",
    "ThirdPartyDataset",
]
