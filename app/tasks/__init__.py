from app.tasks.celery_app import celery_app
from app.tasks.dummy_task import run_dummy_task
from app.tasks.highlight_task import detect_highlights_task
from app.tasks.render_task import render_clip_task
from app.tasks.transcription_task import transcribe_video_task

__all__ = [
    "celery_app",
    "detect_highlights_task",
    "render_clip_task",
    "run_dummy_task",
    "transcribe_video_task",
]
