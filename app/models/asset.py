"""Media Asset database model (Milestone M1).

Represents uploaded or imported media assets (B-roll video, overlay images, music, SFX)
with provider attribution (Pexels, Pixabay, Local).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import JSON, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin


class MediaAsset(Base, TimestampMixin):
    """Database model for media assets in the ClipForge asset library."""

    __tablename__ = "media_assets"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # media_type: "video", "image", "audio", "music"
    media_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    # source_type: "upload", "pexels", "pixabay", "local"
    source_type: Mapped[str] = mapped_column(String(32), nullable=False, default="upload")
    file_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    thumbnail_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    preview_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    # Attribution information (e.g. {"author": "...", "provider": "pexels"})
    attribution: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    # Media dimensions and duration
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    file_size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Optional tags / keywords
    tags: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
