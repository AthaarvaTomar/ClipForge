from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.clip import Clip
from app.models.job import Job
from app.models.transcript import Transcript
from app.models.video import Video
from app.schemas.clip import ClipListResponse
from app.schemas.job import JobResponse
from app.services.job_service import JobService
from app.tasks.highlight_task import detect_highlights_task

router = APIRouter(prefix="/highlights", tags=["Highlights"])


@router.post(
    "/{video_id}",
    response_model=JobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Enqueue a highlight detection job for a video",
)
def create_highlights_job(
    video_id: str,
    db: Session = Depends(get_db),
) -> Job:
    """Validate video and transcript, create a highlight detection job, and enqueue Celery task."""
    video = db.scalar(select(Video).where(Video.id == video_id))
    if not video:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Video with id '{video_id}' not found",
        )

    transcript = db.scalar(select(Transcript).where(Transcript.video_id == video_id))
    if not transcript or not transcript.text.strip():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"Transcript not found for video '{video_id}'. "
                "Please enqueue and complete a transcription job first."
            ),
        )

    job = JobService.create_job(
        db=db,
        job_type="highlights",
        video_id=video_id,
    )
    detect_highlights_task.delay(
        job_id=job.id,
        video_id=video_id,
    )
    return job


@router.get(
    "/{video_id}",
    response_model=ClipListResponse,
    summary="Get all detected draft clips for a video",
)
def get_video_highlights(
    video_id: str,
    db: Session = Depends(get_db),
) -> ClipListResponse:
    """Fetch all draft clips created for the given video."""
    video = db.scalar(select(Video).where(Video.id == video_id))
    if not video:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Video with id '{video_id}' not found",
        )

    clips = list(
        db.scalars(
            select(Clip).where(Clip.video_id == video_id).order_by(Clip.created_at.asc())
        ).all()
    )

    return ClipListResponse(
        video_id=video_id,
        total=len(clips),
        clips=clips,  # type: ignore[arg-type]
    )
