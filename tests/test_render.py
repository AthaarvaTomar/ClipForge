"""Tests for Milestone A11: Render Pipeline, Progress, Cleanup, and Endpoints."""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.main import app
from app.models.clip import Clip
from app.models.transcript import Transcript
from app.models.video import Video
from app.schemas.edit_spec import (
    CaptionSpec,
    CutSegment,
    EditSpec,
    GradeSpec,
    ReframeSpec,
)
from app.services.ffmpeg_builder import (
    FFmpegBuilder,
    FFmpegBuilderError,
    extract_preview_frame,
)
from app.services.job_service import JobService
from app.services.video_probe import probe_video
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


@pytest.fixture(autouse=True)
def clean_clips_state(db_session: Session) -> Generator[None, None, None]:
    from sqlalchemy import delete

    db_session.execute(delete(Clip))
    db_session.commit()
    yield
    db_session.execute(delete(Clip))
    db_session.commit()


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


@pytest.fixture(scope="module")
def sample_video(tmp_path_factory: pytest.TempPathFactory) -> Generator[Path, None, None]:
    """Generate a clean 2.5s 1280x720 test video."""
    ffmpeg_bin = shutil.which("ffmpeg")
    assert ffmpeg_bin is not None

    tmp_dir = tmp_path_factory.mktemp("render_test_video")
    out_video = tmp_dir / "sample_test.mp4"

    cmd = [
        ffmpeg_bin,
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc=duration=2.5:size=1280x720:rate=30",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:duration=2.5:sample_rate=44100",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        str(out_video),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode == 0, f"FFmpeg failed: {res.stderr}"
    yield out_video


# ---------------------------------------------------------------------------
# Unit Tests: Progress, Cleanup, Frame Extraction
# ---------------------------------------------------------------------------


def test_ffmpeg_builder_with_progress(sample_video: Path, tmp_path: Path) -> None:
    out_file = tmp_path / "progress_rendered.mp4"
    spec = EditSpec(
        cuts=[CutSegment(start=0.0, end=1.5)],
        aspect_ratio="9:16",
        reframe=ReframeSpec(strategy="crop"),
    )

    builder = FFmpegBuilder(
        input_path=sample_video,
        output_path=out_file,
        edit_spec=spec,
    )

    progress_reports: list[float] = []

    def on_progress(pct: float) -> None:
        progress_reports.append(pct)

    res = builder.run(on_progress=on_progress)
    assert res.is_file()
    assert len(progress_reports) > 0
    assert progress_reports[-1] == 100.0


def test_ffmpeg_builder_cleanup_on_failure(tmp_path: Path) -> None:
    out_file = tmp_path / "should_be_cleaned_up.mp4"
    spec = EditSpec(
        cuts=[CutSegment(start=0.0, end=1.0)],
        aspect_ratio="9:16",
    )

    builder = FFmpegBuilder(
        input_path=tmp_path / "non_existent_input.mp4",
        output_path=out_file,
        edit_spec=spec,
    )

    with pytest.raises(FFmpegBuilderError):
        builder.run()

    # Verify partial or erroneous output file does NOT remain on disk
    assert not out_file.exists()


def test_extract_preview_frame(sample_video: Path) -> None:
    frame_bytes = extract_preview_frame(sample_video, timestamp=0.5)
    assert isinstance(frame_bytes, bytes)
    assert len(frame_bytes) > 0
    # Standard JPEG SOI marker is 0xFF 0xD8
    assert frame_bytes.startswith(b"\xff\xd8")


# ---------------------------------------------------------------------------
# Celery Task & Integration Tests
# ---------------------------------------------------------------------------


def test_render_clip_task_end_to_end(
    db_session: Session, sample_video: Path, tmp_path: Path
) -> None:
    # 1. Setup Video & Transcript
    video = Video(
        filename="test_video.mp4",
        file_path=str(sample_video),
        duration=2.5,
        width=1280,
        height=720,
        fps=30.0,
        orientation="landscape",
        status="PROCESSED",
    )
    db_session.add(video)
    db_session.commit()
    db_session.refresh(video)

    transcript = Transcript(
        video_id=video.id,
        language="en",
        text="Fast clips for social media.",
        words=[
            {"word": "Fast", "start": 0.2, "end": 0.5},
            {"word": "clips", "start": 0.55, "end": 0.9},
            {"word": "for", "start": 0.95, "end": 1.2},
            {"word": "social", "start": 1.25, "end": 1.6},
            {"word": "media.", "start": 1.65, "end": 2.1},
        ],
    )
    db_session.add(transcript)
    db_session.commit()

    # 2. Setup Clip
    edit_spec = EditSpec(
        cuts=[CutSegment(start=0.1, end=2.0)],
        aspect_ratio="9:16",
        reframe=ReframeSpec(strategy="crop"),
        captions=CaptionSpec(
            enabled=True,
            animation="highlight",
            primary_color="#FFFFFF",
            highlight_color="#00FFCC",
        ),
        grade=GradeSpec(preset="cinematic"),
    )
    clip = Clip(
        video_id=video.id,
        title="Epic Reel",
        start_time=0.1,
        end_time=2.0,
        edit_spec=edit_spec.model_dump(),
        status="DRAFT",
    )
    db_session.add(clip)
    db_session.commit()
    db_session.refresh(clip)

    job = JobService.create_job(
        db=db_session,
        job_type="RENDER",
        clip_id=clip.id,
        video_id=video.id,
    )

    # 3. Run Celery task
    result = render_clip_task(job_id=job.id, clip_id=clip.id)
    assert "error" not in result
    assert "output_path" in result

    # 4. Verify DB state and disk file
    db_session.refresh(clip)
    assert clip.status == "COMPLETED"
    assert clip.output_path is not None
    out_path = Path(clip.output_path)
    assert out_path.is_file()
    assert out_path.stat().st_size > 0

    # Probe output video
    meta = probe_video(out_path)
    assert meta.width == 1080
    assert meta.height == 1920
    assert meta.orientation == "portrait"
    assert 1.7 <= meta.duration <= 2.1

    # Check job completion
    db_session.expire_all()
    job_record = JobService.get_job(db_session, job.id)
    assert job_record is not None
    assert job_record.status == "COMPLETED"
    assert job_record.progress == 100


# ---------------------------------------------------------------------------
# API Endpoints: /api/clips/{id}/render, download, preview-frame
# ---------------------------------------------------------------------------


def test_api_render_download_preview_flow(
    client: TestClient, db_session: Session, sample_video: Path
) -> None:
    # 1. Create Video
    video = Video(
        filename="api_sample.mp4",
        file_path=str(sample_video),
        duration=2.5,
        width=1280,
        height=720,
        fps=30.0,
        orientation="landscape",
        status="PROCESSED",
    )
    db_session.add(video)
    db_session.commit()
    db_session.refresh(video)

    # 2. Create Clip via POST /api/clips
    spec = EditSpec(
        cuts=[CutSegment(start=0.0, end=1.5)],
        aspect_ratio="9:16",
        reframe=ReframeSpec(strategy="crop"),
        captions=CaptionSpec(enabled=False),
    )
    clip_payload = {
        "video_id": video.id,
        "title": "API Render Clip",
        "edit_spec": spec.model_dump(),
    }
    create_res = client.post("/api/clips", json=clip_payload)
    assert create_res.status_code == 201
    clip_data = create_res.json()
    clip_id = clip_data["id"]

    # 3. Preview Frame BEFORE rendering (from source video)
    preview_res = client.get(f"/api/clips/{clip_id}/preview-frame?time=0.5")
    assert preview_res.status_code == 200
    assert preview_res.headers["content-type"] == "image/jpeg"
    assert preview_res.content.startswith(b"\xff\xd8")

    # 4. Attempt download before render should fail with 400
    down_pre = client.get(f"/api/clips/{clip_id}/download")
    assert down_pre.status_code == 400

    # 5. Dispatch Render via POST /api/clips/{id}/render
    # (Since Celery is eager, task runs synchronously during the request)
    render_res = client.post(f"/api/clips/{clip_id}/render")
    assert render_res.status_code == 202
    job_data = render_res.json()
    assert job_data["job_type"] == "RENDER"
    assert job_data["clip_id"] == clip_id

    # 6. Check Clip status is now COMPLETED
    get_clip_res = client.get(f"/api/clips/{clip_id}")
    assert get_clip_res.status_code == 200
    assert get_clip_res.json()["status"] == "COMPLETED"

    # 7. Download rendered video
    down_post = client.get(f"/api/clips/{clip_id}/download")
    assert down_post.status_code == 200
    assert down_post.headers["content-type"] == "video/mp4"
    assert len(down_post.content) > 0

    # 8. Preview Frame AFTER rendering (from rendered video)
    preview_rendered = client.get(f"/api/clips/{clip_id}/preview-frame?time=0.5")
    assert preview_rendered.status_code == 200
    assert preview_rendered.headers["content-type"] == "image/jpeg"
    assert preview_rendered.content.startswith(b"\xff\xd8")
