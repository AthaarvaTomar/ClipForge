from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.timeline import Track


class TimelineCreateRequest(BaseModel):
    """Payload to create a new timeline from a source video."""

    model_config = ConfigDict(extra="ignore")

    video_id: str = Field(
        ...,
        description="Source video ID to initialize the timeline for",
    )
    tracks: list[Track] | None = Field(
        default=None,
        description="Optional initial tracks. If omitted, starts with an empty track list.",
    )
    source_duration_ms: int | None = Field(
        default=None,
        ge=0,
        description=(
            "Optional total duration in milliseconds. "
            "Defaults to source video duration if available."
        ),
    )


class TimelineOpsRequest(BaseModel):
    """Payload to apply a batch of operations sharing one group_id."""

    model_config = ConfigDict(extra="ignore")

    expected_version: int = Field(
        ...,
        ge=0,
        description="Client's current timeline version for optimistic concurrency check",
    )
    ops: list[dict[str, Any]] = Field(
        ...,
        min_length=1,
        description="List of timeline operations to apply in order",
    )
    actor: str = Field(
        default="user",
        description="Actor applying the operations ('user' or 'agent')",
    )
    group_id: str | None = Field(
        default=None,
        description="Optional group ID to group these operations. Generated if omitted.",
    )


class TimelineUndoRequest(BaseModel):
    """Payload to undo the latest group of operations."""

    model_config = ConfigDict(extra="ignore")

    expected_version: int = Field(
        ...,
        ge=0,
        description="Client's current timeline version for optimistic concurrency check",
    )


class TimelineRedoRequest(BaseModel):
    """Payload to redo the next undone group of operations."""

    model_config = ConfigDict(extra="ignore")

    expected_version: int = Field(
        ...,
        ge=0,
        description="Client's current timeline version for optimistic concurrency check",
    )


class TimelineRestoreRequest(BaseModel):
    """Payload to restore a specific snapshot version."""

    model_config = ConfigDict(extra="ignore")

    expected_version: int = Field(
        ...,
        ge=0,
        description="Client's current timeline version for optimistic concurrency check",
    )


class TimelineOpResponse(BaseModel):
    """Representation of an operation stored in timeline_ops."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    seq: int
    group_id: str
    op: dict[str, Any]
    inverse_op: dict[str, Any]
    actor: str
    created_at: datetime


class TimelineVersionResponse(BaseModel):
    """Representation of a snapshot stored in timeline_versions."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    version: int
    created_at: datetime


class TimelineHistoryResponse(BaseModel):
    """Complete operation history and snapshots for a timeline."""

    model_config = ConfigDict(extra="ignore")

    timeline_id: str
    current_version: int
    current_seq: int
    ops: list[TimelineOpResponse]
    versions: list[TimelineVersionResponse]
