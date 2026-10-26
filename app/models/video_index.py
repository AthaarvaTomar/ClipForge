import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin

if TYPE_CHECKING:
    from app.models.video import Video


class VideoIndex(Base, TimestampMixin):
    """Model representing a comprehensive AI index of video footage (Phase 5)."""

    __tablename__ = "video_indices"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    video_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("videos.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
    )
    # Status: PENDING, INDEXING, READY, FAILED
    status: Mapped[str] = mapped_column(String(32), default="PENDING", nullable=False)
    error_message: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    # I1: Scene boundaries [{index, start_time, end_time, duration}]
    scenes: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)

    # I2: Audio silences [{start_time, end_time, duration}]
    silences: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)

    # I2: Filler words [{word, start_time, end_time, confidence}]
    fillers: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)

    # I3: Repeated take groups [{group_id, takes: [...], chosen_take_index}]
    repeated_takes: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)

    # I4: Visual frame understanding [{scene_index, timestamp, caption, tags}]
    visuals: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)

    # I7: Generated chapters [{title, start_time, end_time, summary}]
    chapters: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)

    # I7: Primary viral hook candidate {start_time, end_time, hook, score, reason}
    hook: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    # Relationships
    video: Mapped["Video"] = relationship(
        "Video",
        back_populates="index",
    )
