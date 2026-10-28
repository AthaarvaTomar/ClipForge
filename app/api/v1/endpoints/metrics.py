from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.metric import MetricItem, MetricsResponse
from app.services.metric_service import MetricService

router = APIRouter(prefix="/metrics", tags=["Metrics"])


@router.get("", response_model=MetricsResponse)
def get_metrics(db: Session = Depends(get_db)) -> MetricsResponse:
    """Retrieve operational and performance metrics across queues and render tasks."""
    return MetricService.get_metrics_summary(db)


@router.post("/record", response_model=MetricItem)
def record_metric(
    task_id: str,
    task_name: str,
    queue_name: str = "default",
    wait_time_ms: float = 0.0,
    execution_time_ms: float = 0.0,
    input_duration_seconds: float | None = None,
    db: Session = Depends(get_db),
) -> MetricItem:
    """Record execution timing telemetry for a task."""
    metric = MetricService.record_metric(
        db=db,
        task_id=task_id,
        task_name=task_name,
        queue_name=queue_name,
        wait_time_ms=wait_time_ms,
        execution_time_ms=execution_time_ms,
        input_duration_seconds=input_duration_seconds,
    )
    return MetricItem.model_validate(metric)
