"""Pydantic schemas for Phase 5: Footage Indexing."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SceneItem(BaseModel):
    """Scene cut boundary identified by PySceneDetect."""

    model_config = ConfigDict(extra="ignore")

    index: int
    start_time: float
    end_time: float
    duration: float


class SilenceRange(BaseModel):
    """Audio silence interval identified by FFmpeg silencedetect."""

    model_config = ConfigDict(extra="ignore")

    start_time: float
    end_time: float
    duration: float


class FillerItem(BaseModel):
    """Detected filler word token with timestamps from transcript."""

    model_config = ConfigDict(extra="ignore")

    word: str
    start_time: float
    end_time: float
    confidence: float = 1.0


class TakeItem(BaseModel):
    """A single take within a repeated sentence/paragraph group."""

    model_config = ConfigDict(extra="ignore")

    take_index: int
    text: str
    start_time: float
    end_time: float
    score: float = 0.0
    is_best: bool = False


class TakeGroup(BaseModel):
    """Group of repeated near-duplicate takes with chosen best candidate."""

    model_config = ConfigDict(extra="ignore")

    group_id: str
    takes: list[TakeItem] = Field(default_factory=list)
    chosen_take_index: int = 0


class VisualScene(BaseModel):
    """Visual understanding description and tags for a scene frame."""

    model_config = ConfigDict(extra="ignore")

    scene_index: int
    timestamp: float
    caption: str
    tags: list[str] = Field(default_factory=list)


class ChapterItem(BaseModel):
    """Thematic chapter marker across the video."""

    model_config = ConfigDict(extra="ignore")

    title: str
    start_time: float
    end_time: float
    summary: str = ""


class HookCandidate(BaseModel):
    """Primary viral opening hook candidate."""

    model_config = ConfigDict(extra="ignore")

    start_time: float
    end_time: float
    hook: str
    score: float = 9.0
    reason: str = ""


class VideoIndexResponse(BaseModel):
    """Complete footage index response for GET /api/videos/{id}/index."""

    model_config = ConfigDict(extra="ignore")

    video_id: str
    status: str
    error_message: str | None = None
    scenes: list[SceneItem] = Field(default_factory=list)
    silences: list[SilenceRange] = Field(default_factory=list)
    fillers: list[FillerItem] = Field(default_factory=list)
    repeated_takes: list[TakeGroup] = Field(default_factory=list)
    visuals: list[VisualScene] = Field(default_factory=list)
    chapters: list[ChapterItem] = Field(default_factory=list)
    hook: HookCandidate | None = None
    highlights: list[dict[str, Any]] = Field(default_factory=list)
