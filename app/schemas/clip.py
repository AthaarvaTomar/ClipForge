from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.edit_spec import EditSpec


class ClipBase(BaseModel):
    """Base schema for clip information."""

    title: str = Field(..., max_length=255)
    start_time: float = Field(..., ge=0.0)
    end_time: float = Field(..., ge=0.0)
    edit_spec: dict[str, Any] = Field(default_factory=dict)
    status: str = Field(default="DRAFT")


class ClipCreate(BaseModel):
    """Schema for creating a new clip with validated EditSpec."""

    video_id: str = Field(..., description="ID of the source video")
    title: str = Field(..., min_length=1, max_length=255, description="Title of the clip")
    edit_spec: EditSpec = Field(
        ...,
        description="Edit specifications including cuts, reframing, and captions",
    )
    start_time: float | None = Field(
        default=None,
        ge=0.0,
        description="Optional clip start time (derived from cuts if omitted)",
    )
    end_time: float | None = Field(
        default=None,
        ge=0.0,
        description="Optional clip end time (derived from cuts if omitted)",
    )
    status: str = Field(default="DRAFT", description="Initial clip status")

    @model_validator(mode="after")
    def resolve_and_validate_times(self) -> "ClipCreate":
        if self.start_time is None and self.edit_spec.cuts:
            self.start_time = self.edit_spec.cuts[0].start
        if self.end_time is None and self.edit_spec.cuts:
            self.end_time = self.edit_spec.cuts[-1].end

        if self.start_time is not None and self.end_time is not None:
            if self.end_time <= self.start_time:
                raise ValueError(
                    f"end_time ({self.end_time}s) must be greater than "
                    f"start_time ({self.start_time}s)"
                )
        return self


class ClipUpdate(BaseModel):
    """Schema for updating an existing clip."""

    title: str | None = Field(default=None, min_length=1, max_length=255)
    start_time: float | None = Field(default=None, ge=0.0)
    end_time: float | None = Field(default=None, ge=0.0)
    edit_spec: EditSpec | None = None
    status: Literal["DRAFT", "QUEUED", "RENDERING", "DONE", "FAILED"] | None = None

    @model_validator(mode="after")
    def validate_times(self) -> "ClipUpdate":
        if self.start_time is not None and self.end_time is not None:
            if self.end_time <= self.start_time:
                raise ValueError(
                    f"end_time ({self.end_time}s) must be greater than "
                    f"start_time ({self.start_time}s)"
                )
        return self


class ClipResponse(ClipBase):
    """Schema for clip response."""

    id: str
    video_id: str
    timeline_id: str | None = None
    output_path: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class ClipListResponse(BaseModel):
    """Schema for listing multiple clips."""

    video_id: str | None = None
    total: int
    clips: list[ClipResponse]
