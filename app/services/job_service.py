from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.job import Job


class JobService:
    """Service handling background job state transitions and progress reporting."""

    @staticmethod
    def create_job(
        db: Session,
        job_type: str,
        video_id: str | None = None,
        clip_id: str | None = None,
        initial_progress: int = 0,
    ) -> Job:
        """Create a new job in the database with PENDING status."""
        job = Job(
            job_type=job_type,
            status="PENDING",
            progress=initial_progress,
            video_id=video_id,
            clip_id=clip_id,
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        return job

    @staticmethod
    def update_progress(
        job_id: str,
        progress: int,
        status: str = "PROCESSING",
        error_message: str | None = None,
        result_data: dict[str, Any] | None = None,
    ) -> Job | None:
        """Update job progress and state in the database using a dedicated session."""
        db = SessionLocal()
        try:
            job = db.scalar(select(Job).where(Job.id == job_id))
            if not job:
                return None
            job.progress = max(0, min(100, progress))
            job.status = status
            if error_message is not None:
                job.error_message = error_message
            if result_data is not None:
                job.result_data = result_data
            db.commit()
            db.refresh(job)
            return job
        finally:
            db.close()

    @staticmethod
    def get_job(db: Session, job_id: str) -> Job | None:
        """Fetch a job by ID."""
        return db.scalar(select(Job).where(Job.id == job_id))

    @staticmethod
    def cancel_job(job_id: str) -> Job | None:
        """Mark a job as CANCELLED."""
        db = SessionLocal()
        try:
            job = db.scalar(select(Job).where(Job.id == job_id))
            if not job:
                return None
            job.status = "CANCELLED"
            db.commit()
            db.refresh(job)
            return job
        finally:
            db.close()

    @staticmethod
    def is_job_cancelled(job_id: str) -> bool:
        """Check if a job has been cancelled."""
        db = SessionLocal()
        try:
            job = db.scalar(select(Job).where(Job.id == job_id))
            return bool(job and job.status == "CANCELLED")
        finally:
            db.close()
