"""Celery task for AI edit plan generation (Milestone P3)."""

import logging

from app.core.database import SessionLocal
from app.services.job_service import JobService
from app.services.planner_service import EditPlannerService
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.plan_task.generate_plan_task")
def generate_plan_task(plan_id: str, job_id: str) -> dict[str, str | int]:
    """Execute AI edit planner in background worker with progress tracking."""
    db = SessionLocal()
    try:
        JobService.update_progress(job_id=job_id, progress=20, status="PROCESSING")

        plan = EditPlannerService.execute_and_store_plan(db, plan_id)

        if plan.status == "FAILED":
            JobService.update_progress(
                job_id=job_id,
                progress=100,
                status="FAILED",
                error_message=plan.error_message or "Plan generation failed",
            )
            return {"status": "FAILED", "plan_id": plan_id}

        JobService.update_progress(
            job_id=job_id,
            progress=100,
            status="COMPLETED",
            result_data={
                "plan_id": plan.id,
                "timeline_id": plan.timeline_id,
                "ops_count": len(plan.ops),
                "rationale": plan.rationale,
            },
        )
        return {"status": "SUCCESS", "plan_id": plan_id}
    except Exception as exc:
        logger.exception("generate_plan_task crashed for plan %s: %s", plan_id, exc)
        JobService.update_progress(
            job_id=job_id,
            progress=100,
            status="FAILED",
            error_message=str(exc),
        )
        return {"status": "FAILED", "error": str(exc)}
    finally:
        db.close()
