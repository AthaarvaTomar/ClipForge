from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.job import Job
from app.models.transcript import Transcript
from app.models.video import Video
from app.schemas.job import JobResponse
from app.schemas.transcript import TranscriptResponse
from app.services.job_service import JobService
from app.tasks.transcription_task import transcribe_video_task

router = APIRouter(prefix="/transcripts", tags=["Transcripts"])


@router.post(
    "/{video_id}",
    response_model=JobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Enqueue a transcription job for a video",
)
def create_transcription_job(
    video_id: str,
    db: Session = Depends(get_db),
) -> Job:
    """Validate video existence, create a transcription job, and enqueue task."""
    video = db.scalar(select(Video).where(Video.id == video_id))
    if not video:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Video with id '{video_id}' not found",
        )

    job = JobService.create_job(
        db=db,
        job_type="transcription",
        video_id=video_id,
    )
    transcribe_video_task.delay(
        job_id=job.id,
        video_id=video_id,
    )
    return job


@router.get(
    "/{video_id}",
    response_model=TranscriptResponse,
    summary="Get transcript with word-level timestamps for a video",
)
def get_transcript(
    video_id: str,
    db: Session = Depends(get_db),
) -> Transcript:
    """Fetch the transcript and word timestamps for a specific video."""
    video = db.scalar(select(Video).where(Video.id == video_id))
    if not video:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Video with id '{video_id}' not found",
        )

    transcript = db.scalar(select(Transcript).where(Transcript.video_id == video_id))
    if not transcript:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"Transcript not found for video '{video_id}'. "
                "Please enqueue a transcription job first."
            ),
        )
    return transcript
