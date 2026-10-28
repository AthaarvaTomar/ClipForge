"""Celery background task for video footage indexing (Milestone I6)."""

from __future__ import annotations

import logging
from typing import Any

from celery import Task

from app.core.database import SessionLocal
from app.services.index_orchestrator import IndexOrchestratorService
from app.services.job_service import JobService
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, name="app.tasks.index_video_task")
def index_video_task(
    self: Task,
    job_id: str,
    video_id: str,
) -> dict[str, Any]:
    """Execute complete footage indexing pipeline in background."""
    JobService.update_progress(job_id=job_id, progress=5, status="PROCESSING")
    if getattr(self.request, "id", None):
        try:
            self.update_state(
                state="PROCESSING",
                meta={"progress": 5, "stage": "Starting indexing"},
            )
        except Exception:
            pass

    db = SessionLocal()
    try:

        def on_index_progress(pct: int, msg: str) -> None:
            JobService.update_progress(job_id=job_id, progress=pct, status="PROCESSING")
            if getattr(self.request, "id", None):
                try:
                    self.update_state(
                        state="PROCESSING",
                        meta={"progress": pct, "stage": msg},
                    )
                except Exception:
                    pass

        index_record = IndexOrchestratorService.index_video(
            db=db,
            video_id=video_id,
            on_progress=on_index_progress,
        )

        result_payload = {
            "index_id": index_record.id,
            "video_id": video_id,
            "scenes_count": len(index_record.scenes),
            "silences_count": len(index_record.silences),
            "fillers_count": len(index_record.fillers),
            "repeated_takes_count": len(index_record.repeated_takes),
            "visuals_count": len(index_record.visuals),
            "chapters_count": len(index_record.chapters),
            "has_hook": bool(index_record.hook),
        }

        JobService.update_progress(
            job_id=job_id,
            progress=100,
            status="COMPLETED",
            result_data=result_payload,
        )
        if getattr(self.request, "id", None):
            try:
                self.update_state(state="COMPLETED", meta={"progress": 100})
            except Exception:
                pass

        return result_payload

    except Exception as e:
        error_msg = str(e)
        logger.exception("Error executing index_video_task: %s", error_msg)
        JobService.update_progress(
            job_id=job_id,
            progress=100,
            status="FAILED",
            error_message=error_msg,
        )
        raise
    finally:
        db.close()
