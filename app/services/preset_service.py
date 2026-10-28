"""Preset service for loading and retrieving editing presets (Task A12)."""

from __future__ import annotations

import json
from pathlib import Path

from app.schemas.preset import (
    AnimationPreset,
    FontPreset,
    GradePreset,
    PresetsResponse,
    TransitionPreset,
)

DEFAULT_GRADES = [
    {
        "id": "none",
        "name": "Original",
        "description": "Original color balance without adjustments",
        "brightness": 0.0,
        "contrast": 1.0,
        "saturation": 1.0,
    },
    {
        "id": "cinematic",
        "name": "Cinematic",
        "description": "Teal & orange film aesthetic with rich contrast",
        "brightness": 0.02,
        "contrast": 1.15,
        "saturation": 1.1,
    },
    {
        "id": "warm",
        "name": "Warm Sunlight",
        "description": "Golden hour warmth",
        "brightness": 0.03,
        "contrast": 1.05,
        "saturation": 1.15,
    },
    {
        "id": "cool",
        "name": "Cool Modern",
        "description": "Clean cool tones",
        "brightness": 0.01,
        "contrast": 1.1,
        "saturation": 0.95,
    },
    {
        "id": "vibrant",
        "name": "Vibrant Pop",
        "description": "Punchy saturated colors",
        "brightness": 0.04,
        "contrast": 1.2,
        "saturation": 1.35,
    },
    {
        "id": "bw",
        "name": "Black & White Noir",
        "description": "Classic monochrome",
        "brightness": 0.0,
        "contrast": 1.25,
        "saturation": 0.0,
    },
]

DEFAULT_TRANSITIONS = [
    {
        "id": "none",
        "name": "Hard Cut",
        "description": "Direct cut without transition",
        "default_duration": 0.0,
    },
    {
        "id": "fade",
        "name": "Smooth Crossfade",
        "description": "Gradual blend",
        "default_duration": 0.5,
    },
    {
        "id": "wipeleft",
        "name": "Wipe Left",
        "description": "Linear wipe to left",
        "default_duration": 0.4,
    },
    {
        "id": "wiperight",
        "name": "Wipe Right",
        "description": "Linear wipe to right",
        "default_duration": 0.4,
    },
    {
        "id": "slideup",
        "name": "Slide Up",
        "description": "Slide upwards",
        "default_duration": 0.35,
    },
    {
        "id": "slidedown",
        "name": "Slide Down",
        "description": "Slide downwards",
        "default_duration": 0.35,
    },
    {
        "id": "circlecrop",
        "name": "Circle Crop Iris",
        "description": "Circular zoom iris",
        "default_duration": 0.5,
    },
    {
        "id": "dissolve",
        "name": "Dissolve",
        "description": "Soft film dissolve",
        "default_duration": 0.4,
    },
    {
        "id": "pixelize",
        "name": "Pixelize Glitch",
        "description": "Digital pixelation",
        "default_duration": 0.35,
    },
]

DEFAULT_ANIMATIONS = [
    {
        "id": "highlight",
        "name": "Spoken Highlight",
        "description": "Active spoken word highlighted in color",
        "recommended_font_size": 38,
        "recommended_position": "bottom",
    },
    {
        "id": "pop",
        "name": "Word Pop",
        "description": "Scale up active word",
        "recommended_font_size": 42,
        "recommended_position": "bottom",
    },
    {
        "id": "fade",
        "name": "Soft Fade",
        "description": "Smooth fade in/out",
        "recommended_font_size": 36,
        "recommended_position": "bottom",
    },
    {
        "id": "bounce",
        "name": "Squash & Bounce",
        "description": "Squash and stretch bounce",
        "recommended_font_size": 40,
        "recommended_position": "bottom",
    },
    {
        "id": "none",
        "name": "Clean Static",
        "description": "Clean static captions",
        "recommended_font_size": 36,
        "recommended_position": "bottom",
    },
]

DEFAULT_FONTS = [
    {
        "id": "arial",
        "name": "Arial",
        "category": "sans-serif",
        "weights": ["Regular", "Bold"],
        "is_system": True,
    },
    {
        "id": "impact",
        "name": "Impact",
        "category": "display",
        "weights": ["Regular"],
        "is_system": True,
    },
    {
        "id": "montserrat",
        "name": "Montserrat",
        "category": "sans-serif",
        "weights": ["Bold", "ExtraBold"],
        "is_system": False,
    },
    {
        "id": "oswald",
        "name": "Oswald",
        "category": "sans-serif-condensed",
        "weights": ["Bold"],
        "is_system": False,
    },
    {
        "id": "roboto",
        "name": "Roboto",
        "category": "sans-serif",
        "weights": ["Bold"],
        "is_system": False,
    },
    {
        "id": "anton",
        "name": "Anton",
        "category": "display",
        "weights": ["Regular"],
        "is_system": False,
    },
    {
        "id": "bebas_neue",
        "name": "Bebas Neue",
        "category": "display",
        "weights": ["Regular"],
        "is_system": False,
    },
]


class PresetService:
    """Service to load and return editing presets from JSON files or embedded defaults."""

    DEFAULT_PRESETS_DIR = Path("data/presets")

    @classmethod
    def _load_json_or_default(
        cls,
        file_path: Path,
        default_data: list[dict],  # type: ignore[type-arg]
    ) -> list[dict]:  # type: ignore[type-arg]
        if file_path.is_file():
            try:
                content = json.loads(file_path.read_text(encoding="utf-8"))
                if isinstance(content, list):
                    return content
            except Exception:
                pass
        return default_data

    @classmethod
    def get_presets(cls, presets_dir: Path | None = None) -> PresetsResponse:
        """Fetch all presets aggregated into a PresetsResponse."""
        base_dir = presets_dir or cls.DEFAULT_PRESETS_DIR

        raw_grades = cls._load_json_or_default(base_dir / "grades.json", DEFAULT_GRADES)
        raw_transitions = cls._load_json_or_default(
            base_dir / "transitions.json", DEFAULT_TRANSITIONS
        )
        raw_animations = cls._load_json_or_default(base_dir / "animations.json", DEFAULT_ANIMATIONS)
        raw_fonts = cls._load_json_or_default(base_dir / "fonts.json", DEFAULT_FONTS)

        grades = [GradePreset.model_validate(g) for g in raw_grades]
        transitions = [TransitionPreset.model_validate(t) for t in raw_transitions]
        animations = [AnimationPreset.model_validate(a) for a in raw_animations]
        fonts = [FontPreset.model_validate(f) for f in raw_fonts]

        return PresetsResponse(
            grades=grades,
            transitions=transitions,
            animations=animations,
            fonts=fonts,
        )
