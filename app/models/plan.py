"""SQLAlchemy database model for AI edit plans (Milestone P3)."""

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin

if TYPE_CHECKING:
    from app.models.timeline import TimelineModel


class EditPlanModel(Base, TimestampMixin):
    """Stores generated, validated, and applied AI editing plans."""

    __tablename__ = "edit_plans"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    timeline_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("timelines.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    job_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    ops: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        default="PENDING",
        nullable=False,
        index=True,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    timeline: Mapped["TimelineModel"] = relationship("TimelineModel", back_populates="plans")
