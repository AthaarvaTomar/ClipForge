"""Pydantic schemas for Media Assets and Stock Providers (Milestone M1)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class AttributionInfo(BaseModel):
    """Creator and source license attribution information."""

    author: str = Field(..., description="Creator or photographer name")
    author_url: str | None = Field(default=None, description="Creator profile URL")
    provider: Literal["pexels", "pixabay", "upload", "local"] = Field(
        ..., description="Source platform name"
    )
    license: str = Field(default="Free to use with attribution", description="License summary")
    source_url: str | None = Field(default=None, description="Original asset webpage URL")


class StockItem(BaseModel):
    """An external stock media item available for search and import."""

    id: str = Field(..., description="Provider unique asset ID")
    provider: Literal["pexels", "pixabay"] = Field(..., description="Provider name")
    title: str = Field(..., description="Asset title or description")
    media_type: Literal["video", "image"] = Field(..., description="Type of media")
    thumbnail_url: str = Field(..., description="Thumbnail preview image URL")
    preview_url: str = Field(..., description="Streaming or short preview URL")
    download_url: str = Field(..., description="High-resolution media download URL")
    duration_s: float | None = Field(default=None, description="Duration in seconds if video")
    width: int | None = Field(default=None, description="Width in pixels")
    height: int | None = Field(default=None, description="Height in pixels")
    attribution: AttributionInfo = Field(..., description="Attribution metadata")


class StockSearchResponse(BaseModel):
    """Response returned when searching Pexels or Pixabay."""

    query: str
    provider: str
    total_results: int
    page: int
    per_page: int
    items: list[StockItem]


class ImportAssetRequest(BaseModel):
    """Payload to download an external stock asset into the project library."""

    stock_item: StockItem
    custom_name: str | None = None


class AssetResponse(BaseModel):
    """Response representing a local or imported media asset."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    media_type: str
    source_type: str
    file_path: str
    thumbnail_url: str | None = None
    preview_url: str | None = None
    attribution: dict[str, Any] | None = None
    duration_ms: int | None = None
    width: int | None = None
    height: int | None = None
    file_size: int
    tags: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class AssetListResponse(BaseModel):
    """Paginated response for media assets."""

    total: int
    items: list[AssetResponse]
