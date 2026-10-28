"""Pydantic schemas for AI edit plans and planning endpoints (Milestone P3/P5)."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class PlanRequest(BaseModel):
    """Payload to request an AI editing plan for a timeline."""

    model_config = ConfigDict(extra="ignore")

    prompt: str = Field(
        ...,
        min_length=1,
        description=(
            "Editing instructions (e.g., 'remove all silences', 'tighten first 15s', 'add B-roll')."
        ),
    )
    dry_run: bool = Field(
        default=False,
        description="If True, generates and validates the plan without saving a persistent job.",
    )


class PlanResponse(BaseModel):
    """Representation of an AI editing plan."""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="Unique plan ID")
    timeline_id: str = Field(..., description="Target timeline ID")
    job_id: str | None = Field(default=None, description="Background job ID if ran asynchronously")
    prompt: str = Field(..., description="Original user prompt")
    rationale: str | None = Field(
        default=None, description="AI reasoning and rationale for the edits"
    )
    ops: list[dict[str, Any]] = Field(
        default_factory=list, description="Validated timeline operations"
    )
    status: str = Field(..., description="Plan status: PENDING, VALIDATED, APPLIED, FAILED")
    error_message: str | None = Field(
        default=None, description="Validation or planning error details"
    )
    created_at: datetime
    updated_at: datetime


class ApplyPlanRequest(BaseModel):
    """Payload to apply an existing edit plan onto the timeline."""

    model_config = ConfigDict(extra="ignore")

    expected_version: int | None = Field(
        default=None,
        ge=0,
        description="Optional current timeline version for optimistic concurrency check.",
    )
