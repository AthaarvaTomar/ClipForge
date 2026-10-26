"""Tests for Milestone R1: Video Proxies, Thumbnail Strips, and Waveforms."""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.main import app
from app.models.video import Video
from app.services.asset_service import (
    assets_ready,
    generate_assets,
    proxy_path,
    strip_path,
    waveform_path,
)
from app.services.job_service import JobService
from app.services.video_probe import probe_video
from app.tasks.asset_task import generate_assets_task
from app.tasks.celery_app import celery_app


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


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(scope="module")
def sample_video(tmp_path_factory: pytest.TempPathFactory) -> Generator[Path, None, None]:
    ffmpeg_bin = shutil.which("ffmpeg")
    assert ffmpeg_bin is not None

    tmp_dir = tmp_path_factory.mktemp("asset_test_video")
    out_video = tmp_dir / "sample_asset_test.mp4"

    cmd = [
        ffmpeg_bin,
        "-y",
        "-f", "lavfi", "-i", "testsrc=duration=2.5:size=1280x720:rate=30",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=2.5:sample_rate=44100",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        str(out_video),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode == 0, f"FFmpeg failed: {res.stderr}"
    yield out_video


@pytest.fixture(scope="module")
def sample_video_no_audio(tmp_path_factory: pytest.TempPathFactory) -> Generator[Path, None, None]:
    ffmpeg_bin = shutil.which("ffmpeg")
    assert ffmpeg_bin is not None

    tmp_dir = tmp_path_factory.mktemp("asset_test_no_audio")
    out_video = tmp_dir / "no_audio.mp4"

    cmd = [
        ffmpeg_bin,
        "-y",
        "-f", "lavfi", "-i", "testsrc=duration=1.5:size=640x360:rate=30",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-an",
        str(out_video),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode == 0, f"FFmpeg failed: {res.stderr}"
    yield out_video


def test_generate_assets_service(sample_video: Path) -> None:
    video_id = "test_asset_vid_1"
    manifest = generate_assets(
        video_id=video_id,
        source=sample_video,
        duration=2.5,
        force=True,
    )
    assert manifest["video_id"] == video_id
    assert manifest["proxy_height"] == 360
    assert manifest["thumbnails"]["count"] >= 1
    assert manifest["waveform"]["has_audio"] is True
    assert manifest["waveform"]["count"] > 0

    assert assets_ready(video_id)
    p_path = proxy_path(video_id)
    assert p_path.is_file()
    probe = probe_video(p_path)
    assert probe.height == 360

    s_path = strip_path(video_id)
    assert s_path.is_file()
    assert s_path.stat().st_size > 0

    w_path = waveform_path(video_id)
    assert w_path.is_file()
    wave_data = json.loads(w_path.read_text(encoding="utf-8"))
    assert len(wave_data["peaks"]) > 0
    assert all(0.0 <= p <= 1.0 for p in wave_data["peaks"])


def test_generate_assets_no_audio(sample_video_no_audio: Path) -> None:
    video_id = "test_asset_no_audio"
    manifest = generate_assets(
        video_id=video_id,
        source=sample_video_no_audio,
        duration=1.5,
        force=True,
    )
    assert manifest["waveform"]["has_audio"] is False
    assert manifest["waveform"]["count"] == 0


def test_generate_assets_task_end_to_end(db_session: Session, sample_video: Path) -> None:
    video = Video(
        filename="celery_asset_test.mp4",
        file_path=str(sample_video),
        duration=2.5,
        width=1280,
        height=720,
        fps=30.0,
        orientation="landscape",
        status="ready",
    )
    db_session.add(video)
    db_session.commit()
    db_session.refresh(video)

    job = JobService.create_job(
        db=db_session,
        job_type="ASSETS",
        video_id=video.id,
    )

    result = generate_assets_task(job_id=job.id, video_id=video.id)
    assert "error" not in result
    assert result["video_id"] == video.id

    db_session.expire_all()
    job_record = JobService.get_job(db_session, job.id)
    assert job_record is not None
    assert job_record.status == "COMPLETED"
    assert job_record.progress == 100


def test_api_video_assets_endpoints(
    client: TestClient, db_session: Session, sample_video: Path
) -> None:
    # 1. Upload video via POST /api/videos (Celery is eager, so assets are generated)
    with open(sample_video, "rb") as f:
        res = client.post(
            "/api/videos",
            files={"file": ("api_test.mp4", f, "video/mp4")},
        )
    assert res.status_code == 201
    video_data = res.json()
    video_id = video_data["id"]

    # 2. Query /api/videos/{id}/assets
    assets_res = client.get(f"/api/videos/{video_id}/assets")
    assert assets_res.status_code == 200
    adata = assets_res.json()
    assert adata["video_id"] == video_id
    assert adata["ready"] is True
    assert adata["proxy_url"] == f"/api/videos/{video_id}/proxy"
    assert adata["thumbnail_strip_url"] == f"/api/videos/{video_id}/thumbnails/strip"
    assert adata["waveform_url"] == f"/api/videos/{video_id}/waveform"
    assert adata["manifest"] is not None

    # 3. Fetch Proxy video
    proxy_res = client.get(adata["proxy_url"])
    assert proxy_res.status_code == 200
    assert proxy_res.headers["content-type"] == "video/mp4"
    assert len(proxy_res.content) > 0

    # 4. Fetch Waveform JSON
    wave_res = client.get(adata["waveform_url"])
    assert wave_res.status_code == 200
    assert "application/json" in wave_res.headers["content-type"]
    wjson = wave_res.json()
    assert "peaks" in wjson
    assert len(wjson["peaks"]) > 0

    # 5. Fetch Thumbnail Strip
    strip_res = client.get(adata["thumbnail_strip_url"])
    assert strip_res.status_code == 200
    assert strip_res.headers["content-type"] == "image/jpeg"
    assert len(strip_res.content) > 0

    # 6. Fetch /thumbnails alias and individual thumbnail
    thumbs_alias_res = client.get(f"/api/videos/{video_id}/thumbnails")
    assert thumbs_alias_res.status_code == 200
    assert thumbs_alias_res.headers["content-type"] == "image/jpeg"

    first_thumb_res = client.get(f"/api/videos/{video_id}/thumbnails/0001.jpg")
    assert first_thumb_res.status_code == 200
    assert first_thumb_res.headers["content-type"] == "image/jpeg"

    # 7. Delete video cleans up assets
    del_res = client.delete(f"/api/videos/{video_id}")
    assert del_res.status_code == 200
    assert not assets_ready(video_id)
