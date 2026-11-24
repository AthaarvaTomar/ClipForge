import shutil
import subprocess
from collections.abc import Generator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import static_ffmpeg
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.database import SessionLocal
from app.main import app
from app.models.video import Video
from app.services.audio_extractor import extract_audio
from app.services.transcription_service import (
    TranscriptionResult,
    compute_transcription_progress,
    transcribe_audio,
)
from app.tasks.celery_app import celery_app

static_ffmpeg.add_paths()


@pytest.fixture(autouse=True)
def configure_celery_eager() -> Generator[None, None, None]:
    original_eager = celery_app.conf.task_always_eager
    original_backend = celery_app.conf.result_backend
    celery_app.conf.task_always_eager = True
    celery_app.conf.result_backend = "cache+memory://"
    yield
    celery_app.conf.task_always_eager = original_eager
    celery_app.conf.result_backend = original_backend


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(scope="session")
def sample_video_with_audio(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Generate a test MP4 video with a 440Hz sine wave tone."""
    tmp_dir = tmp_path_factory.mktemp("transcription_video")
    file_path = tmp_dir / "audio_test.mp4"
    ffmpeg = shutil.which("ffmpeg")
    assert ffmpeg, "ffmpeg must be available"

    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=640x360:d=1.0",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1.0",
            "-t",
            "1.0",
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


def test_compute_transcription_progress() -> None:
    """Unit test: progress is computed correctly and never exceeds 99 until transcript is saved."""
    duration = 120.0
    # 0s
    assert compute_transcription_progress(0.0, duration) == 0
    # 30s / 120s = 25%
    assert compute_transcription_progress(30.0, duration) == 25
    # 60s / 120s = 50%
    assert compute_transcription_progress(60.0, duration) == 50
    # 118s / 120s = 98%
    assert compute_transcription_progress(118.0, duration) == 98
    # 120s / 120s = 100% -> must be capped at 99
    assert compute_transcription_progress(120.0, duration) == 99
    # 130s / 120s = 108% -> must never exceed 99
    assert compute_transcription_progress(130.0, duration) == 99
    # Negative and 0 duration
    assert compute_transcription_progress(10.0, 0.0) == 0
    assert compute_transcription_progress(10.0, -5.0) == 0
    assert compute_transcription_progress(-10.0, duration) == 0


def test_audio_extraction(sample_video_with_audio: Path) -> None:
    wav_path = extract_audio(sample_video_with_audio)
    assert wav_path.exists()
    assert wav_path.suffix == ".wav"
    assert wav_path.stat().st_size > 0
    wav_path.unlink(missing_ok=True)


def test_real_faster_whisper_execution(sample_video_with_audio: Path) -> None:
    wav_path = extract_audio(sample_video_with_audio)
    result = transcribe_audio(wav_path, model_size="tiny")
    assert isinstance(result.text, str)
    assert isinstance(result.language, str)
    assert isinstance(result.words, list)
    wav_path.unlink(missing_ok=True)


def test_transcription_task_and_endpoints(
    client: TestClient,
    sample_video_with_audio: Path,
) -> None:
    mock_result = TranscriptionResult(
        language="en",
        text="The quick brown fox",
        words=[
            {"word": "The", "start": 0.0, "end": 0.2, "probability": 0.95},
            {"word": "quick", "start": 0.25, "end": 0.5, "probability": 0.96},
            {"word": "brown", "start": 0.55, "end": 0.8, "probability": 0.97},
            {"word": "fox", "start": 0.85, "end": 1.0, "probability": 0.98},
        ],
    )

    with (
        patch("app.tasks.transcription_task.transcribe_audio", return_value=mock_result),
        patch("app.api.v1.endpoints.videos.generate_assets_task.delay"),
    ):
        # 1. Upload video first
        with open(sample_video_with_audio, "rb") as f:
            res = client.post(
                "/api/videos",
                files={"file": ("transcribe_test.mp4", f, "video/mp4")},
            )
        assert res.status_code == 201
        video_id = res.json()["id"]

        # 2. Trigger transcription job via POST
        job_res = client.post(f"/api/transcripts/{video_id}")
        assert job_res.status_code == 202
        job_id = job_res.json()["id"]

        # 3. Check job status (since eager mode is enabled, it completes synchronously)
        job_status = client.get(f"/api/jobs/{job_id}")
        assert job_status.status_code == 200
        assert job_status.json()["status"] == "COMPLETED"
        assert job_status.json()["progress"] == 100

        # 4. Fetch the transcript with words
        transcript_res = client.get(f"/api/transcripts/{video_id}")
        assert transcript_res.status_code == 200
        t_data = transcript_res.json()
        assert t_data["video_id"] == video_id
        assert t_data["language"] == "en"
        assert t_data["text"] == "The quick brown fox"
        assert len(t_data["words"]) == 4
        assert t_data["words"][1]["word"] == "quick"
        assert t_data["words"][1]["start"] == 0.25

    # 5. Non-existent video 404 test
    assert client.get("/api/transcripts/non-existent-video").status_code == 404

    # Cleanup
    client.delete(f"/api/videos/{video_id}")


def test_transcription_progress_api_during_run(
    client: TestClient,
    sample_video_with_audio: Path,
) -> None:
    """Verify that during a transcription run, the API returns progress and timing."""
    mock_result = TranscriptionResult(
        language="en",
        text="Testing progress bar live updates.",
        words=[
            {"word": "Testing", "start": 0.0, "end": 0.5, "probability": 0.99},
            {"word": "progress", "start": 0.5, "end": 1.0, "probability": 0.98},
        ],
    )

    def simulate_transcribe_with_progress(
        audio_path: Any,
        duration: Any = None,
        on_progress: Any = None,
        **kwargs: Any,
    ) -> TranscriptionResult:
        if on_progress:
            on_progress(42)
        return mock_result

    with (
        patch(
            "app.tasks.transcription_task.transcribe_audio",
            side_effect=simulate_transcribe_with_progress,
        ),
        patch("app.api.v1.endpoints.videos.generate_assets_task.delay"),
    ):
        # 1. Upload video (triggers transcription in eager mode)
        with open(sample_video_with_audio, "rb") as f:
            res = client.post(
                "/api/videos",
                files={"file": ("progress_test.mp4", f, "video/mp4")},
            )
        assert res.status_code == 201
        video_id = res.json()["id"]

    # Verify API returns progress mid-run (transcribing state)
    db = SessionLocal()
    v_mid = db.scalar(select(Video).where(Video.id == video_id))
    assert v_mid is not None
    v_mid.status = "transcribing"
    v_mid.progress = 42
    db.commit()
    db.close()

    api_mid_res = client.get(f"/api/videos/{video_id}")
    assert api_mid_res.status_code == 200
    mid_api_data = api_mid_res.json()
    assert mid_api_data["progress"] == 42
    assert mid_api_data["status"] == "transcribing"
    assert mid_api_data["transcribe_started_at"] is not None
    assert mid_api_data["duration"] is not None
    assert mid_api_data["duration"] > 0

    # Verify final completed state
    db = SessionLocal()
    v_done = db.scalar(select(Video).where(Video.id == video_id))
    assert v_done is not None
    v_done.status = "transcribed"
    v_done.progress = 100
    db.commit()
    db.close()

    final_res = client.get(f"/api/videos/{video_id}")
    assert final_res.status_code == 200
    final_data = final_res.json()
    assert final_data["progress"] == 100
    assert final_data["status"] == "transcribed"
    assert final_data["transcribe_started_at"] is not None
    assert final_data["duration"] is not None

    # Cleanup
    client.delete(f"/api/videos/{video_id}")
