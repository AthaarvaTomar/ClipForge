"""Tests for Phase 8: B-roll and Audio (Milestones M1, M2, M3, M4)."""

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
from app.models.video import Video
from app.models.video_index import VideoIndex
from app.schemas.timeline import Item, Timeline, Track, TrackType
from app.services.planner_service import EditPlannerService
from app.services.timeline_compiler import TimelineCompiler
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
def db_session() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(scope="module")
def sample_video_clip(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Generate a small 720x1280 4-second test video with audio tone."""
    ffmpeg_bin = shutil.which("ffmpeg")
    assert ffmpeg_bin is not None, "ffmpeg required for video tests"

    tmp = tmp_path_factory.mktemp("phase8_media")
    video_path = tmp / "base_video.mp4"

    cmd = [
        ffmpeg_bin,
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc=duration=4:size=720x1280:rate=25",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=1000:duration=4",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-shortest",
        str(video_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return video_path


@pytest.fixture(scope="module")
def sample_music_clip(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Generate a 4-second background music audio clip."""
    ffmpeg_bin = shutil.which("ffmpeg")
    assert ffmpeg_bin is not None

    tmp = tmp_path_factory.mktemp("phase8_music")
    music_path = tmp / "bg_music.mp3"

    cmd = [
        ffmpeg_bin,
        "-y",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:duration=4",
        "-c:a",
        "libmp3lame",
        str(music_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return music_path


@pytest.fixture(scope="module")
def sample_overlay_image(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Generate a static test image."""
    ffmpeg_bin = shutil.which("ffmpeg")
    assert ffmpeg_bin is not None

    tmp = tmp_path_factory.mktemp("phase8_img")
    img_path = tmp / "overlay.png"

    cmd = [
        ffmpeg_bin,
        "-y",
        "-f",
        "lavfi",
        "-i",
        "color=c=coral:s=400x400:d=1",
        "-vframes",
        "1",
        str(img_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return img_path


def test_m1_stock_search_pexels_and_pixabay(client: TestClient) -> None:
    """Milestone M1: Keyword search returns downloadable clips with attribution."""
    # 1. Search Pexels video
    resp_pexels = client.get(
        "/api/assets/search",
        params={"q": "technology", "provider": "pexels", "media_type": "video"},
    )
    assert resp_pexels.status_code == 200
    data_p = resp_pexels.json()
    assert data_p["provider"] == "pexels"
    assert len(data_p["items"]) > 0

    item = data_p["items"][0]
    assert item["media_type"] == "video"
    assert item["download_url"]
    assert item["attribution"]["author"]
    assert item["attribution"]["provider"] == "pexels"
    assert (
        "attribution" in item["attribution"]["license"].lower()
        or "free" in item["attribution"]["license"].lower()
    )

    # 2. Search Pixabay image
    resp_pixabay = client.get(
        "/api/assets/search", params={"q": "nature", "provider": "pixabay", "media_type": "image"}
    )
    assert resp_pixabay.status_code == 200
    data_px = resp_pixabay.json()
    assert data_px["provider"] == "pixabay"
    assert len(data_px["items"]) > 0
    img_item = data_px["items"][0]
    assert img_item["media_type"] == "image"
    assert img_item["attribution"]["provider"] == "pixabay"


def test_m1_import_and_upload_asset(client: TestClient, sample_overlay_image: Path) -> None:
    """Milestone M1: Upload images/video and import stock items into asset library."""
    # 1. Import stock item
    stock_item_payload = {
        "id": "stock_demo_1",
        "provider": "pexels",
        "title": "Modern Coding Workspace",
        "media_type": "video",
        "thumbnail_url": "https://example.com/thumb.jpg",
        "preview_url": "https://example.com/prev.mp4",
        "download_url": "https://example.com/download.mp4",
        "duration_s": 4.0,
        "width": 1280,
        "height": 720,
        "attribution": {
            "author": "TechShooter",
            "author_url": "https://pexels.com/@techshooter",
            "provider": "pexels",
            "license": "Free to use under Pexels license",
            "source_url": "https://pexels.com/video/123",
        },
    }

    import_resp = client.post(
        "/api/assets/import",
        json={"stock_item": stock_item_payload, "custom_name": "My Tech B-Roll"},
    )
    assert import_resp.status_code == 201
    asset_data = import_resp.json()
    assert asset_data["name"] == "My Tech B-Roll"
    assert asset_data["source_type"] == "pexels"
    assert asset_data["attribution"]["author"] == "TechShooter"
    assert Path(asset_data["file_path"]).exists()

    # 2. Upload an image asset
    with sample_overlay_image.open("rb") as f:
        upload_resp = client.post(
            "/api/assets/upload",
            files={"file": ("overlay.png", f, "image/png")},
            data={"name": "Logo Watermark", "media_type": "image"},
        )
    assert upload_resp.status_code == 201
    uploaded = upload_resp.json()
    assert uploaded["name"] == "Logo Watermark"
    assert uploaded["media_type"] == "image"

    # 3. Retrieve asset file
    file_resp = client.get(f"/api/assets/{uploaded['id']}/file")
    assert file_resp.status_code == 200
    assert len(file_resp.content) > 0

    # 4. List assets
    list_resp = client.get("/api/assets")
    assert list_resp.status_code == 200
    assert list_resp.json()["total"] >= 2


def test_m2_overlay_compositing_render(
    sample_video_clip: Path,
    sample_overlay_image: Path,
    tmp_path: Path,
) -> None:
    """Milestone M2: B-roll/image on overlay track with position, scale, fades renders cleanly."""
    out_file = tmp_path / "rendered_overlay.mp4"

    # Construct timeline with main video track and overlay track
    tl = Timeline(
        id="tl_m2_test",
        video_id="vid_1",
        version=1,
        source_duration_ms=4000,
        tracks=[
            Track(
                id="trk_v1",
                type=TrackType.VIDEO,
                name="Main Video",
                items=[
                    Item(
                        id="itm_v1",
                        source="src_main",
                        src_in=0,
                        src_out=4000,
                        start=0,
                        volume=1.0,
                    )
                ],
            ),
            Track(
                id="trk_overlay",
                type=TrackType.OVERLAY,
                name="B-Roll Overlay",
                items=[
                    Item(
                        id="itm_broll_1",
                        source="src_image_overlay",
                        src_in=0,
                        src_out=2000,
                        start=1000,
                        volume=0.0,
                        effects={
                            "position": "pip",
                            "scale": "fit",
                            "fade_in_ms": 300,
                            "fade_out_ms": 300,
                            "opacity": 0.9,
                        },
                    )
                ],
            ),
        ],
    )

    compiler = TimelineCompiler(
        timeline=tl,
        source_resolver={
            "src_main": sample_video_clip,
            "src_image_overlay": sample_overlay_image,
        },
        output_path=out_file,
        target_resolution=(720, 1280),
    )

    filter_complex, final_v, final_a, _ = compiler.build_filter_graph(tmp_dir=tmp_path)
    # Check that overlay position, fade, and scale expressions were generated
    assert "overlay=" in filter_complex
    assert "fade=t=in" in filter_complex
    assert "fade=t=out" in filter_complex
    assert "between(t,1.000,3.000)" in filter_complex

    # Execute FFmpeg build and verify output video exists and plays
    cmd, _ = compiler.build_command(tmp_dir=tmp_path)
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode == 0, f"FFmpeg failed: {res.stderr}"
    assert out_file.exists()
    assert out_file.stat().st_size > 5000


def test_m3_planner_broll_keywords_insertion(sample_video_clip: Path, db_session: Session) -> None:
    """Milestone M3: 'add B-roll' extracts keywords from transcript/index
    and inserts overlay ops.
    """
    # Setup test video and index in DB
    video = Video(
        filename="coding_tutorial.mp4",
        file_path=str(sample_video_clip),
        duration=60.0,
        width=1920,
        height=1080,
        status="READY",
    )
    db_session.add(video)
    db_session.commit()

    index = VideoIndex(
        video_id=video.id,
        status="READY",
        chapters=[
            {
                "title": "Deep Dive Architecture",
                "start": 0.0,
                "end": 30.0,
                "summary": "System architectural breakdown",
            },
            {
                "title": "Database Schema",
                "start": 30.0,
                "end": 60.0,
                "summary": "Database engine design",
            },
        ],
        visuals=[
            {
                "scene_index": 0,
                "timestamp_s": 5.0,
                "tags": ["coding", "terminal"],
                "caption": "Coding session",
            },
        ],
    )
    db_session.add(index)
    db_session.commit()

    # Create timeline in DB
    from app.services.timeline_service import TimelineService

    tl = TimelineService.create_timeline(db_session, video.id)

    rationale, ops = EditPlannerService.generate_plan(
        db=db_session,
        timeline_id=tl.id,
        prompt="add B-roll to enhance the video",
    )

    assert len(ops) >= 2  # add_track + add_item
    track_op = next(op for op in ops if op["type"] == "add_track")
    assert track_op["track_type"] == "overlay"

    item_op = next(op for op in ops if op["type"] == "add_item")
    assert item_op["item"]["start"] >= 0
    assert item_op["item"]["effects"]["fade_in_ms"] == 300
    assert "deep dive architecture" in rationale.lower() or "coding" in rationale.lower()


def test_m4_audio_ducking_and_loudness_normalisation(
    sample_video_clip: Path,
    sample_music_clip: Path,
    tmp_path: Path,
) -> None:
    """Milestone M4: Speech denoise, music ducking under speech, and loudness normalization."""
    out_file = tmp_path / "rendered_audio_ducking.mp4"

    tl = Timeline(
        id="tl_m4_test",
        video_id="vid_m4",
        version=1,
        source_duration_ms=4000,
        tracks=[
            Track(
                id="trk_v1",
                type=TrackType.VIDEO,
                name="Main Video Dialogue",
                items=[
                    Item(
                        id="itm_v1",
                        source="src_speech",
                        src_in=0,
                        src_out=4000,
                        start=0,
                        volume=1.0,
                    )
                ],
            ),
            Track(
                id="trk_music",
                type=TrackType.AUDIO,
                name="Background Music Track",
                items=[
                    Item(
                        id="itm_music",
                        source="src_bgm",
                        src_in=0,
                        src_out=4000,
                        start=0,
                        volume=0.8,
                    )
                ],
            ),
        ],
    )

    compiler = TimelineCompiler(
        timeline=tl,
        source_resolver={
            "src_speech": sample_video_clip,
            "src_bgm": sample_music_clip,
        },
        output_path=out_file,
        target_resolution=(720, 1280),
    )

    filter_complex, final_v, final_a, _ = compiler.build_filter_graph(tmp_dir=tmp_path)

    # 1. Speech denoise / conditioning filter
    assert "highpass=f=80,lowpass=f=8000" in filter_complex
    # 2. Sidechain compression ducking music under speech
    assert "sidechaincompress=" in filter_complex
    assert "threshold=0.08" in filter_complex
    # 3. Master loudness normalization
    assert "loudnorm=I=-16:TP=-1.5:LRA=11" in filter_complex

    # Run FFmpeg compilation and verify output
    cmd, _ = compiler.build_command(tmp_dir=tmp_path)
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode == 0, f"FFmpeg execution failed: {res.stderr}"
    assert out_file.exists()
    assert out_file.stat().st_size > 5000
