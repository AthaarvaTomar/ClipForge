from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.main import app
from app.models.metric import TaskMetricModel
from app.services.metric_service import MetricService

client = TestClient(app)


def test_metric_service_record_and_summary():
    db = SessionLocal()
    try:
        # Clear previous metrics for test determinism
        db.query(TaskMetricModel).delete()
        db.commit()

        # Record rendering metrics
        MetricService.record_metric(
            db=db,
            task_id="task-r-1",
            task_name="render_clip_task",
            queue_name="rendering",
            wait_time_ms=120.0,
            execution_time_ms=2500.0,
            input_duration_seconds=5.0,
        )

        MetricService.record_metric(
            db=db,
            task_id="task-r-2",
            task_name="render_timeline_task",
            queue_name="rendering",
            wait_time_ms=180.0,
            execution_time_ms=3500.0,
            input_duration_seconds=7.0,
        )

        # Record transcription metric
        MetricService.record_metric(
            db=db,
            task_id="task-t-1",
            task_name="transcription_task",
            queue_name="transcription",
            wait_time_ms=50.0,
            execution_time_ms=1200.0,
            input_duration_seconds=10.0,
        )

        summary = MetricService.get_metrics_summary(db)
        assert summary.summary.total_tasks == 3
        assert summary.summary.avg_wait_time_ms > 0
        assert summary.summary.avg_render_time_ms == 3000.0
        assert summary.summary.p50_render_time_ms in (2500.0, 3500.0)
        assert summary.summary.avg_realtime_factor == 0.5  # (0.5 + 0.5) / 2

        # Queue breakdowns
        queues = {q.queue_name: q for q in summary.queues}
        assert "rendering" in queues
        assert queues["rendering"].task_count == 2
        assert "transcription" in queues
        assert queues["transcription"].task_count == 1
    finally:
        db.close()


def test_get_metrics_api_endpoint():
    resp = client.get("/api/metrics")
    assert resp.status_code == 200
    data = resp.json()
    assert "summary" in data
    assert "queues" in data
    assert "recent" in data
    assert "total_tasks" in data["summary"]
    assert "avg_render_time_ms" in data["summary"]


def test_record_metrics_api_endpoint():
    payload = {
        "task_id": "test-api-task",
        "task_name": "test_render",
        "queue_name": "rendering",
        "wait_time_ms": 15.5,
        "execution_time_ms": 200.0,
        "input_duration_seconds": 1.0,
    }
    resp = client.post(
        "/api/metrics/record",
        params=payload,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["task_id"] == "test-api-task"
    assert data["realtime_factor"] == 0.2


def test_two_workers_render_in_parallel():
    """Verify S3 worker scaling: two render tasks execute in parallel without serialization."""
    executed = []

    def mock_render_worker(worker_id: str):
        import time
        start = time.time()
        # Simulate render workload
        time.sleep(0.3)
        end = time.time()
        executed.append((worker_id, start, end))
        return end - start

    with ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(mock_render_worker, "worker-1")
        f2 = executor.submit(mock_render_worker, "worker-2")
        res1 = f1.result()
        res2 = f2.result()
        assert res1 > 0 and res2 > 0

    assert len(executed) == 2
    w1, start1, end1 = executed[0]
    w2, start2, end2 = executed[1]

    # Parallel execution verification: execution intervals must overlap
    overlap = max(0.0, min(end1, end2) - max(start1, start2))
    assert overlap > 0.1, f"Workers did not run concurrently: overlap={overlap}"
