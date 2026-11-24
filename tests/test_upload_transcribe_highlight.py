"""End-to-end integration test for video upload -> automatic transcription -> highlight detection.

Verifies:
1. Video upload automatically triggers background transcription.
2. Video status transitions properly to 'transcribed'.
3. Highlight detection is guarded by HTTP 409 when transcription is incomplete.
4. Highlight detection runs on the transcribed video and yields valid draft clip segments.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Generator
from pathlib import Path
from unittest.mock import patch

import pytest
import static_ffmpeg
from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.main import app
from app.models.video import Video
from app.services.transcription_service import TranscriptionResult
from app.tasks.celery_app import celery_app

static_ffmpeg.add_paths()


@pytest.fixture(autouse=True)
def configure_celery_eager() -> Generator[None, None, None]:
    original_broker = celery_app.conf.broker_url
    original_eager = celery_app.conf.task_always_eager
    original_backend = celery_app.conf.result_backend
    celery_app.conf.broker_url = "memory://"
    celery_app.conf.task_always_eager = True
    celery_app.conf.result_backend = "cache+memory://"
    yield
    celery_app.conf.broker_url = original_broker
    celery_app.conf.task_always_eager = original_eager
    celery_app.conf.result_backend = original_backend


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(scope="session")
def short_sample_video(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Generate a 2.0s test MP4 video with a test audio tone."""
    tmp_dir = tmp_path_factory.mktemp("upload_test_video")
    file_path = tmp_dir / "short_sample.mp4"
    ffmpeg = shutil.which("ffmpeg")
    assert ffmpeg, "ffmpeg executable must be available"

    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=darkblue:s=640x360:d=2.0",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=2.0",
            "-t",
            "2.0",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            str(file_path),
        ],
        check=True,
        capture_output=True,
    )
    return file_path


MOCK_TRANSCRIPTION = TranscriptionResult(
    language="en",
    text="Welcome to ClipForge AI. Discover the secret to viral short videos.",
    words=[
        {"word": "Welcome", "start": 0.0, "end": 0.4, "probability": 0.99},
        {"word": "to", "start": 0.45, "end": 0.6, "probability": 0.99},
        {"word": "ClipForge", "start": 0.65, "end": 1.0, "probability": 0.98},
        {"word": "AI.", "start": 1.05, "end": 1.25, "probability": 0.97},
        {"word": "Discover", "start": 1.3, "end": 1.6, "probability": 0.99},
        {"word": "the", "start": 1.65, "end": 1.75, "probability": 0.99},
        {"word": "secret.", "start": 1.8, "end": 2.0, "probability": 0.98},
    ],
)


def test_upload_transcribe_and_highlight_detection_flow(
    client: TestClient,
    short_sample_video: Path,
) -> None:
   
    db = SessionLocal()
    untranscribed = Video(
        filename="untranscribed_guard.mp4",
        file_path=str(short_sample_video),
        duration=2.0,
        status="uploaded",
    )
    db.add(untranscribed)
    db.commit()
    db.refresh(untranscribed)

    guard_resp = client.post(f"/api/highlights/{untranscribed.id}")
    assert guard_resp.status_code == 409
    assert guard_resp.json()["detail"] == "Transcription not complete yet"

    db.delete(untranscribed)
    db.commit()
    db.close()

   
    with patch(
        "app.tasks.transcription_task.transcribe_audio",
        return_value=MOCK_TRANSCRIPTION,
    ):
        with open(short_sample_video, "rb") as f:
            upload_resp = client.post(
                "/api/videos",
                files={"file": ("short_sample.mp4", f, "video/mp4")},
            )

    assert upload_resp.status_code == 201
    upload_data = upload_resp.json()
    video_id = upload_data["id"]
    assert video_id is not None
    assert upload_data["filename"] == "short_sample.mp4"

    tx_resp = client.get(f"/api/transcripts/{video_id}")
    assert tx_resp.status_code == 200
    tx_data = tx_resp.json()
    assert tx_data["video_id"] == video_id
    assert tx_data["text"] == MOCK_TRANSCRIPTION.text
    assert len(tx_data["words"]) == len(MOCK_TRANSCRIPTION.words)

   
    v_resp = client.get(f"/api/videos/{video_id}")
    assert v_resp.status_code == 200
    assert v_resp.json()["status"] == "transcribed"

  
    hl_job_resp = client.post(f"/api/highlights/{video_id}")
    assert hl_job_resp.status_code == 202
    job_info = hl_job_resp.json()
    assert job_info["id"] is not None
    assert job_info["job_type"] == "highlights"

    clips_resp = client.get(f"/api/highlights/{video_id}")
    assert clips_resp.status_code == 200
    clips_data = clips_resp.json()
    assert clips_data["video_id"] == video_id
    assert clips_data["total"] >= 1
    assert len(clips_data["clips"]) >= 1

    for clip in clips_data["clips"]:
        assert clip["status"] == "DRAFT"
        assert clip["start_time"] < clip["end_time"]
        assert clip["title"]
        assert "cuts" in clip["edit_spec"]
        assert len(clip["edit_spec"]["cuts"]) > 0


    del_res = client.delete(f"/api/videos/{video_id}")
    assert del_res.status_code == 200
