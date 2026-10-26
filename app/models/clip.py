import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin

if TYPE_CHECKING:
    from app.models.job import Job
    from app.models.timeline import TimelineModel
    from app.models.video import Video


class Clip(Base, TimestampMixin):
    """Model representing an edited vertical clip of a video."""

    __tablename__ = "clips"

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
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    start_time: Mapped[float] = mapped_column(Float, nullable=False)
    end_time: Mapped[float] = mapped_column(Float, nullable=False)
    edit_spec: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="DRAFT", nullable=False)
    output_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    timeline_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("timelines.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Relationships
    video: Mapped["Video"] = relationship("Video", back_populates="clips")
    timeline: Mapped["TimelineModel | None"] = relationship("TimelineModel")
    jobs: Mapped[list["Job"]] = relationship(
        "Job",
        back_populates="clip",
        cascade="all, delete-orphan",
    )
