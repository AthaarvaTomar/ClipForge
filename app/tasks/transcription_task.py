import time
from datetime import UTC, datetime
from typing import Any

from celery import Task
from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.logging import logger
from app.models.transcript import Transcript
from app.models.video import Video
from app.services.audio_extractor import extract_audio
from app.services.job_service import JobService
from app.services.transcription_service import transcribe_audio
from app.tasks.celery_app import celery_app


@celery_app.task(bind=True, name="app.tasks.transcribe_video_task")
def transcribe_video_task(
    self: Task,
    job_id: str,
    video_id: str,
) -> dict[str, Any]:
    """Celery task to extract audio from video and perform word-level transcription."""
    JobService.update_progress(job_id=job_id, progress=10, status="PROCESSING")
    if getattr(self.request, "id", None):
        try:
            self.update_state(state="PROCESSING", meta={"progress": 10})
        except Exception:
            pass

    db = SessionLocal()
    try:
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

        # Update video status to transcribing
        video.status = "transcribing"
        video.progress = 0
        video.transcribe_started_at = datetime.now(UTC)
        db.commit()

        # 1. Extract 16kHz mono WAV audio
        JobService.update_progress(job_id=job_id, progress=10, status="PROCESSING", db=db)
        wav_path = extract_audio(video.file_path)

        # Get audio duration (from video metadata or fallback probe)
        duration = video.duration
        if duration is None or duration <= 0:
            try:
                from app.services.video_probe import probe_video

                meta = probe_video(video.file_path)
                duration = meta.duration
                video.duration = duration
                db.commit()
            except Exception:
                duration = None

        # 2. Run faster-whisper transcription with throttled progress updates
        JobService.update_progress(job_id=job_id, progress=10, status="PROCESSING", db=db)

        last_saved_progress = 0
        last_save_time = 0.0

        def on_segment_progress(percent: int) -> None:
            nonlocal last_saved_progress, last_save_time
            percent = min(99, max(0, percent))
            now = time.monotonic()
            if percent != last_saved_progress:
                if (now - last_save_time >= 2.0) or (last_saved_progress == 0):
                    try:
                        v = db.scalar(select(Video).where(Video.id == video_id))
                        if v:
                            v.progress = percent
                            db.commit()
                            last_saved_progress = percent
                            last_save_time = now
                        JobService.update_progress(
                            job_id=job_id,
                            progress=percent,
                            status="PROCESSING",
                            db=db,
                        )
                        if getattr(self.request, "id", None):
                            self.update_state(state="PROCESSING", meta={"progress": percent})
                    except Exception as err:
                        logger.warning("Failed to save progress update %s%%: %s", percent, err)

        result = transcribe_audio(
            wav_path,
            duration=duration,
            on_progress=on_segment_progress,
        )

        # 3. Store transcript in database
        existing_transcript = db.scalar(select(Transcript).where(Transcript.video_id == video_id))
        if existing_transcript:
            existing_transcript.language = result.language
            existing_transcript.text = result.text
            existing_transcript.words = result.words
            transcript_record = existing_transcript
        else:
            transcript_record = Transcript(
                video_id=video_id,
                language=result.language,
                text=result.text,
                words=result.words,
            )
            db.add(transcript_record)

        video.progress = 100
        video.status = "transcribed"
        db.commit()
        db.refresh(transcript_record)

        # 4. Mark job completed
        result_payload = {
            "transcript_id": transcript_record.id,
            "word_count": len(result.words),
            "language": result.language,
        }
        JobService.update_progress(
            job_id=job_id,
            progress=100,
            status="COMPLETED",
            result_data=result_payload,
            db=db,
        )
        if getattr(self.request, "id", None):
            try:
                self.update_state(state="COMPLETED", meta={"progress": 100})
            except Exception:
                pass

        return result_payload

    except Exception as e:
        logger.exception("Transcription worker failed for video '%s': %s", video_id, e)
        try:
            v_fail = db.scalar(select(Video).where(Video.id == video_id))
            if v_fail:
                v_fail.status = "failed"
                db.commit()
        except Exception:
            pass
        JobService.update_progress(
            job_id=job_id,
            progress=100,
            status="FAILED",
            error_message=str(e),
        )
        raise
    finally:
        db.close()
