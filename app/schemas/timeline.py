import uuid
from enum import StrEnum
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator

from app.schemas.edit_spec import CaptionSpec, GradeSpec


class TrackType(StrEnum):
    """Supported track types in a multi-track timeline."""

    VIDEO = "video"
    AUDIO = "audio"
    OVERLAY = "overlay"
    CAPTION = "caption"


class ItemTransition(BaseModel):
    """Transition applied at the start/end of a timeline item."""

    model_config = ConfigDict(extra="ignore")

    type: Literal["none", "fade", "wipeleft", "crossfade", "slideup"] = Field(
        default="none",
        description="Transition type",
    )
    duration_ms: int = Field(
        default=500,
        ge=0,
        description="Transition duration in integer milliseconds",
    )


class Item(BaseModel):
    """A media segment placed onto a timeline track.

    All time coordinates are represented as integer milliseconds.
    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique item identifier",
    )
    source: str = Field(
        ...,
        validation_alias=AliasChoices("source", "source_ref"),
        min_length=1,
        description="Source media reference (e.g. video_id or asset URI)",
    )
    src_in: int = Field(
        ...,
        ge=0,
        description="In-point in the source media in integer milliseconds",
    )
    src_out: int = Field(
        ...,
        ge=0,
        description="Out-point in the source media in integer milliseconds",
    )
    start: int = Field(
        ...,
        ge=0,
        description="Start position on the track timeline in integer milliseconds",
    )
    effects: dict[str, Any] = Field(
        default_factory=dict,
        description="Applied visual or audio filter/effects parameters",
    )
    volume: float = Field(
        default=1.0,
        ge=0.0,
        le=2.0,
        description="Audio gain multiplier (1.0 = unity gain)",
    )
    grade: GradeSpec | None = Field(
        default=None,
        description="Color grading adjustments",
    )
    transition: ItemTransition | None = Field(
        default=None,
        description="Item transition effect",
    )
    text: str | None = Field(
        default=None,
        description="Text content for caption items",
    )
    caption_style: CaptionSpec | None = Field(
        default=None,
        validation_alias=AliasChoices("caption_style", "caption_spec"),
        description="Optional burned-in caption styling override",
    )

    @property
    def caption_spec(self) -> CaptionSpec | None:
        """Alias for caption_style."""
        return self.caption_style

    @property
    def source_ref(self) -> str:
        """Alias for source for compatibility with task spec."""
        return self.source

    @property
    def duration(self) -> int:
        """Item duration on the timeline in milliseconds."""
        return self.src_out - self.src_in

    @property
    def end(self) -> int:
        """End position on the track timeline in milliseconds."""
        return self.start + self.duration

    @model_validator(mode="after")
    def validate_in_out_range(self) -> "Item":
        if self.src_in >= self.src_out:
            raise ValueError(
                f"Item '{self.id}': src_in ({self.src_in}ms) must be strictly "
                f"less than src_out ({self.src_out}ms)"
            )
        return self


class Track(BaseModel):
    """A single lane of media items in a timeline."""

    model_config = ConfigDict(extra="ignore")

    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique track identifier",
    )
    type: TrackType = Field(
        ...,
        description="Track type: video, audio, overlay, or caption",
    )
    name: str | None = Field(
        default=None,
        description="Human-readable track label",
    )
    items: list[Item] = Field(
        default_factory=list,
        description="Ordered list of non-overlapping media items",
    )
    muted: bool = Field(
        default=False,
        description="Whether this track is muted",
    )
    locked: bool = Field(
        default=False,
        description="Whether track editing is locked",
    )

    @model_validator(mode="after")
    def validate_no_overlapping_items(self) -> "Track":
        """Verify that no two items on the same track occupy overlapping time spans."""
        if len(self.items) <= 1:
            return self

        # Sort items by track timeline start position
        sorted_items = sorted(self.items, key=lambda item: item.start)

        for i in range(len(sorted_items) - 1):
            curr = sorted_items[i]
            nxt = sorted_items[i + 1]

            curr_end = curr.start + (curr.src_out - curr.src_in)
            if nxt.start < curr_end:
                raise ValueError(
                    f"Track '{self.id}' ({self.type.value}) contains overlapping items: "
                    f"item '{curr.id}' [{curr.start}ms - {curr_end}ms] overlaps with "
                    f"item '{nxt.id}' starting at {nxt.start}ms"
                )

        return self


class Timeline(BaseModel):
    """Full multi-track timeline model.

    Root schema for all video editing operations, undo/redo logs, and renders.
    All time measurements are in integer milliseconds.
    """

    model_config = ConfigDict(extra="ignore")

    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique timeline identifier",
    )
    video_id: str = Field(
        ...,
        description="Source video reference ID",
    )
    version: int = Field(
        default=1,
        ge=0,
        description="Monotonically increasing version number for optimistic concurrency",
    )
    tracks: list[Track] = Field(
        default_factory=list,
        description="List of multi-track lanes (video, audio, overlay, caption)",
    )
    source_duration_ms: int | None = Field(
        default=None,
        ge=0,
        description="Optional total duration of source video in milliseconds for validation",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Auxiliary timeline metadata",
    )

    @property
    def duration(self) -> int:
        """Total duration of the timeline in integer milliseconds."""
        max_end = 0
        for track in self.tracks:
            for item in track.items:
                if item.end > max_end:
                    max_end = item.end
        return max_end

    @model_validator(mode="after")
    def validate_source_duration(self) -> "Timeline":
        """If source_duration_ms is provided, ensure all source items stay within limits."""
        if self.source_duration_ms is not None:
            for track in self.tracks:
                for item in track.items:
                    is_source_media = item.source in (self.video_id, "source")
                    if is_source_media and item.src_out > self.source_duration_ms:
                        raise ValueError(
                            f"Item '{item.id}' src_out ({item.src_out}ms) exceeds "
                            f"source duration ({self.source_duration_ms}ms)"
                        )
        return self
