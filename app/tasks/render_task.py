"""Celery background task for video clip rendering (Task A11)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from celery import Task
from sqlalchemy import select

from app.config import settings
from app.core.database import SessionLocal
from app.models.clip import Clip
from app.models.transcript import Transcript
from app.models.video import Video
from app.schemas.edit_spec import EditSpec
from app.services.ass_builder import ASSBuilder
from app.services.ffmpeg_builder import (
    FFmpegBuilder,
    FFmpegBuilderError,
    get_target_resolution,
)
from app.services.job_service import JobService
from app.tasks.celery_app import celery_app


@celery_app.task(bind=True, name="app.tasks.render_clip_task")
def render_clip_task(
    self: Task,
    job_id: str,
    clip_id: str,
) -> dict[str, Any]:
    """Render a video clip using FFmpeg according to its EditSpec and burned-in captions."""
    JobService.update_progress(job_id=job_id, progress=5, status="PROCESSING")
    if getattr(self.request, "id", None):
        try:
            self.update_state(state="PROCESSING", meta={"progress": 5})
        except Exception:
            pass

    db = SessionLocal()
    tmp_ass: Path | None = None
    output_path: Path | None = None

    try:
        clip = db.scalar(select(Clip).where(Clip.id == clip_id))
        if not clip:
            error_msg = f"Clip with id '{clip_id}' not found"
            JobService.update_progress(
                job_id=job_id,
                progress=100,
                status="FAILED",
                error_message=error_msg,
            )
            return {"error": error_msg}

        clip.status = "RENDERING"
        db.commit()

        video = db.scalar(select(Video).where(Video.id == clip.video_id))
        if not video:
            error_msg = f"Source video with id '{clip.video_id}' not found"
            clip.status = "FAILED"
            db.commit()
            JobService.update_progress(
                job_id=job_id,
                progress=100,
                status="FAILED",
                error_message=error_msg,
            )
            return {"error": error_msg}

        input_video_path = Path(video.file_path)
        if not input_video_path.is_file():
            error_msg = f"Source video file not found on disk: {video.file_path}"
            clip.status = "FAILED"
            db.commit()
            JobService.update_progress(
                job_id=job_id,
                progress=100,
                status="FAILED",
                error_message=error_msg,
            )
            return {"error": error_msg}

        # Parse EditSpec
        edit_spec = EditSpec.model_validate(clip.edit_spec)

        # Output resolution and destination
        source_w = video.width or 1920
        source_h = video.height or 1080
        target_w, target_h = get_target_resolution(edit_spec.aspect_ratio, source_w, source_h)

        output_dir = Path(settings.OUTPUT_DIR)
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{clip.id}.mp4"

        # Generate subtitles if captions are enabled
        subtitle_path: Path | None = None
        if edit_spec.captions.enabled:
            transcript = db.scalar(
                select(Transcript).where(Transcript.video_id == clip.video_id)
            )
            if transcript and transcript.words:
                ass_builder = ASSBuilder(
                    caption_spec=edit_spec.captions,
                    target_width=target_w,
                    target_height=target_h,
                )
                tmp_ass = output_dir / f"{clip.id}_subs.ass"
                ass_builder.write_ass_file(
                    output_file=tmp_ass,
                    words=transcript.words,
                    cuts=edit_spec.cuts,
                    transition=edit_spec.transition,
                    title=clip.title or edit_spec.hook,
                )
                subtitle_path = tmp_ass

        # Initialize FFmpeg builder
        builder = FFmpegBuilder(
            input_path=input_video_path,
            output_path=output_path,
            edit_spec=edit_spec,
            source_width=source_w,
            source_height=source_h,
            subtitle_path=subtitle_path,
        )

        def on_render_progress(pct: float) -> None:
            # Map ffmpeg 0-100% to job 10-95%
            job_pct = 10 + int(pct * 0.85)
            JobService.update_progress(job_id=job_id, progress=job_pct, status="PROCESSING")
            if getattr(self.request, "id", None):
                try:
                    self.update_state(state="PROCESSING", meta={"progress": job_pct})
                except Exception:
                    pass

        # Execute render with real-time progress and timeout
        rendered_file = builder.run(
            timeout=settings.FFMPEG_TIMEOUT_SECONDS,
            on_progress=on_render_progress,
        )


        # Update clip and job state
        clip.output_path = str(rendered_file.resolve())
        clip.status = "COMPLETED"
        db.commit()

        result_data = {
            "clip_id": clip.id,
            "output_path": clip.output_path,
        }
        JobService.update_progress(
            job_id=job_id,
            progress=100,
            status="COMPLETED",
            result_data=result_data,
        )

        return result_data

    except Exception as e:
        if output_path and output_path.exists():
            output_path.unlink(missing_ok=True)

        clip_record = db.scalar(select(Clip).where(Clip.id == clip_id))
        if clip_record:
            clip_record.status = "FAILED"
            db.commit()

        err_detail = str(e)
        JobService.update_progress(
            job_id=job_id,
            progress=100,
            status="FAILED",
            error_message=err_detail,
        )
        raise FFmpegBuilderError(f"Render task failed: {err_detail}") from e

    finally:
        # Cleanup temporary subtitle file
        if tmp_ass and tmp_ass.exists():
            tmp_ass.unlink(missing_ok=True)
        db.close()
