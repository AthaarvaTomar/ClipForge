from typing import Any

from celery import Task
from sqlalchemy import select

from app.core.database import SessionLocal
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

        # 1. Extract 16kHz mono WAV audio
        JobService.update_progress(job_id=job_id, progress=30, status="PROCESSING")
        wav_path = extract_audio(video.file_path)

        # 2. Run faster-whisper transcription
        JobService.update_progress(job_id=job_id, progress=60, status="PROCESSING")
        result = transcribe_audio(wav_path)

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
