from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CutSegment(BaseModel):
    """A segment of the source video to include in the clip."""

    start: float = Field(..., ge=0.0, description="Start timestamp in seconds")
    end: float = Field(..., gt=0.0, description="End timestamp in seconds")

    @model_validator(mode="after")
    def validate_cut_range(self) -> "CutSegment":
        if self.end <= self.start:
            raise ValueError(
                f"Cut end time ({self.end}s) must be greater than start time ({self.start}s)"
            )
        return self


class ReframeSpec(BaseModel):
    """Aspect ratio reframing options."""

    strategy: Literal["crop", "blur-bg"] = Field(
        default="crop",
        description="Reframing strategy: 'crop' or 'blur-bg'",
    )
    crop_x_offset: float = Field(
        default=0.0,
        ge=-1.0,
        le=1.0,
        description="Horizontal crop framing offset (-1.0 left to 1.0 right)",
    )


class CaptionSpec(BaseModel):
    """Subtitle and burned-in caption styling."""

    enabled: bool = Field(default=True, description="Whether to burn captions into the clip")
    style: str = Field(
        default="bold-highlight",
        description="Preset caption style (e.g. bold-highlight, clean, karaoke)",
    )
    font_name: str = Field(default="Arial", description="Font family name")
    font_size: int = Field(default=36, ge=12, le=120, description="Font size in pt")
    primary_color: str = Field(
        default="#FFFFFF",
        pattern=r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$",
        description="Base text hex color (e.g. #FFFFFF)",
    )
    highlight_color: str = Field(
        default="#00FFCC",
        pattern=r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$",
        description="Active spoken word highlight hex color (e.g. #00FFCC)",
    )
    animation: Literal["highlight", "pop", "fade", "bounce", "none"] = Field(
        default="highlight",
        description="Subtitle animation style",
    )
    position: Literal["bottom", "middle", "top"] = Field(
        default="bottom",
        description="Vertical caption placement",
    )


class GradeSpec(BaseModel):
    """Color grading and visual adjustment parameters."""

    preset: Literal["none", "cinematic", "warm", "vibrant", "cool", "bw"] = Field(
        default="none",
        description="Color grade preset",
    )
    brightness: float = Field(default=0.0, ge=-1.0, le=1.0, description="Brightness adjustment")
    contrast: float = Field(default=1.0, ge=0.0, le=3.0, description="Contrast adjustment")
    saturation: float = Field(default=1.0, ge=0.0, le=3.0, description="Saturation multiplier")


class TransitionSpec(BaseModel):
    """Transition between multi-segment cuts."""

    type: Literal["none", "fade", "wipeleft", "crossfade", "slideup"] = Field(
        default="none",
        description="Transition effect between cuts",
    )
    duration: float = Field(
        default=0.5,
        ge=0.0,
        le=3.0,
        description="Duration of transition in seconds",
    )


class EditSpec(BaseModel):
    """Full specification for editing, reframing, and rendering a video clip."""

    cuts: list[CutSegment] = Field(
        ...,
        min_length=1,
        description="List of ordered, non-overlapping cut segments",
    )
    aspect_ratio: Literal["9:16", "16:9", "1:1", "4:5"] = Field(
        default="9:16",
        description="Target aspect ratio",
    )
    reframe: ReframeSpec = Field(default_factory=ReframeSpec)
    captions: CaptionSpec = Field(default_factory=CaptionSpec)
    grade: GradeSpec = Field(default_factory=GradeSpec)
    transition: TransitionSpec = Field(default_factory=TransitionSpec)

    # Highlight and moment metadata
    hook: str | None = Field(default=None, description="Opening hook text")
    reason: str | None = Field(default=None, description="Reason this clip was selected")
    score: float | None = Field(default=None, ge=0.0, le=100.0, description="Virality score")

    model_config = ConfigDict(extra="ignore")

    @model_validator(mode="after")
    def validate_cuts_chronology_and_overlap(self) -> "EditSpec":
        if not self.cuts:
            raise ValueError("At least one cut segment is required in EditSpec")

        for i in range(len(self.cuts) - 1):
            curr_cut = self.cuts[i]
            next_cut = self.cuts[i + 1]
            if next_cut.start < curr_cut.end:
                raise ValueError(
                    f"Cut segment {i + 1} (start {next_cut.start}s) overlaps with cut segment {i} "
                    f"(end {curr_cut.end}s). Cuts must be chronological and non-overlapping."
                )

        return self

    @property
    def total_duration(self) -> float:
        """Calculate total playback duration across all cut segments."""
        return sum(cut.end - cut.start for cut in self.cuts)
