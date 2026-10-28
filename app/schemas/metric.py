from datetime import datetime

from pydantic import BaseModel, ConfigDict


class MetricItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    task_id: str
    task_name: str
    queue_name: str
    wait_time_ms: float
    execution_time_ms: float
    total_time_ms: float
    input_duration_seconds: float | None = None
    realtime_factor: float | None = None
    created_at: datetime


class QueueMetricSummary(BaseModel):
    queue_name: str
    task_count: int
    avg_wait_time_ms: float
    avg_execution_time_ms: float


class MetricsSummary(BaseModel):
    total_tasks: int
    avg_wait_time_ms: float
    avg_render_time_ms: float
    p50_render_time_ms: float
    p95_render_time_ms: float
    avg_realtime_factor: float


class MetricsResponse(BaseModel):
    summary: MetricsSummary
    queues: list[QueueMetricSummary]
    recent: list[MetricItem]
