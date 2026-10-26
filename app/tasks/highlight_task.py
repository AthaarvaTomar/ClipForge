from typing import Any

from celery import Task
from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.clip import Clip
from app.models.transcript import Transcript
from app.models.video import Video
from app.services.highlight_service import HighlightService
from app.services.job_service import JobService
from app.tasks.celery_app import celery_app


@celery_app.task(bind=True, name="app.tasks.detect_highlights_task")
def detect_highlights_task(
    self: Task,
    job_id: str,
    video_id: str,
) -> dict[str, Any]:
    """Celery task to detect highlight moments from transcript and create draft clips."""
    JobService.update_progress(job_id=job_id, progress=10, status="PROCESSING")
    if getattr(self.request, "id", None):
        try:
            self.update_state(state="PROCESSING", meta={"progress": 10})
        except Exception:
            pass

    db = SessionLocal()
    try:
        # 1. Fetch video
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

        # 2. Fetch transcript
        transcript = db.scalar(select(Transcript).where(Transcript.video_id == video_id))
        if not transcript or not transcript.text.strip():
            error_msg = f"Transcript not found or empty for video '{video_id}'"
            JobService.update_progress(
                job_id=job_id,
                progress=100,
                status="FAILED",
                error_message=error_msg,
            )
            return {"error": error_msg}

        # 3. Detect highlights via LLM (Gemini with Ollama fallback)
        JobService.update_progress(job_id=job_id, progress=40, status="PROCESSING")
        moments = HighlightService.detect_highlights(
            text=transcript.text,
            words=transcript.words if transcript.words else None,
            duration=video.duration,
        )

        # 4. Save draft clips
        JobService.update_progress(job_id=job_id, progress=80, status="PROCESSING")
        created_clips: list[Clip] = []
        for moment in moments:
            clip = Clip(
                video_id=video_id,
                title=moment.title,
                start_time=moment.start_time,
                end_time=moment.end_time,
                edit_spec={
                    "hook": moment.hook,
                    "reason": moment.reason,
                    "score": moment.score,
                    "cuts": [{"start": moment.start_time, "end": moment.end_time}],
                },
                status="DRAFT",
            )
            db.add(clip)
            created_clips.append(clip)

        db.commit()
        for clip in created_clips:
            db.refresh(clip)

        # 5. Mark job completed
        result_payload = {
            "video_id": video_id,
            "clips_count": len(created_clips),
            "clips": [
                {
                    "id": c.id,
                    "title": c.title,
                    "start_time": c.start_time,
                    "end_time": c.end_time,
                    "status": c.status,
                    "score": c.edit_spec.get("score"),
                }
                for c in created_clips
            ],
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
        JobService.update_progress(
            job_id=job_id,
            progress=100,
            status="FAILED",
            error_message=str(e),
        )
        raise
    finally:
        db.close()
