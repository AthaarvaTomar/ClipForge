from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class VideoBase(BaseModel):
    filename: str
    duration: float | None = None
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    orientation: str | None = None
    status: str = "uploaded"


class VideoResponse(VideoBase):
    id: str
    file_path: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class VideoListResponse(BaseModel):
    videos: list[VideoResponse]
    total: int


class VideoAssetsResponse(BaseModel):
    video_id: str
    ready: bool
    proxy_url: str
    thumbnail_strip_url: str
    waveform_url: str
    manifest: dict[str, Any] | None = None
