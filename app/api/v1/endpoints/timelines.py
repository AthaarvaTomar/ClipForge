from pathlib import Path as FilePath

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.database import get_db
from app.models.job import Job
from app.models.video import Video
from app.schemas.job import JobResponse
from app.schemas.plan import ApplyPlanRequest, PlanRequest, PlanResponse
from app.schemas.timeline import Timeline
from app.schemas.timeline_api import (
    TimelineCreateRequest,
    TimelineHistoryResponse,
    TimelineOpsRequest,
    TimelineRedoRequest,
    TimelineRestoreRequest,
    TimelineUndoRequest,
)
from app.services.job_service import JobService
from app.services.planner_service import EditPlannerService
from app.services.timeline_compiler import TimelineCompiler
from app.services.timeline_service import TimelineService
from app.tasks.plan_task import generate_plan_task
from app.tasks.timeline_render_task import render_timeline_task

router = APIRouter(prefix="/timelines", tags=["Timelines"])


@router.post(
    "",
    response_model=Timeline,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new timeline from a video",
)
def create_timeline(
    payload: TimelineCreateRequest,
    db: Session = Depends(get_db),
) -> Timeline:
    """Create a new timeline initialized for a source video.

    If source_duration_ms is not provided, extracts duration from the source video if available.
    """
    video = db.scalar(select(Video).where(Video.id == payload.video_id))
    if not video:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Video with id '{payload.video_id}' not found",
        )

    source_duration_ms = payload.source_duration_ms
    if source_duration_ms is None and video.duration is not None:
        source_duration_ms = int(video.duration * 1000)

    return TimelineService.create_timeline(
        db=db,
        video_id=payload.video_id,
        tracks=payload.tracks,
        source_duration_ms=source_duration_ms,
    )


@router.get(
    "/{id}",
    response_model=Timeline,
    status_code=status.HTTP_200_OK,
    summary="Get timeline by ID",
)
def get_timeline(
    id: str = Path(..., description="Timeline ID"),
    db: Session = Depends(get_db),
) -> Timeline:
    """Fetch the latest active state of a timeline by its ID."""
    return TimelineService.get_timeline(db, id)


@router.post(
    "/{id}/ops",
    response_model=Timeline,
    status_code=status.HTTP_200_OK,
    summary="Apply a batch of operations",
)
def apply_ops(
    payload: TimelineOpsRequest,
    id: str = Path(..., description="Timeline ID"),
    db: Session = Depends(get_db),
) -> Timeline:
    """Apply a batch of timeline operations sharing a single group_id.

    - Validates optimistic concurrency against expected_version (409 on mismatch).
    - Automatically purges redo stack if in an undone state.
    - Creates snapshots every N ops.
    """
    result = TimelineService.apply_ops(
        db=db,
        timeline_id=id,
        ops=payload.ops,
        expected_version=payload.expected_version,
        actor=payload.actor,
        group_id=payload.group_id,
    )
    try:
        from app.api.v1.endpoints.websocket import timeline_manager

        timeline_manager.broadcast_sync(
            timeline_id=id,
            message={
                "event": "OP_APPLIED",
                "timeline_id": id,
                "version": result.version,
                "actor": payload.actor,
            },
        )
    except Exception:
        pass
    return result


@router.post(
    "/{id}/undo",
    response_model=Timeline,
    status_code=status.HTTP_200_OK,
    summary="Undo the latest group of operations",
)
def undo(
    payload: TimelineUndoRequest,
    id: str = Path(..., description="Timeline ID"),
    db: Session = Depends(get_db),
) -> Timeline:
    """Undo the most recent group of operations in reverse order."""
    result = TimelineService.undo(
        db=db,
        timeline_id=id,
        expected_version=payload.expected_version,
    )
    try:
        from app.api.v1.endpoints.websocket import timeline_manager

        timeline_manager.broadcast_sync(
            timeline_id=id,
            message={
                "event": "OP_APPLIED",
                "timeline_id": id,
                "version": result.version,
                "actor": "user",
            },
        )
    except Exception:
        pass
    return result


@router.post(
    "/{id}/redo",
    response_model=Timeline,
    status_code=status.HTTP_200_OK,
    summary="Redo the next undone group of operations",
)
def redo(
    payload: TimelineRedoRequest,
    id: str = Path(..., description="Timeline ID"),
    db: Session = Depends(get_db),
) -> Timeline:
    """Redo the next undone group of operations in forward order."""
    result = TimelineService.redo(
        db=db,
        timeline_id=id,
        expected_version=payload.expected_version,
    )
    try:
        from app.api.v1.endpoints.websocket import timeline_manager

        timeline_manager.broadcast_sync(
            timeline_id=id,
            message={
                "event": "OP_APPLIED",
                "timeline_id": id,
                "version": result.version,
                "actor": "user",
            },
        )
    except Exception:
        pass
    return result


@router.get(
    "/{id}/history",
    response_model=TimelineHistoryResponse,
    status_code=status.HTTP_200_OK,
    summary="Get timeline operations history and snapshot versions",
)
def get_history(
    id: str = Path(..., description="Timeline ID"),
    db: Session = Depends(get_db),
) -> dict:
    """Retrieve full operation history and snapshot versions for a timeline."""
    return TimelineService.get_history(db, id)


@router.post(
    "/{id}/restore/{version}",
    response_model=Timeline,
    status_code=status.HTTP_200_OK,
    summary="Restore a pinned timeline snapshot version",
)
def restore_version(
    payload: TimelineRestoreRequest,
    id: str = Path(..., description="Timeline ID"),
    version: int = Path(..., ge=1, description="Snapshot version number to restore"),
    db: Session = Depends(get_db),
) -> Timeline:
    """Restore a pinned snapshot version from timeline_versions."""
    result = TimelineService.restore_version(
        db=db,
        timeline_id=id,
        target_version=version,
        expected_version=payload.expected_version,
    )
    try:
        from app.api.v1.endpoints.websocket import timeline_manager

        timeline_manager.broadcast_sync(
            timeline_id=id,
            message={
                "event": "OP_APPLIED",
                "timeline_id": id,
                "version": result.version,
                "actor": "user",
            },
        )
    except Exception:
        pass
    return result


@router.post(
    "/{id}/render",
    response_model=JobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Enqueue timeline render job",
)
def render_timeline(
    id: str = Path(..., description="Timeline ID"),
    version: int | None = Query(default=None, ge=1, description="Optional pinned version"),
    db: Session = Depends(get_db),
) -> JobResponse:
    """Dispatch background rendering task for a timeline (pinned version or latest)."""
    model = TimelineService.get_timeline_model(db, id)

    active_renders = (
        db.scalar(
            select(func.count(Job.id)).where(
                Job.job_type == "TIMELINE_RENDER",
                Job.status.in_(["PENDING", "PROCESSING"]),
            )
        )
        or 0
    )
    if active_renders >= settings.RENDER_CONCURRENCY_LIMIT:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Maximum concurrent renders reached ({active_renders}/"
                f"{settings.RENDER_CONCURRENCY_LIMIT}). Please wait for current renders to finish."
            ),
        )

    job = JobService.create_job(
        db=db,
        job_type="TIMELINE_RENDER",
        video_id=model.video_id,
        initial_progress=0,
    )

    render_timeline_task.delay(
        job_id=job.id,
        timeline_id=id,
        version=version,
    )
    return JobResponse.model_validate(job)


@router.post(
    "/{id}/cancel",
    summary="Cancel active timeline render job",
)
def cancel_timeline_render(
    id: str = Path(..., description="Timeline ID"),
    job_id: str | None = Query(default=None, description="Optional specific job ID"),
    db: Session = Depends(get_db),
) -> dict[str, str | bool]:
    """Cancel an active rendering job for a timeline."""
    stmt = select(Job).where(
        Job.job_type == "TIMELINE_RENDER",
        Job.status.in_(["PENDING", "PROCESSING"]),
    )
    if job_id:
        stmt = stmt.where(Job.id == job_id)

    active_job = db.scalar(stmt.order_by(Job.created_at.desc()))
    if not active_job:
        return {"ok": True, "message": "No active render job found to cancel"}

    JobService.cancel_job(active_job.id)
    return {
        "ok": True,
        "message": f"Render job '{active_job.id}' cancelled successfully",
        "job_id": active_job.id,
    }


@router.get(
    "/{id}/download",
    summary="Download rendered timeline video file",
)
def download_timeline(
    id: str = Path(..., description="Timeline ID"),
    version: int | None = Query(default=None, ge=1, description="Optional pinned version"),
    db: Session = Depends(get_db),
) -> FileResponse:
    """Download the completed MP4 video file for a rendered timeline."""
    model = TimelineService.get_timeline_model(db, id)
    target_v = version or model.version
    out_file = FilePath(settings.OUTPUT_DIR) / f"timeline_{id}_v{target_v}.mp4"

    if not out_file.is_file():
        # Check if any version output exists
        candidates = sorted(FilePath(settings.OUTPUT_DIR).glob(f"timeline_{id}_v*.mp4"))
        if candidates:
            out_file = candidates[-1]
        else:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Rendered video file for timeline '{id}' (v{target_v}) not found",
            )

    return FileResponse(
        path=str(out_file),
        media_type="video/mp4",
        filename=f"timeline_{id}_v{target_v}.mp4",
    )


@router.get(
    "/{id}/frame",
    summary="Render preview frame from timeline at time t",
)
def get_timeline_frame(
    id: str = Path(..., description="Timeline ID"),
    t: float = Query(default=0.0, ge=0.0, description="Offset in seconds from timeline start"),
    time: float | None = Query(default=None, ge=0.0, description="Alias for t"),
    version: int | None = Query(default=None, ge=1, description="Optional pinned version"),
    db: Session = Depends(get_db),
) -> Response:
    """Render a single JPEG preview frame evaluated from the timeline filters and tracks."""
    target_time = time if time is not None else t

    # 1. Resolve timeline
    model = TimelineService.get_timeline_model(db, id)
    if version is not None and version != model.version:
        from app.models.timeline import TimelineVersionModel

        v_record = db.scalar(
            select(TimelineVersionModel).where(
                TimelineVersionModel.timeline_id == id,
                TimelineVersionModel.version == version,
            )
        )
        if not v_record:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Version {version} snapshot not found for timeline '{id}'",
            )
        timeline = Timeline.model_validate(v_record.snapshot)
    else:
        timeline = model.to_schema()

    def source_resolver(ref: str) -> FilePath:
        vid = db.scalar(select(Video).where(Video.id == ref))
        if vid and vid.file_path and FilePath(vid.file_path).is_file():
            return FilePath(vid.file_path)
        p = FilePath(ref)
        if p.is_file():
            return p
        up = FilePath(settings.UPLOAD_DIR) / f"{ref}.mp4"
        if up.is_file():
            return up
        up_orig = FilePath(settings.UPLOAD_DIR) / ref
        if up_orig.is_file():
            return up_orig
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Source media not found on disk for '{ref}'",
        )

    out_dummy = FilePath(settings.OUTPUT_DIR) / f"frame_{id}.jpg"
    compiler = TimelineCompiler(
        timeline=timeline,
        source_resolver=source_resolver,
        output_path=out_dummy,
    )

    frame_bytes = compiler.extract_frame(timestamp=target_time)
    return Response(content=frame_bytes, media_type="image/jpeg")


@router.post(
    "/{id}/plan",
    response_model=PlanResponse,
    status_code=status.HTTP_200_OK,
    summary="Generate an AI edit plan for the timeline",
)
def create_edit_plan(
    payload: PlanRequest,
    id: str = Path(..., description="Timeline ID"),
    db: Session = Depends(get_db),
) -> PlanResponse:
    """Generate an AI editing plan for a timeline from a natural language prompt (Milestone P3).

    - If dry_run is False (default), creates an asynchronous background Job and returns plan.
    - If dry_run is True, validates and returns the plan immediately without queueing
      a background task.
    """
    model = TimelineService.get_timeline_model(db, id)

    if payload.dry_run:
        rationale, validated_ops = EditPlannerService.generate_plan(
            db=db,
            timeline_id=id,
            prompt=payload.prompt,
        )
        plan = EditPlannerService.create_plan_record(
            db=db,
            timeline_id=id,
            prompt=payload.prompt,
        )
        plan.rationale = rationale
        plan.ops = validated_ops
        plan.status = "VALIDATED"
        db.commit()
        db.refresh(plan)
        return PlanResponse.model_validate(plan)

    job = JobService.create_job(
        db=db,
        job_type="TIMELINE_PLAN",
        video_id=model.video_id,
        initial_progress=0,
    )
    plan = EditPlannerService.create_plan_record(
        db=db,
        timeline_id=id,
        prompt=payload.prompt,
        job_id=job.id,
    )

    generate_plan_task.delay(plan_id=plan.id, job_id=job.id)
    # Refresh plan to get accurate status
    db.refresh(plan)
    return PlanResponse.model_validate(plan)


@router.get(
    "/{id}/plan/{plan_id}",
    response_model=PlanResponse,
    summary="Get AI edit plan status and operations",
)
def get_edit_plan(
    id: str = Path(..., description="Timeline ID"),
    plan_id: str = Path(..., description="Edit Plan ID"),
    db: Session = Depends(get_db),
) -> PlanResponse:
    """Retrieve an edit plan by its ID."""
    plan = EditPlannerService.get_plan(db, plan_id)
    if plan.timeline_id != id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Plan '{plan_id}' does not belong to timeline '{id}'",
        )
    return PlanResponse.model_validate(plan)


@router.post(
    "/{id}/plan/{plan_id}/apply",
    response_model=Timeline,
    status_code=status.HTTP_200_OK,
    summary="Apply an AI edit plan onto the timeline",
)
def apply_edit_plan(
    payload: ApplyPlanRequest,
    id: str = Path(..., description="Timeline ID"),
    plan_id: str = Path(..., description="Edit Plan ID"),
    db: Session = Depends(get_db),
) -> Timeline:
    """Apply all plan operations as a single undo group with actor='agent' (Milestone P5).

    One undo reverts the entire agent plan.
    """
    return EditPlannerService.apply_plan(
        db=db,
        timeline_id=id,
        plan_id=plan_id,
        expected_version=payload.expected_version,
    )
