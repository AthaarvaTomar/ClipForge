import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Float, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class TaskMetricModel(Base):
    """Database model for tracking task execution and queue wait timings."""

    __tablename__ = "task_metrics"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    task_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    task_name: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    queue_name: Mapped[str] = mapped_column(String(32), default="default", nullable=False)
    wait_time_ms: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    execution_time_ms: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    total_time_ms: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    input_duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    realtime_factor: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
