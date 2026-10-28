
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.metric import TaskMetricModel
from app.schemas.metric import MetricsResponse, MetricsSummary, QueueMetricSummary


class MetricService:
    @staticmethod
    def record_metric(
        db: Session,
        task_id: str,
        task_name: str,
        queue_name: str,
        wait_time_ms: float,
        execution_time_ms: float,
        input_duration_seconds: float | None = None,
    ) -> TaskMetricModel:
        total_time_ms = max(0.0, wait_time_ms) + max(0.0, execution_time_ms)
        realtime_factor = None
        if input_duration_seconds and input_duration_seconds > 0:
            realtime_factor = round((execution_time_ms / 1000.0) / input_duration_seconds, 3)

        metric = TaskMetricModel(
            task_id=task_id,
            task_name=task_name,
            queue_name=queue_name,
            wait_time_ms=round(max(0.0, wait_time_ms), 2),
            execution_time_ms=round(max(0.0, execution_time_ms), 2),
            total_time_ms=round(total_time_ms, 2),
            input_duration_seconds=input_duration_seconds,
            realtime_factor=realtime_factor,
        )
        db.add(metric)
        db.commit()
        db.refresh(metric)
        return metric

    @staticmethod
    def get_metrics_summary(db: Session) -> MetricsResponse:
        stmt = select(TaskMetricModel).order_by(TaskMetricModel.created_at.desc())
        all_metrics = list(db.scalars(stmt).all())

        total_tasks = len(all_metrics)
        if total_tasks == 0:
            return MetricsResponse(
                summary=MetricsSummary(
                    total_tasks=0,
                    avg_wait_time_ms=0.0,
                    avg_render_time_ms=0.0,
                    p50_render_time_ms=0.0,
                    p95_render_time_ms=0.0,
                    avg_realtime_factor=0.0,
                ),
                queues=[],
                recent=[],
            )

        avg_wait_time_ms = sum(m.wait_time_ms for m in all_metrics) / total_tasks

        render_tasks = [
            m for m in all_metrics if m.queue_name == "rendering" or "render" in m.task_name
        ]
        render_times = sorted([m.execution_time_ms for m in render_tasks])

        if render_times:
            avg_render_time_ms = sum(render_times) / len(render_times)
            p50_idx = int(len(render_times) * 0.5)
            p95_idx = min(len(render_times) - 1, int(len(render_times) * 0.95))
            p50_render_time_ms = render_times[p50_idx]
            p95_render_time_ms = render_times[p95_idx]
        else:
            avg_render_time_ms = 0.0
            p50_render_time_ms = 0.0
            p95_render_time_ms = 0.0

        rt_factors = [m.realtime_factor for m in render_tasks if m.realtime_factor is not None]
        avg_realtime_factor = round(sum(rt_factors) / len(rt_factors), 3) if rt_factors else 0.0

        # Queues breakdown
        queue_names = sorted({m.queue_name for m in all_metrics})
        queue_summaries: list[QueueMetricSummary] = []
        for q in queue_names:
            q_items = [m for m in all_metrics if m.queue_name == q]
            queue_summaries.append(
                QueueMetricSummary(
                    queue_name=q,
                    task_count=len(q_items),
                    avg_wait_time_ms=round(sum(m.wait_time_ms for m in q_items) / len(q_items), 2),
                    avg_execution_time_ms=round(
                        sum(m.execution_time_ms for m in q_items) / len(q_items), 2
                    ),
                )
            )

        summary = MetricsSummary(
            total_tasks=total_tasks,
            avg_wait_time_ms=round(avg_wait_time_ms, 2),
            avg_render_time_ms=round(avg_render_time_ms, 2),
            p50_render_time_ms=round(p50_render_time_ms, 2),
            p95_render_time_ms=round(p95_render_time_ms, 2),
            avg_realtime_factor=avg_realtime_factor,
        )

        recent = all_metrics[:20]

        return MetricsResponse(
            summary=summary,
            queues=queue_summaries,
            recent=recent,  # type: ignore
        )
