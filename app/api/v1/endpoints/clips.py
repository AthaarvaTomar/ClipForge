from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.database import get_db
from app.models.clip import Clip
from app.models.video import Video
from app.schemas.clip import ClipCreate, ClipListResponse, ClipResponse, ClipUpdate
from app.schemas.job import JobResponse
from app.schemas.timeline import Timeline
from app.services.ffmpeg_builder import extract_preview_frame
from app.services.job_service import JobService
from app.services.timeline_service import TimelineService
from app.tasks.render_task import render_clip_task

router = APIRouter(prefix="/clips", tags=["Clips"])



@router.post(
    "",
    response_model=ClipResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new clip with EditSpec",
)
def create_clip(
    payload: ClipCreate,
    db: Session = Depends(get_db),
) -> Clip:
    """Create a new draft clip configured with validated EditSpec."""
    video = db.scalar(select(Video).where(Video.id == payload.video_id))
    if not video:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Video with id '{payload.video_id}' not found",
        )

    # Validate cuts against source video duration if available
    if video.duration is not None:
        for i, cut in enumerate(payload.edit_spec.cuts):
            if cut.end > video.duration + 0.5:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=(
                        f"Cut segment {i} end time ({cut.end}s) exceeds "
                        f"video duration ({video.duration:.2f}s)"
                    ),
                )

    clip = Clip(
        video_id=payload.video_id,
        title=payload.title,
        start_time=payload.start_time if payload.start_time is not None else 0.0,
        end_time=payload.end_time if payload.end_time is not None else 0.0,
        edit_spec=payload.edit_spec.model_dump(),
        status=payload.status,
    )
    db.add(clip)
    db.commit()
    db.refresh(clip)
    return clip


@router.get(
    "",
    response_model=ClipListResponse,
    summary="List clips",
)
def list_clips(
    video_id: str | None = Query(default=None, description="Filter clips by video ID"),
    clip_status: str | None = Query(default=None, alias="status", description="Filter by status"),
    limit: int = Query(default=50, ge=1, le=100, description="Items per page"),
    offset: int = Query(default=0, ge=0, description="Items to skip"),
    db: Session = Depends(get_db),
) -> ClipListResponse:
    """List clips with optional filtering by video_id and status."""
    stmt = select(Clip)
    count_stmt = select(func.count(Clip.id))

    if video_id:
        stmt = stmt.where(Clip.video_id == video_id)
        count_stmt = count_stmt.where(Clip.video_id == video_id)
    if clip_status:
        stmt = stmt.where(Clip.status == clip_status)
        count_stmt = count_stmt.where(Clip.status == clip_status)

    total = db.scalar(count_stmt) or 0
    ordered_stmt = stmt.order_by(Clip.created_at.desc()).offset(offset).limit(limit)
    clips = list(db.scalars(ordered_stmt).all())

    return ClipListResponse(
        video_id=video_id,
        total=total,
        clips=[ClipResponse.model_validate(c) for c in clips],
    )


@router.get(
    "/{clip_id}",
    response_model=ClipResponse,
    summary="Get clip by ID",
)
def get_clip(
    clip_id: str,
    db: Session = Depends(get_db),
) -> Clip:
    """Retrieve metadata and EditSpec for a specific clip."""
    clip = db.scalar(select(Clip).where(Clip.id == clip_id))
    if not clip:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Clip with id '{clip_id}' not found",
        )
    return clip


@router.patch(
    "/{clip_id}",
    response_model=ClipResponse,
    summary="Update clip title, times, or EditSpec",
)
def update_clip(
    clip_id: str,
    payload: ClipUpdate,
    db: Session = Depends(get_db),
) -> Clip:
    """Update an existing clip's EditSpec, title, times, or status."""
    clip = db.scalar(select(Clip).where(Clip.id == clip_id))
    if not clip:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Clip with id '{clip_id}' not found",
        )

    if payload.edit_spec is not None:
        # Validate cuts against video duration if available
        video = db.scalar(select(Video).where(Video.id == clip.video_id))
        if video and video.duration is not None:
            for i, cut in enumerate(payload.edit_spec.cuts):
                if cut.end > video.duration + 0.5:
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                        detail=(
                            f"Cut segment {i} end time ({cut.end}s) exceeds "
                            f"video duration ({video.duration:.2f}s)"
                        ),
                    )

        clip.edit_spec = payload.edit_spec.model_dump()
        if payload.start_time is None and payload.edit_spec.cuts:
            clip.start_time = payload.edit_spec.cuts[0].start
        if payload.end_time is None and payload.edit_spec.cuts:
            clip.end_time = payload.edit_spec.cuts[-1].end

    if payload.title is not None:
        clip.title = payload.title
    if payload.start_time is not None:
        clip.start_time = payload.start_time
    if payload.end_time is not None:
        clip.end_time = payload.end_time

    if clip.end_time <= clip.start_time:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"end_time ({clip.end_time}s) must be strictly greater than "
                f"start_time ({clip.start_time}s)"
            ),
        )

    if payload.status is not None:
        clip.status = payload.status

    db.commit()
    db.refresh(clip)
    return clip


@router.delete(
    "/{clip_id}",
    summary="Delete a clip",
)
def delete_clip(
    clip_id: str,
    db: Session = Depends(get_db),
) -> dict[str, bool | str]:
    """Delete a clip record and its associated rendered output file if present."""
    clip = db.scalar(select(Clip).where(Clip.id == clip_id))
    if not clip:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Clip with id '{clip_id}' not found",
        )

    # Clean up output file if it exists
    if clip.output_path:
        out_path = Path(clip.output_path)
        if out_path.exists():
            out_path.unlink(missing_ok=True)

    db.delete(clip)
    db.commit()
    return {"ok": True, "message": f"Clip '{clip_id}' deleted successfully"}


@router.get(
    "/{clip_id}/timeline",
    response_model=Timeline,
    summary="Open or convert draft clip into a multi-track Timeline",
)
def get_clip_timeline(
    clip_id: str,
    db: Session = Depends(get_db),
) -> Timeline:
    """Open or convert a draft clip and its EditSpec into a valid multi-track Timeline (Task T7).

    - If a timeline has already been created for this clip, returns the active timeline.
    - Otherwise, automatically converts cuts, grade, transitions, and captions into tracks/items,
      persists the timeline, links clip.timeline_id, and returns the Timeline.
    """
    clip = db.scalar(select(Clip).where(Clip.id == clip_id))
    if not clip:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Clip with id '{clip_id}' not found",
        )
    return TimelineService.open_clip_timeline(db, clip_id, force_recreate=False)


@router.post(
    "/{clip_id}/timeline",
    response_model=Timeline,
    summary="Force re-convert draft clip into a fresh Timeline",
)
def convert_clip_timeline(
    clip_id: str,
    db: Session = Depends(get_db),
) -> Timeline:
    """Force re-convert a draft clip's current EditSpec into a fresh Timeline (Task T7)."""
    clip = db.scalar(select(Clip).where(Clip.id == clip_id))
    if not clip:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Clip with id '{clip_id}' not found",
        )
    return TimelineService.open_clip_timeline(db, clip_id, force_recreate=True)


@router.post(
    "/{clip_id}/render",
    response_model=JobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Enqueue clip render job",
)
def render_clip(
    clip_id: str,
    db: Session = Depends(get_db),
) -> JobResponse:
    """Dispatch background rendering task for a clip."""
    clip = db.scalar(select(Clip).where(Clip.id == clip_id))
    if not clip:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Clip with id '{clip_id}' not found",
        )

    if clip.status == "RENDERING":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Clip '{clip_id}' is already being rendered",
        )

    # Check active renders against concurrency limit
    active_renders = (
        db.scalar(select(func.count(Clip.id)).where(Clip.status == "RENDERING")) or 0
    )
    if active_renders >= settings.RENDER_CONCURRENCY_LIMIT:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Maximum concurrent renders reached ({active_renders}/"
                f"{settings.RENDER_CONCURRENCY_LIMIT}). Please wait for current renders to finish."
            ),
        )

    video = db.scalar(select(Video).where(Video.id == clip.video_id))

    if not video or not video.file_path or not Path(video.file_path).is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Source video file not found on disk",
        )

    job = JobService.create_job(
        db=db,
        job_type="RENDER",
        clip_id=clip.id,
        video_id=clip.video_id,
        initial_progress=0,
    )

    clip.status = "QUEUED"
    db.commit()

    render_clip_task.delay(job.id, clip.id)
    return JobResponse.model_validate(job)


@router.get(
    "/{clip_id}/download",
    summary="Download rendered clip MP4",
)
def download_clip(
    clip_id: str,
    db: Session = Depends(get_db),
) -> FileResponse:
    """Download the completed MP4 video file for a clip."""
    clip = db.scalar(select(Clip).where(Clip.id == clip_id))
    if not clip:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Clip with id '{clip_id}' not found",
        )

    if clip.status != "COMPLETED" or not clip.output_path:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Clip has not finished rendering yet (current status: '{clip.status}')",
        )

    out_file = Path(clip.output_path)
    if not out_file.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Rendered video file not found at: {clip.output_path}",
        )

    filename = f"{clip.title.strip() or clip.id}.mp4"
    return FileResponse(
        path=str(out_file),
        media_type="video/mp4",
        filename=filename,
    )


@router.get(
    "/{clip_id}/preview-frame",
    summary="Extract preview frame from clip",
)
def get_preview_frame(
    clip_id: str,
    time: float = Query(default=0.5, ge=0.0, description="Offset in seconds from clip start"),
    db: Session = Depends(get_db),
) -> Response:
    """Extract a single JPEG frame at the specified offset."""
    clip = db.scalar(select(Clip).where(Clip.id == clip_id))
    if not clip:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Clip with id '{clip_id}' not found",
        )

    # If already rendered and output file exists, extract directly from rendered output
    if clip.output_path and Path(clip.output_path).is_file():
        frame_bytes = extract_preview_frame(clip.output_path, timestamp=time)
        return Response(content=frame_bytes, media_type="image/jpeg")

    # Otherwise, extract from source video at mapped timestamp
    video = db.scalar(select(Video).where(Video.id == clip.video_id))
    if not video or not video.file_path or not Path(video.file_path).is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Source video file not found",
        )

    # Map time offset to source video timeline
    cuts = clip.edit_spec.get("cuts", []) if isinstance(clip.edit_spec, dict) else []
    if cuts:
        accum = 0.0
        src_time = float(cuts[0].get("start", clip.start_time))
        for cut in cuts:
            dur = float(cut.get("end", 0.0)) - float(cut.get("start", 0.0))
            if accum + dur >= time:
                src_time = float(cut.get("start", 0.0)) + (time - accum)
                break
            accum += dur
        else:
            src_time = float(cuts[-1].get("end", clip.end_time))
    else:
        src_time = clip.start_time + time

    frame_bytes = extract_preview_frame(video.file_path, timestamp=src_time)
    return Response(content=frame_bytes, media_type="image/jpeg")

