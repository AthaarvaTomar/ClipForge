import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, utc_now

if TYPE_CHECKING:
    from app.models.video import Video


class TimelineModel(Base, TimestampMixin):
    """Model representing a multi-track editing timeline."""

    __tablename__ = "timelines"

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
    version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    current_seq: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
        nullable=False,
    )
    source_duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Stored Timeline Pydantic model representation (tracks, items, metadata)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    def to_schema(self) -> Any:
        from app.schemas.timeline import Timeline as TimelineSchema

        return TimelineSchema.model_validate(self.data)


    # Relationships
    video: Mapped["Video"] = relationship("Video", back_populates="timelines")
    ops: Mapped[list["TimelineOpModel"]] = relationship(
        "TimelineOpModel",
        back_populates="timeline",
        cascade="all, delete-orphan",
        order_by="TimelineOpModel.seq",
    )
    versions: Mapped[list["TimelineVersionModel"]] = relationship(
        "TimelineVersionModel",
        back_populates="timeline",
        cascade="all, delete-orphan",
        order_by="TimelineVersionModel.version",
    )


class TimelineOpModel(Base):
    """Model representing an atomic timeline operation in the operation log."""

    __tablename__ = "timeline_ops"
    __table_args__ = (
        UniqueConstraint("timeline_id", "seq", name="uq_timeline_ops_timeline_seq"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timeline_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("timelines.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    group_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    op: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    inverse_op: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    # Actor: 'user' or 'agent'
    actor: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[Any] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    # Relationships
    timeline: Mapped["TimelineModel"] = relationship(
        "TimelineModel",
        back_populates="ops",
    )


class TimelineVersionModel(Base):
    """Model representing a complete timeline snapshot taken every N operations."""

    __tablename__ = "timeline_versions"
    __table_args__ = (
        UniqueConstraint(
            "timeline_id",
            "version",
            name="uq_timeline_versions_timeline_version",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timeline_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("timelines.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[Any] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    # Relationships
    timeline: Mapped["TimelineModel"] = relationship(
        "TimelineModel",
        back_populates="versions",
    )


# Convenient alias
Timeline = TimelineModel
