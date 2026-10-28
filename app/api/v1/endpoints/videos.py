import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.database import get_db
from app.models.video import Video
from app.schemas.job import JobResponse
from app.schemas.video import VideoAssetsResponse, VideoListResponse, VideoResponse
from app.services.asset_service import (
    assets_ready,
    delete_assets,
    proxy_path,
    read_manifest,
    strip_path,
    thumbs_dir,
    waveform_path,
)
from app.services.job_service import JobService
from app.services.video_probe import VideoProbeError, probe_video
from app.tasks.asset_task import generate_assets_task

router = APIRouter(prefix="/videos", tags=["Videos"])

ALLOWED_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
CHUNK_SIZE = 1024 * 1024  # 1 MB chunk


@router.post(
    "",
    response_model=VideoResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Streamed upload and probe a video",
)
async def upload_video(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> Video:
    filename = file.filename or "video.mp4"
    ext = Path(filename).suffix.lower()

    if ext not in ALLOWED_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_EXTENSIONS))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file format '{ext}'. Allowed extensions: {allowed}",
        )

    video_id = str(uuid.uuid4())
    destination = settings.UPLOAD_DIR / f"{video_id}{ext}"
    settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    total_bytes = 0

    try:
        with open(destination, "wb") as buffer:
            while chunk := await file.read(CHUNK_SIZE):
                total_bytes += len(chunk)
                if total_bytes > max_bytes:
                    limit_mb = settings.MAX_UPLOAD_SIZE_MB
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"File exceeds maximum allowed size of {limit_mb}MB",
                    )
                buffer.write(chunk)
    except Exception:
        if destination.exists():
            destination.unlink(missing_ok=True)
        raise

    # Probe video metadata using ffprobe
    try:
        metadata = probe_video(destination)
    except VideoProbeError as e:
        destination.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Video validation failed: {e}",
        ) from e

    # Persist in DB
    video = Video(
        id=video_id,
        filename=filename,
        file_path=str(destination.resolve()),
        duration=metadata.duration,
        width=metadata.width,
        height=metadata.height,
        fps=metadata.fps,
        orientation=metadata.orientation,
        status="ready",
    )
    db.add(video)
    db.commit()
    db.refresh(video)

    # Enqueue background asset generation (proxy 360p, thumbnails, waveform)
    job = JobService.create_job(db=db, job_type="ASSETS", video_id=video.id)
    generate_assets_task.delay(job_id=job.id, video_id=video.id)

    return video


@router.get("", response_model=VideoListResponse, summary="List all videos")
def list_videos(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> VideoListResponse:
    total = db.scalar(select(func.count(Video.id))) or 0
    query = select(Video).order_by(Video.created_at.desc()).offset(offset).limit(limit)
    videos = list(db.scalars(query).all())
    return VideoListResponse(
        videos=[VideoResponse.model_validate(v) for v in videos],
        total=total,
    )


@router.get("/{video_id}", response_model=VideoResponse, summary="Get video details")
def get_video(
    video_id: str,
    db: Session = Depends(get_db),
) -> Video:
    video = db.scalar(select(Video).where(Video.id == video_id))
    if not video:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Video with id '{video_id}' not found",
        )
    return video


@router.delete("/{video_id}", summary="Delete a video and its file")
def delete_video(
    video_id: str,
    db: Session = Depends(get_db),
) -> dict[str, str]:
    video = db.scalar(select(Video).where(Video.id == video_id))
    if not video:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Video with id '{video_id}' not found",
        )

    # Delete physical file
    file_path = Path(video.file_path)
    if file_path.exists():
        file_path.unlink(missing_ok=True)

    # Delete UI assets if present
    delete_assets(video_id)

    db.delete(video)
    db.commit()

    return {"message": "Video deleted successfully", "id": video_id}


@router.post(
    "/{video_id}/assets",
    response_model=JobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Enqueue video asset generation (proxy, thumbnails, waveform)",
)
def create_video_assets(
    video_id: str,
    force: bool = Query(default=False, description="Force regeneration even if assets exist"),
    db: Session = Depends(get_db),
) -> JobResponse:
    """Enqueue background generation of 360p proxy, thumbnails strip, and waveform peaks."""
    video = db.scalar(select(Video).where(Video.id == video_id))
    if not video:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Video with id '{video_id}' not found",
        )

    job = JobService.create_job(db=db, job_type="ASSETS", video_id=video.id)
    generate_assets_task.delay(job_id=job.id, video_id=video.id, force=force)
    return JobResponse.model_validate(job)


@router.get(
    "/{video_id}/assets",
    response_model=VideoAssetsResponse,
    summary="Get video asset status, URLs, and manifest",
)
def get_video_assets(
    video_id: str,
    db: Session = Depends(get_db),
) -> VideoAssetsResponse:
    """Return status and URLs for proxy video, thumbnail strip, and waveform peaks."""
    video = db.scalar(select(Video).where(Video.id == video_id))
    if not video:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Video with id '{video_id}' not found",
        )

    ready = assets_ready(video_id)
    manifest = read_manifest(video_id)
    return VideoAssetsResponse(
        video_id=video_id,
        ready=ready,
        proxy_url=f"/api/videos/{video_id}/proxy",
        thumbnail_strip_url=f"/api/videos/{video_id}/thumbnails/strip",
        waveform_url=f"/api/videos/{video_id}/waveform",
        manifest=manifest,
    )


@router.get(
    "/{video_id}/proxy",
    summary="Stream 360p video proxy for editor playback",
)
def get_video_proxy(
    video_id: str,
    db: Session = Depends(get_db),
) -> FileResponse:
    """Return the lightweight 360p proxy MP4 video."""
    video = db.scalar(select(Video).where(Video.id == video_id))
    if not video:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Video with id '{video_id}' not found",
        )

    p_file = proxy_path(video_id)
    if not p_file.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Proxy video not found or not ready yet for video '{video_id}'",
        )

    return FileResponse(
        path=str(p_file),
        media_type="video/mp4",
        filename=f"{video_id}_proxy.mp4",
    )


@router.get(
    "/{video_id}/waveform",
    summary="Get audio waveform peaks JSON",
)
def get_video_waveform(
    video_id: str,
    db: Session = Depends(get_db),
) -> FileResponse:
    """Return normalised audio peaks JSON for timeline waveform visualization."""
    video = db.scalar(select(Video).where(Video.id == video_id))
    if not video:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Video with id '{video_id}' not found",
        )

    w_file = waveform_path(video_id)
    if not w_file.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Waveform data not found or not ready yet for video '{video_id}'",
        )

    return FileResponse(
        path=str(w_file),
        media_type="application/json",
        filename=f"{video_id}_waveform.json",
    )


@router.get(
    "/{video_id}/thumbnails/strip",
    summary="Get tiled horizontal thumbnail strip",
)
def get_video_thumbnail_strip(
    video_id: str,
    db: Session = Depends(get_db),
) -> FileResponse:
    """Return the horizontally tiled thumbnail strip image."""
    video = db.scalar(select(Video).where(Video.id == video_id))
    if not video:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Video with id '{video_id}' not found",
        )

    s_file = strip_path(video_id)
    if not s_file.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Thumbnail strip not found or not ready yet for video '{video_id}'",
        )

    return FileResponse(
        path=str(s_file),
        media_type="image/jpeg",
        filename="strip.jpg",
    )


@router.get(
    "/{video_id}/thumbnails",
    summary="Get thumbnail strip or list",
)
def get_video_thumbnails(
    video_id: str,
    db: Session = Depends(get_db),
) -> FileResponse:
    """Alias for /thumbnails/strip returning the tiled thumbnail strip."""
    return get_video_thumbnail_strip(video_id=video_id, db=db)


@router.get(
    "/{video_id}/thumbnails/{filename}",
    summary="Get individual thumbnail image",
)
def get_video_thumbnail_frame(
    video_id: str,
    filename: str,
    db: Session = Depends(get_db),
) -> FileResponse:
    """Return an individual thumbnail image from the thumbnails directory."""
    video = db.scalar(select(Video).where(Video.id == video_id))
    if not video:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Video with id '{video_id}' not found",
        )

    thumb_file = thumbs_dir(video_id) / filename
    if not thumb_file.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Thumbnail '{filename}' not found for video '{video_id}'",
        )

    return FileResponse(
        path=str(thumb_file),
        media_type="image/jpeg",
        filename=filename,
    )
