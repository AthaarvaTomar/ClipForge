"""Pydantic schemas for video editing presets (Task A12)."""

from pydantic import BaseModel, ConfigDict, Field


class GradePreset(BaseModel):
    """Color grading preset configuration."""

    id: str = Field(description="Unique identifier matching EditSpec.grade.preset")
    name: str = Field(description="Human-readable title")
    description: str = Field(description="Detailed visual aesthetic description")
    brightness: float = Field(default=0.0, description="Default brightness offset")
    contrast: float = Field(default=1.0, description="Default contrast multiplier")
    saturation: float = Field(default=1.0, description="Default saturation multiplier")

    model_config = ConfigDict(extra="ignore")


class TransitionPreset(BaseModel):
    """Transition preset configuration."""

    id: str = Field(description="Unique identifier matching EditSpec.transition.type")
    name: str = Field(description="Human-readable title")
    description: str = Field(description="Description of the scene transition effect")
    default_duration: float = Field(default=0.5, description="Recommended duration in seconds")

    model_config = ConfigDict(extra="ignore")


class AnimationPreset(BaseModel):
    """Caption animation preset configuration."""

    id: str = Field(description="Unique identifier matching EditSpec.captions.animation")
    name: str = Field(description="Human-readable title")
    description: str = Field(description="Visual animation pacing and style description")
    recommended_font_size: int = Field(
        default=36, description="Optimal font size for this animation"
    )
    recommended_position: str = Field(default="bottom", description="Recommended screen placement")

    model_config = ConfigDict(extra="ignore")


class FontPreset(BaseModel):
    """Typography font preset configuration."""

    id: str = Field(description="Identifier for font selection")
    name: str = Field(description="Font family name for ASS and CSS rendering")
    category: str = Field(description="Typographic family category (sans-serif, display, etc.)")
    weights: list[str] = Field(default_factory=list, description="Available font weights")
    is_system: bool = Field(
        default=False, description="Whether font is pre-installed on standard OS"
    )

    model_config = ConfigDict(extra="ignore")


class PresetsResponse(BaseModel):
    """Aggregated preset listings returned by GET /api/presets."""

    grades: list[GradePreset] = Field(default_factory=list, description="Available color grades")
    transitions: list[TransitionPreset] = Field(
        default_factory=list, description="Available transitions"
    )
    animations: list[AnimationPreset] = Field(
        default_factory=list, description="Available caption animations"
    )
    fonts: list[FontPreset] = Field(default_factory=list, description="Available subtitle fonts")

    model_config = ConfigDict(extra="ignore")
