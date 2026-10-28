"""Strict Pydantic models for all 13 T3 timeline operations (Milestone P1).

These models define exact parameter shapes, constraints, and integer millisecond boundaries
for timeline modifications driven by user requests or Gemini AI function calls.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.edit_spec import CaptionSpec, GradeSpec
from app.schemas.timeline import Item, ItemTransition, Track, TrackType


class BaseTimelineOp(BaseModel):
    """Base model for all timeline operations."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class AddTrackOp(BaseTimelineOp):
    """Add a new track to the timeline."""

    type: Literal["add_track"] = Field(
        default="add_track",
        description="Operation type identifier",
    )
    track_id: str | None = Field(
        default=None,
        description="Optional unique identifier for the new track. Generated if omitted.",
    )
    track_type: TrackType = Field(
        default=TrackType.VIDEO,
        description="Type of track to create: 'video', 'audio', 'overlay', or 'caption'.",
    )
    name: str | None = Field(
        default=None,
        description="Optional human-readable label for the track.",
    )
    index: int | None = Field(
        default=None,
        ge=0,
        description="Optional 0-indexed position in the track list to insert into.",
    )
    track: Track | None = Field(
        default=None,
        description="Optional complete Track model to insert directly.",
    )


class RemoveTrackOp(BaseTimelineOp):
    """Remove a track and all its items from the timeline."""

    type: Literal["remove_track"] = Field(
        default="remove_track",
        description="Operation type identifier",
    )
    track_id: str = Field(
        ...,
        min_length=1,
        description="Unique identifier of the track to remove.",
    )


class AddItemOp(BaseTimelineOp):
    """Add a media item to a specific track."""

    type: Literal["add_item"] = Field(
        default="add_item",
        description="Operation type identifier",
    )
    track_id: str | None = Field(
        default=None,
        description="Target track ID to place the item onto.",
    )
    track_index: int | None = Field(
        default=None,
        ge=0,
        description="Target track index if track_id is omitted.",
    )
    item: Item = Field(
        ...,
        description="Media item definition with source, start, src_in, and src_out.",
    )


class RemoveItemOp(BaseTimelineOp):
    """Remove a media item from a track."""

    type: Literal["remove_item"] = Field(
        default="remove_item",
        description="Operation type identifier",
    )
    track_id: str = Field(
        ...,
        min_length=1,
        description="Unique identifier of the track containing the item.",
    )
    item_id: str = Field(
        ...,
        min_length=1,
        description="Unique identifier of the item to remove.",
    )


class SplitOp(BaseTimelineOp):
    """Slice an existing timeline item into two parts at a specified millisecond timestamp."""

    type: Literal["split"] = Field(
        default="split",
        description="Operation type identifier",
    )
    track_id: str = Field(
        ...,
        min_length=1,
        description="Unique identifier of the track containing the item.",
    )
    item_id: str = Field(
        ...,
        min_length=1,
        description="Unique identifier of the item to split.",
    )
    split_time: int = Field(
        ...,
        ge=0,
        description="Timeline timestamp in integer milliseconds where the item is sliced.",
    )
    new_item_id: str | None = Field(
        default=None,
        description="Optional unique identifier for the resulting right-hand item.",
    )


class TrimOp(BaseTimelineOp):
    """Adjust the in/out source boundaries or timeline start position of an item."""

    type: Literal["trim"] = Field(
        default="trim",
        description="Operation type identifier",
    )
    track_id: str = Field(
        ...,
        min_length=1,
        description="Unique identifier of the track containing the item.",
    )
    item_id: str = Field(
        ...,
        min_length=1,
        description="Unique identifier of the item to trim.",
    )
    new_src_in: int | None = Field(
        default=None,
        ge=0,
        description="New source media in-point in integer milliseconds.",
    )
    new_src_out: int | None = Field(
        default=None,
        ge=0,
        description="New source media out-point in integer milliseconds.",
    )
    new_start: int | None = Field(
        default=None,
        ge=0,
        description="New timeline start position in integer milliseconds.",
    )


class MoveOp(BaseTimelineOp):
    """Relocate an item to a new start position or across tracks."""

    type: Literal["move"] = Field(
        default="move",
        description="Operation type identifier",
    )
    item_id: str = Field(
        ...,
        min_length=1,
        description="Unique identifier of the item to move.",
    )
    from_track_id: str = Field(
        ...,
        min_length=1,
        description="Track ID currently containing the item.",
    )
    to_track_id: str | None = Field(
        default=None,
        description="Destination track ID. Defaults to from_track_id if omitted.",
    )
    new_start: int = Field(
        ...,
        ge=0,
        description="New start position on the track in integer milliseconds.",
    )


class RippleDeleteOp(BaseTimelineOp):
    """Delete an item and ripple-shift all subsequent items leftward by its duration."""

    type: Literal["ripple_delete"] = Field(
        default="ripple_delete",
        description="Operation type identifier",
    )
    track_id: str = Field(
        ...,
        min_length=1,
        description="Unique identifier of the track containing the item.",
    )
    item_id: str = Field(
        ...,
        min_length=1,
        description="Unique identifier of the item to delete with ripple shift.",
    )


class SetVolumeOp(BaseTimelineOp):
    """Modify the audio playback volume of an item."""

    type: Literal["set_volume"] = Field(
        default="set_volume",
        description="Operation type identifier",
    )
    track_id: str = Field(
        ...,
        min_length=1,
        description="Unique identifier of the track containing the item.",
    )
    item_id: str = Field(
        ...,
        min_length=1,
        description="Unique identifier of the item whose volume to adjust.",
    )
    volume: float = Field(
        ...,
        ge=0.0,
        le=2.0,
        description="Volume multiplier between 0.0 (mute) and 2.0 (200% boost).",
    )


class SetGradeOp(BaseTimelineOp):
    """Apply or update color grading adjustments on an item."""

    type: Literal["set_grade"] = Field(
        default="set_grade",
        description="Operation type identifier",
    )
    track_id: str = Field(
        ...,
        min_length=1,
        description="Unique identifier of the track containing the item.",
    )
    item_id: str = Field(
        ...,
        min_length=1,
        description="Unique identifier of the item to grade.",
    )
    grade: GradeSpec = Field(
        ...,
        description="Color grading specification with preset, brightness, contrast, saturation.",
    )


class SetTransitionOp(BaseTimelineOp):
    """Apply or update a visual transition effect on an item."""

    type: Literal["set_transition"] = Field(
        default="set_transition",
        description="Operation type identifier",
    )
    track_id: str = Field(
        ...,
        min_length=1,
        description="Unique identifier of the track containing the item.",
    )
    item_id: str = Field(
        ...,
        min_length=1,
        description="Unique identifier of the item to apply transition to.",
    )
    transition: ItemTransition = Field(
        ...,
        description="Transition spec (type: fade, wipeleft, crossfade, slideup, duration_ms).",
    )


class AddCaptionOp(BaseTimelineOp):
    """Add a subtitle or caption item onto a caption track."""

    type: Literal["add_caption"] = Field(
        default="add_caption",
        description="Operation type identifier",
    )
    text: str = Field(
        ...,
        min_length=1,
        description="Text content of the subtitle or caption.",
    )
    start: int = Field(
        ...,
        ge=0,
        description="Start position in integer milliseconds.",
    )
    duration_ms: int = Field(
        ...,
        gt=0,
        description="Display duration in integer milliseconds.",
    )
    track_id: str | None = Field(
        default=None,
        description="Optional caption track ID. A caption track is created if omitted.",
    )
    caption_spec: CaptionSpec | None = Field(
        default=None,
        description="Optional caption styling (font, colors, animation, position).",
    )


class UpdateCaptionOp(BaseTimelineOp):
    """Update text, timing, or style of an existing caption item."""

    type: Literal["update_caption"] = Field(
        default="update_caption",
        description="Operation type identifier",
    )
    item_id: str = Field(
        ...,
        min_length=1,
        description="Unique identifier of the caption item to update.",
    )
    text: str | None = Field(
        default=None,
        min_length=1,
        description="Optional updated caption text content.",
    )
    start: int | None = Field(
        default=None,
        ge=0,
        description="Optional updated start position in integer milliseconds.",
    )
    duration_ms: int | None = Field(
        default=None,
        gt=0,
        description="Optional updated duration in integer milliseconds.",
    )
    track_id: str | None = Field(
        default=None,
        description="Optional caption track ID containing the item.",
    )
    caption_spec: CaptionSpec | None = Field(
        default=None,
        description="Optional updated caption styling specification.",
    )


# Discriminated union of all 13 valid timeline operations
TimelineOp = Annotated[
    AddTrackOp
    | RemoveTrackOp
    | AddItemOp
    | RemoveItemOp
    | SplitOp
    | TrimOp
    | MoveOp
    | RippleDeleteOp
    | SetVolumeOp
    | SetGradeOp
    | SetTransitionOp
    | AddCaptionOp
    | UpdateCaptionOp,
    Field(discriminator="type"),
]

# Mapping of op type names to corresponding Pydantic model classes
OP_MODEL_MAP: dict[str, type[BaseTimelineOp]] = {
    "add_track": AddTrackOp,
    "remove_track": RemoveTrackOp,
    "add_item": AddItemOp,
    "remove_item": RemoveItemOp,
    "split": SplitOp,
    "trim": TrimOp,
    "move": MoveOp,
    "ripple_delete": RippleDeleteOp,
    "set_volume": SetVolumeOp,
    "set_grade": SetGradeOp,
    "set_transition": SetTransitionOp,
    "add_caption": AddCaptionOp,
    "update_caption": UpdateCaptionOp,
}
