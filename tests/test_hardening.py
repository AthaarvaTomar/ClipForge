"""Tests for Milestone A13: Hardening, Security, CORS, Error Format,
and Killing FFmpeg mid-render.
"""

from __future__ import annotations

import subprocess
from collections.abc import Generator
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import settings
from app.core.database import SessionLocal
from app.main import app
from app.models.clip import Clip
from app.models.video import Video
from app.schemas.edit_spec import CutSegment, EditSpec, ReframeSpec
from app.services.ffmpeg_builder import FFmpegBuilder, FFmpegBuilderError
from app.services.job_service import JobService
from app.tasks.celery_app import celery_app
from app.tasks.render_task import render_clip_task


@pytest.fixture(autouse=True)
def configure_celery_eager() -> Generator[None, None, None]:
    """Ensure Celery tasks execute synchronously within tests."""
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


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def dummy_video_file(tmp_path: Path) -> Path:
    vid = tmp_path / "dummy_video.mp4"
    vid.write_bytes(b"dummy video data for testing")
    return vid


# ---------------------------------------------------------------------------
# Standardized Error Shape Tests
# ---------------------------------------------------------------------------


def test_error_format_404_not_found(client: TestClient) -> None:
    response = client.get("/api/videos/non-existent-uuid-12345")
    assert response.status_code == 404
    data = response.json()
    assert "detail" in data
    assert "error" in data
    assert data["error"]["code"] == "NOT_FOUND"
    assert "not found" in data["error"]["message"].lower()


def test_error_format_422_validation_error(client: TestClient) -> None:
    # Invalid payload (missing required video_id)
    response = client.post("/api/clips", json={"title": "No video id"})
    assert response.status_code == 422
    data = response.json()
    assert "detail" in data
    assert "error" in data
    assert data["error"]["code"] == "VALIDATION_ERROR"
    assert "details" in data["error"]


# ---------------------------------------------------------------------------
# Optional API Key Authentication Tests
# ---------------------------------------------------------------------------


def test_api_key_when_disabled_allows_all(client: TestClient) -> None:
    original_key = settings.API_KEY
    settings.API_KEY = None
    try:
        res = client.get("/api/presets")
        assert res.status_code == 200
    finally:
        settings.API_KEY = original_key


def test_api_key_when_configured_enforces_auth(client: TestClient) -> None:
    original_key = settings.API_KEY
    settings.API_KEY = "test-secret-key-1234"
    try:
        # 1. Unauthenticated request should be rejected with 401
        res_no_key = client.get("/api/presets")
        assert res_no_key.status_code == 401
        assert res_no_key.json()["error"]["code"] == "UNAUTHORIZED"

        # 2. Invalid key should be rejected with 401
        res_wrong_key = client.get("/api/presets", headers={"X-API-Key": "wrong-key"})
        assert res_wrong_key.status_code == 401

        # 3. Valid key via X-API-Key header should succeed
        res_valid_header = client.get(
            "/api/presets", headers={"X-API-Key": "test-secret-key-1234"}
        )
        assert res_valid_header.status_code == 200

        # 4. Valid key via Bearer token should succeed
        res_valid_bearer = client.get(
            "/api/presets", headers={"Authorization": "Bearer test-secret-key-1234"}
        )
        assert res_valid_bearer.status_code == 200

        # 5. /health remains accessible without API key
        res_health = client.get("/health")
        assert res_health.status_code == 200
    finally:
        settings.API_KEY = original_key


# ---------------------------------------------------------------------------
# CORS & Timing Middleware Tests
# ---------------------------------------------------------------------------


def test_cors_headers_and_timing_header(client: TestClient) -> None:
    response = client.get("/health", headers={"Origin": "http://localhost:3000"})
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") in ("http://localhost:3000", "*")
    assert "X-Process-Time-Ms" in response.headers



# ---------------------------------------------------------------------------
# Concurrency Limit Tests
# ---------------------------------------------------------------------------


def test_render_concurrency_limit(
    client: TestClient, db_session: Session, dummy_video_file: Path
) -> None:
    video = Video(
        filename="concurrency_test.mp4",
        file_path=str(dummy_video_file),
        duration=10.0,
        status="PROCESSED",
    )
    db_session.add(video)
    db_session.commit()

    try:
        # Pre-populate 2 active rendering clips (max limit = 2)
        for i in range(settings.RENDER_CONCURRENCY_LIMIT):
            active_clip = Clip(
                video_id=video.id,
                title=f"Rendering clip {i}",
                start_time=0.0,
                end_time=5.0,
                edit_spec={"cuts": [{"start": 0.0, "end": 5.0}]},
                status="RENDERING",
            )
            db_session.add(active_clip)
        db_session.commit()

        # Create new clip attempting to render
        new_clip = Clip(
            video_id=video.id,
            title="Excess clip",
            start_time=0.0,
            end_time=3.0,
            edit_spec={"cuts": [{"start": 0.0, "end": 3.0}]},
            status="DRAFT",
        )
        db_session.add(new_clip)
        db_session.commit()

        # Should be rejected with 429 Too Many Requests
        res = client.post(f"/api/clips/{new_clip.id}/render")
        assert res.status_code == 429
        assert "Maximum concurrent renders reached" in res.json()["detail"]
    finally:
        from sqlalchemy import delete

        db_session.execute(delete(Clip).where(Clip.video_id == video.id))
        db_session.execute(delete(Video).where(Video.id == video.id))
        db_session.commit()



# ---------------------------------------------------------------------------
# Killing FFmpeg Mid-Render Marks Job FAILED with Message
# ---------------------------------------------------------------------------


def test_killing_ffmpeg_mid_render_marks_job_failed_with_message(
    db_session: Session, dummy_video_file: Path, tmp_path: Path
) -> None:
    """Verifies that killing or aborting FFmpeg mid-render cleans up partial files

    and updates the database job and clip status to FAILED with an explicit error message.
    """
    video = Video(
        filename="kill_test.mp4",
        file_path=str(dummy_video_file),
        duration=10.0,
        width=1280,
        height=720,
        fps=30.0,
        orientation="landscape",
        status="PROCESSED",
    )
    db_session.add(video)
    db_session.commit()

    spec = EditSpec(
        cuts=[CutSegment(start=0.0, end=5.0)],
        aspect_ratio="9:16",
        reframe=ReframeSpec(strategy="crop"),
    )
    clip = Clip(
        video_id=video.id,
        title="Mid-Render Kill Test",
        start_time=0.0,
        end_time=5.0,
        edit_spec=spec.model_dump(),
        status="DRAFT",
    )
    db_session.add(clip)
    db_session.commit()

    job = JobService.create_job(
        db=db_session,
        job_type="RENDER",
        clip_id=clip.id,
        video_id=video.id,
    )

    # Mock FFmpegBuilder.run to simulate an external process kill (SIGKILL / returncode -9)
    partial_output = settings.OUTPUT_DIR / f"{clip.id}.mp4"
    partial_output.write_bytes(b"partial byte stream before SIGKILL")


    def mock_run_killed(*args: object, **kwargs: object) -> Path:
        # Simulate partial file remaining before process kill
        assert partial_output.exists()
        # Raise FFmpegBuilderError simulating process termination
        raise FFmpegBuilderError(
            "FFmpeg render process failed with code -9: Process terminated by SIGKILL"
        )

    with patch.object(FFmpegBuilder, "run", side_effect=mock_run_killed):
        with pytest.raises(FFmpegBuilderError) as exc_info:
            render_clip_task(job_id=job.id, clip_id=clip.id)

        assert "code -9" in str(exc_info.value)

    # 1. Verify Job status is marked FAILED with descriptive error message
    db_session.expire_all()
    job_record = JobService.get_job(db_session, job.id)
    assert job_record is not None
    assert job_record.status == "FAILED"
    assert job_record.error_message is not None
    assert "code -9" in job_record.error_message
    assert "Process terminated by SIGKILL" in job_record.error_message

    # 2. Verify Clip status is marked FAILED
    from sqlalchemy import select

    clip_record = db_session.scalar(select(Clip).where(Clip.id == clip.id))
    assert clip_record is not None
    assert clip_record.status == "FAILED"

    # 3. Verify partial output file was cleaned up on failure
    assert not partial_output.exists()

    # Clean up DB records
    from sqlalchemy import delete

    db_session.execute(delete(Clip).where(Clip.id == clip.id))
    db_session.execute(delete(Video).where(Video.id == video.id))
    db_session.commit()



def test_ffmpeg_timeout_handling(tmp_path: Path) -> None:
    """Verifies that an FFmpeg render timing out raises FFmpegBuilderError with timeout message."""
    input_file = tmp_path / "input.mp4"
    input_file.write_bytes(b"dummy")
    spec = EditSpec(cuts=[CutSegment(start=0.0, end=2.0)])
    builder = FFmpegBuilder(
        input_path=input_file,
        output_path=tmp_path / "out.mp4",
        edit_spec=spec,
        source_width=1080,
        source_height=1920,
        has_audio=False,
    )

    with patch.object(
        subprocess,
        "run",
        side_effect=subprocess.TimeoutExpired(cmd=["ffmpeg"], timeout=0.1),
    ):
        with pytest.raises(FFmpegBuilderError) as exc:
            builder.run(timeout=0.1)
        assert "timed out after 0.1s" in str(exc.value)

