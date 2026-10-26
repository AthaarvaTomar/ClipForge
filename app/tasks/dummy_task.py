import time
from typing import Any

from celery import Task

from app.services.job_service import JobService
from app.tasks.celery_app import celery_app


@celery_app.task(bind=True, name="app.tasks.run_dummy_task")
def run_dummy_task(
    self: Task,
    job_id: str,
    steps: int = 5,
    delay_seconds: float = 0.05,
) -> dict[str, Any]:
    """Simulate an asynchronous background job progressing from 0% to 100%."""
    # Mark as PROCESSING at 0%
    JobService.update_progress(job_id=job_id, progress=0, status="PROCESSING")
    if getattr(self.request, "id", None):
        try:
            self.update_state(state="PROCESSING", meta={"progress": 0})
        except Exception:
            pass

    for step in range(1, steps + 1):
        if delay_seconds > 0:
            time.sleep(delay_seconds)
        pct = int((step / steps) * 100)
        status = "PROCESSING" if pct < 100 else "COMPLETED"
        result_payload = (
            {"steps_completed": step, "message": "Dummy job completed"}
            if pct == 100
            else None
        )

        JobService.update_progress(
            job_id=job_id,
            progress=pct,
            status=status,
            result_data=result_payload,
        )
        if getattr(self.request, "id", None):
            try:
                self.update_state(state=status, meta={"progress": pct})
            except Exception:
                pass

    return {"job_id": job_id, "progress": 100, "status": "COMPLETED"}
