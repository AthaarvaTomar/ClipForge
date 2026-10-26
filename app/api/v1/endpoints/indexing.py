"""API endpoints for Footage Indexing (Phase 5)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.job import Job
from app.models.video import Video
from app.models.video_index import VideoIndex
from app.schemas.index import VideoIndexResponse
from app.schemas.job import JobResponse
from app.services.job_service import JobService
from app.tasks.index_task import index_video_task

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/videos", tags=["indexing"])


@router.post(
    "/{video_id}/index",
    response_model=JobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger video footage indexing",
    description=(
        "Enqueue a background Celery task to run the complete indexing pipeline "
        "(scenes, silences, takes, visuals, chapters)."
    ),
)
def trigger_video_index(
    video_id: str,
    db: Session = Depends(get_db),
) -> Job:
    """Enqueue video indexing background job."""
    video = db.scalar(select(Video).where(Video.id == video_id))
    if not video:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Video with id '{video_id}' not found",
        )

    job = JobService.create_job(
        db=db,
        job_type="VIDEO_INDEX",
        video_id=video_id,
    )

    try:
        index_video_task.delay(job_id=job.id, video_id=video_id)
    except Exception as e:
        logger.warning(
            "Could not dispatch Celery task asynchronously (%s). Executing directly.",
            e,
        )
        index_video_task(job_id=job.id, video_id=video_id)

    db.refresh(job)
    return job


@router.get(
    "/{video_id}/index",
    response_model=VideoIndexResponse,
    status_code=status.HTTP_200_OK,
    summary="Get video footage index",
    description=(
        "Retrieve the complete AI index including scenes, silences, fillers, "
        "repeated takes, visuals, chapters, and hooks."
    ),
)
def get_video_index(
    video_id: str,
    db: Session = Depends(get_db),
) -> VideoIndexResponse:
    """Retrieve full footage index for a video."""
    video = db.scalar(select(Video).where(Video.id == video_id))
    if not video:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Video with id '{video_id}' not found",
        )

    v_idx = db.scalar(select(VideoIndex).where(VideoIndex.video_id == video_id))
    if not v_idx:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"Index for video '{video_id}' has not been generated yet. "
                f"POST to /api/videos/{video_id}/index first."
            ),
        )

    return VideoIndexResponse.model_validate(
        {
            "video_id": video_id,
            "status": v_idx.status,
            "error_message": v_idx.error_message,
            "scenes": v_idx.scenes or [],
            "silences": v_idx.silences or [],
            "fillers": v_idx.fillers or [],
            "repeated_takes": v_idx.repeated_takes or [],
            "visuals": v_idx.visuals or [],
            "chapters": v_idx.chapters or [],
            "hook": v_idx.hook,
            "highlights": [],
        }
    )
