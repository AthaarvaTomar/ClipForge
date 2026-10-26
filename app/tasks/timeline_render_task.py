"""Celery background task for multi-track timeline rendering (Task R3)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from celery import Task
from sqlalchemy import select

from app.config import settings
from app.core.database import SessionLocal
from app.models.timeline import TimelineModel, TimelineVersionModel
from app.models.video import Video
from app.schemas.timeline import Timeline
from app.services.ffmpeg_builder import FFmpegBuilderError
from app.services.job_service import JobService
from app.services.timeline_compiler import TimelineCompiler
from app.tasks.celery_app import celery_app


@celery_app.task(bind=True, name="app.tasks.render_timeline_task")
def render_timeline_task(
    self: Task,
    job_id: str,
    timeline_id: str,
    version: int | None = None,
) -> dict[str, Any]:
    """Render a pinned or active timeline version using TimelineCompiler."""
    JobService.update_progress(job_id=job_id, progress=5, status="PROCESSING")
    if getattr(self.request, "id", None):
        try:
            self.update_state(state="PROCESSING", meta={"progress": 5})
        except Exception:
            pass

    db = SessionLocal()
    output_path: Path | None = None

    try:
        # 1. Fetch Timeline model
        tl_model = db.scalar(select(TimelineModel).where(TimelineModel.id == timeline_id))
        if not tl_model:
            error_msg = f"Timeline with id '{timeline_id}' not found"
            JobService.update_progress(
                job_id=job_id, progress=100, status="FAILED", error_message=error_msg
            )
            return {"error": error_msg}

        # 2. Resolve target version schema
        if version is not None and version != tl_model.version:
            v_record = db.scalar(
                select(TimelineVersionModel).where(
                    TimelineVersionModel.timeline_id == timeline_id,
                    TimelineVersionModel.version == version,
                )
            )
            if not v_record:
                error_msg = f"Version {version} snapshot not found for timeline '{timeline_id}'"
                JobService.update_progress(
                    job_id=job_id, progress=100, status="FAILED", error_message=error_msg
                )
                return {"error": error_msg}
            timeline = Timeline.model_validate(v_record.snapshot)
        else:
            timeline = tl_model.to_schema()

        # 3. Source file resolver
        def source_resolver(ref: str) -> Path:
            # Check DB for video ID
            vid = db.scalar(select(Video).where(Video.id == ref))
            if vid and vid.file_path and Path(vid.file_path).is_file():
                return Path(vid.file_path)

            # Check direct path
            p = Path(ref)
            if p.is_file():
                return p

            # Check uploads directory
            up = Path(settings.UPLOAD_DIR) / f"{ref}.mp4"
            if up.is_file():
                return up
            up_orig = Path(settings.UPLOAD_DIR) / ref
            if up_orig.is_file():
                return up_orig

            raise FFmpegBuilderError(f"Cannot resolve media source file for reference: '{ref}'")

        # 4. Destination path
        out_dir = Path(settings.OUTPUT_DIR)
        out_dir.mkdir(parents=True, exist_ok=True)
        target_version = version or timeline.version
        output_path = out_dir / f"timeline_{timeline.id}_v{target_version}.mp4"

        # 5. Build TimelineCompiler
        compiler = TimelineCompiler(
            timeline=timeline,
            source_resolver=source_resolver,
            output_path=output_path,
        )

        def on_render_progress(pct: float) -> None:
            # Map 0..100% to 10..95%
            job_pct = 10 + int(pct * 0.85)
            JobService.update_progress(job_id=job_id, progress=job_pct, status="PROCESSING")
            if getattr(self.request, "id", None):
                try:
                    self.update_state(state="PROCESSING", meta={"progress": job_pct})
                except Exception:
                    pass

        def cancel_check() -> bool:
            return JobService.is_job_cancelled(job_id)

        # 6. Execute render
        rendered_file = compiler.run(
            timeout=settings.FFMPEG_TIMEOUT_SECONDS,
            on_progress=on_render_progress,
            cancel_check=cancel_check,
        )

        result_payload = {
            "timeline_id": timeline.id,
            "version": target_version,
            "output_path": str(rendered_file.resolve()),
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
        if output_path and output_path.exists():
            output_path.unlink(missing_ok=True)

        is_cancel = "cancelled" in str(e).lower()
        status_str = "CANCELLED" if is_cancel else "FAILED"

        JobService.update_progress(
            job_id=job_id,
            progress=100,
            status=status_str,
            error_message=str(e),
        )
        raise
    finally:
        db.close()
