import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin

if TYPE_CHECKING:
    from app.models.clip import Clip
    from app.models.job import Job
    from app.models.timeline import TimelineModel
    from app.models.transcript import Transcript


class Video(Base, TimestampMixin):
    """Model representing an uploaded source video."""

    __tablename__ = "videos"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    duration: Mapped[float | None] = mapped_column(Float, nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fps: Mapped[float | None] = mapped_column(Float, nullable=True)
    # orientation: landscape, portrait, square
    orientation: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="uploaded", nullable=False)

    # Relationships
    transcripts: Mapped[list["Transcript"]] = relationship(
        "Transcript",
        back_populates="video",
        cascade="all, delete-orphan",
    )
    clips: Mapped[list["Clip"]] = relationship(
        "Clip",
        back_populates="video",
        cascade="all, delete-orphan",
    )
    jobs: Mapped[list["Job"]] = relationship(
        "Job",
        back_populates="video",
        cascade="all, delete-orphan",
    )
    timelines: Mapped[list["TimelineModel"]] = relationship(
        "TimelineModel",
        back_populates="video",
        cascade="all, delete-orphan",
    )

