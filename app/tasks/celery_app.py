from celery import Celery

from app.config import settings

celery_app = Celery(
    "clipforge",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=[
        "app.tasks.dummy_task",
        "app.tasks.transcription_task",
        "app.tasks.highlight_task",
        "app.tasks.render_task",
        "app.tasks.asset_task",
        "app.tasks.timeline_render_task",
        "app.tasks.index_task",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_always_eager=settings.CELERY_TASK_ALWAYS_EAGER,
)
