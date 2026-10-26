"""Celery background task for UI asset generation (Task R1)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from celery import Task
from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.video import Video
from app.services.asset_service import generate_assets
from app.services.job_service import JobService
from app.tasks.celery_app import celery_app


@celery_app.task(bind=True, name="app.tasks.generate_assets_task")
def generate_assets_task(
    self: Task,
    job_id: str,
    video_id: str,
    force: bool = False,
) -> dict[str, Any]:
    """Generate proxy video, thumbnail strip, and waveform peaks JSON for a video."""
    JobService.update_progress(job_id=job_id, progress=5, status="PROCESSING")
    if getattr(self.request, "id", None):
        try:
            self.update_state(state="PROCESSING", meta={"progress": 5})
        except Exception:
            pass

    db = SessionLocal()
    try:
        video = db.scalar(select(Video).where(Video.id == video_id))
        if not video:
            error_msg = f"Video with id '{video_id}' not found"
            JobService.update_progress(
                job_id=job_id,
                progress=100,
                status="FAILED",
                error_message=error_msg,
            )
            return {"error": error_msg}

        source_path = Path(video.file_path)
        if not source_path.is_file():
            error_msg = f"Source video file not found on disk: {video.file_path}"
            JobService.update_progress(
                job_id=job_id,
                progress=100,
                status="FAILED",
                error_message=error_msg,
            )
            return {"error": error_msg}

        def on_asset_progress(pct: int) -> None:
            JobService.update_progress(job_id=job_id, progress=pct, status="PROCESSING")
            if getattr(self.request, "id", None):
                try:
                    self.update_state(state="PROCESSING", meta={"progress": pct})
                except Exception:
                    pass

        manifest = generate_assets(
            video_id=video_id,
            source=source_path,
            duration=video.duration,
            force=force,
            on_progress=on_asset_progress,
        )

        JobService.update_progress(
            job_id=job_id,
            progress=100,
            status="COMPLETED",
            result_data=manifest,
        )
        if getattr(self.request, "id", None):
            try:
                self.update_state(state="COMPLETED", meta={"progress": 100})
            except Exception:
                pass

        return manifest

    except Exception as e:
        error_msg = str(e)
        JobService.update_progress(
            job_id=job_id,
            progress=100,
            status="FAILED",
            error_message=error_msg,
        )
        raise
    finally:
        db.close()
