import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin

if TYPE_CHECKING:
    from app.models.video import Video


class Transcript(Base, TimestampMixin):
    """Model representing transcription results for a video."""

    __tablename__ = "transcripts"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    video_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("videos.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    language: Mapped[str] = mapped_column(String(16), default="en", nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    words: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)

    # Relationships
    video: Mapped["Video"] = relationship("Video", back_populates="transcripts")
