import uuid
from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy import JSON, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin

if TYPE_CHECKING:
    from app.models.clip import Clip
    from app.models.video import Video


class Job(Base, TimestampMixin):
    """Model representing an asynchronous background task."""

    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    job_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="PENDING", nullable=False)
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    video_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("videos.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    clip_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("clips.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    # Relationships
    video: Mapped[Optional["Video"]] = relationship("Video", back_populates="jobs")
    clip: Mapped[Optional["Clip"]] = relationship("Clip", back_populates="jobs")
