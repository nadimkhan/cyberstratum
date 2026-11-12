"""Schemas for the detector guidance."""

from __future__ import annotations

from pydantic import BaseModel, Field


class GuidanceRead(BaseModel):
    """What a detector's finding means and what to do about it."""

    detector_id: str
    title: str
    what_it_means: str
    why_it_matters: str
    how_to_fix: str
    false_positive_patterns: str
    references: str
    default_severity: str = "medium"
    version: str = "1"


class GuidanceListResponse(BaseModel):
    """Every guidance entry the product holds."""

    items: list[GuidanceRead] = Field(default_factory=list)
    total: int = 0
