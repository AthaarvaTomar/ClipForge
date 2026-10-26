"""Tests for Phase 5: Footage Indexing (Milestones I1 through I7)."""

from __future__ import annotations

import shutil
import subprocess
import uuid
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.main import app
from app.models.transcript import Transcript
from app.models.video import Video
from app.services.highlight_service import HighlightService
from app.services.job_service import JobService
from app.services.scene_detector import SceneDetectorService
from app.services.silence_detector import SilenceFillerService
from app.services.take_detector import RepeatedTakeService
from app.services.visual_service import VisualUnderstandingService
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
def sample_indexed_video(tmp_path_factory: pytest.TempPathFactory) -> Generator[Path, None, None]:
    """Generate a multi-scene video with audio speech and silence gaps."""
    ffmpeg_bin = shutil.which("ffmpeg")
    assert ffmpeg_bin is not None

    tmp_dir = tmp_path_factory.mktemp("indexed_video")
    out_video = tmp_dir / "indexing_sample.mp4"

    # Create video with 2 visual scenes (blue for 1.5s, red for 1.5s)
    # and audio with 0.8s silence in middle
    cmd = [
        ffmpeg_bin,
        "-y",
        "-f", "lavfi", "-i", "color=c=blue:s=320x240:d=1.5:r=30",
        "-f", "lavfi", "-i", "color=c=red:s=320x240:d=1.5:r=30",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=1.0:sample_rate=44100",
        "-f", "lavfi", "-i", "anullsrc=channel_layout=mono:sample_rate=44100:duration=1.0",
        "-f", "lavfi", "-i", "sine=frequency=880:duration=1.0:sample_rate=44100",
        "-filter_complex",
        "[0:v][1:v]concat=n=2:v=1:a=0[vcat];"
        "[2:a][3:a][4:a]concat=n=3:v=0:a=1[acat]",
        "-map", "[vcat]",
        "-map", "[acat]",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        str(out_video),
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    yield out_video


def test_i1_scene_detection_service(sample_indexed_video: Path) -> None:
    """I1: PySceneDetect scene boundaries saved per video."""
    scenes = SceneDetectorService.detect_scenes(sample_indexed_video, threshold=20.0)
    assert len(scenes) >= 1
    first_scene = scenes[0]
    assert "start_time" in first_scene
    assert "end_time" in first_scene
    assert "duration" in first_scene
    assert first_scene["start_time"] == 0.0
    assert first_scene["end_time"] > 0.0


def test_i2_silence_and_filler_detection(sample_indexed_video: Path) -> None:
    """I2: FFmpeg silencedetect plus filler words from transcript."""
    # 1. Silences via FFmpeg
    silences = SilenceFillerService.detect_silences(
        sample_indexed_video,
        noise_threshold_db=-25.0,
        min_duration_sec=0.3,
    )
    assert isinstance(silences, list)
    if silences:
        assert silences[0]["duration"] > 0.1

    # 2. Filler words from transcript words
    words = [
        {"word": "Well", "start": 0.0, "end": 0.4},
        {"word": "um", "start": 0.5, "end": 0.8, "probability": 0.95},
        {"word": "I", "start": 0.9, "end": 1.1},
        {"word": "think", "start": 1.2, "end": 1.5},
        {"word": "uh,", "start": 1.6, "end": 1.9, "probability": 0.92},
        {"word": "this", "start": 2.0, "end": 2.3},
        {"word": "is", "start": 2.4, "end": 2.6},
        {"word": "great.", "start": 2.7, "end": 3.0},
    ]
    fillers = SilenceFillerService.detect_fillers(words)
    assert len(fillers) == 2
    filler_words = [f["word"] for f in fillers]
    assert "um" in filler_words
    assert "uh" in filler_words
    assert fillers[0]["start_time"] == 0.5
    assert fillers[1]["start_time"] == 1.6


def test_i3_repeated_takes_grouping() -> None:
    """I3: Fuzzy-match adjacent transcript sentences, group near-duplicates and mark best take."""
    sentences = [
        {
            "text": "Today we are going to talk about the future of artificial.",
            "start_time": 0.0,
            "end_time": 3.0,
            "duration": 3.0,
        },
        {
            "text": (
                "Today we are going to discuss the future of artificial intelligence, wait "
                "let me redo."
            ),
            "start_time": 4.0,
            "end_time": 8.0,
            "duration": 4.0,
        },
        {
            "text": (
                "Today we are going to discuss the future of artificial intelligence in modern "
                "video editing."
            ),
            "start_time": 9.0,
            "end_time": 14.5,
            "duration": 5.5,
        },
        {
            "text": "This completely unrelated sentence begins the real lecture.",
            "start_time": 15.0,
            "end_time": 19.0,
            "duration": 4.0,
        },
    ]

    take_groups = RepeatedTakeService.detect_repeated_takes(
        sentences=sentences, similarity_threshold=60.0
    )
    assert len(take_groups) == 1
    group = take_groups[0]
    assert len(group["takes"]) == 3

    # Verify best take is chosen and marked is_best=True
    chosen_idx = group["chosen_take_index"]
    assert chosen_idx == 2  # The 3rd take is the complete final take
    assert group["takes"][chosen_idx]["is_best"] is True
    assert "video editing" in group["takes"][chosen_idx]["text"]


def test_i4_visual_understanding(sample_indexed_video: Path) -> None:
    """I4: Sample one frame per scene and return caption and tags."""
    scenes = [{"index": 0, "start_time": 0.0, "end_time": 1.5, "duration": 1.5}]
    visuals = VisualUnderstandingService.analyze_scenes(
        sample_indexed_video, scenes=scenes, max_scenes=1
    )
    assert len(visuals) == 1
    vis = visuals[0]
    assert vis["scene_index"] == 0
    assert "caption" in vis
    assert len(vis["caption"]) > 0
    assert "tags" in vis
    assert len(vis["tags"]) > 0


def test_i7_chapters_hook_and_highlights() -> None:
    """I7: Upgrade highlight detection to produce chapters, hook candidate, and highlights."""
    transcript_text = (
        "Welcome to our podcast on artificial intelligence in film. "
        "The most shocking thing about automated editing is speed. "
        "We can now render high retention vertical clips in seconds."
    )
    insights = HighlightService.detect_index_insights(
        text=transcript_text,
        duration=25.0,
    )
    assert "chapters" in insights
    assert len(insights["chapters"]) >= 1
    assert "hook" in insights
    assert "hook" in insights["hook"]
    assert "highlights" in insights
    assert len(insights["highlights"]) >= 1


def test_i6_index_orchestrator_and_api_flow(
    client: TestClient,
    db_session: Session,
    sample_indexed_video: Path,
) -> None:
    """I6: End-to-end Celery indexing pipeline and GET /api/videos/{id}/index."""
    # 1. Setup Video & pre-existing transcript
    video_id = f"vid_idx_{uuid.uuid4().hex[:8]}"
    video = Video(
        id=video_id,
        filename="index_test_video.mp4",
        file_path=str(sample_indexed_video),
        duration=3.0,
        width=320,
        height=240,
        fps=30.0,
        orientation="landscape",
        status="ready",
    )
    transcript = Transcript(
        video_id=video_id,
        language="en",
        text="Hello world, um, this is an indexed video test.",
        words=[
            {"word": "Hello", "start": 0.0, "end": 0.5},
            {"word": "world,", "start": 0.6, "end": 1.0},
            {"word": "um,", "start": 1.1, "end": 1.4, "probability": 0.95},
            {"word": "this", "start": 1.5, "end": 1.8},
            {"word": "is", "start": 1.9, "end": 2.1},
            {"word": "an", "start": 2.2, "end": 2.4},
            {"word": "indexed", "start": 2.5, "end": 2.8},
            {"word": "video", "start": 2.9, "end": 3.0},
        ],
    )
    db_session.add(video)
    db_session.add(transcript)
    db_session.commit()

    # 2. POST /api/videos/{id}/index triggers indexing job
    res_post = client.post(f"/api/videos/{video_id}/index")
    assert res_post.status_code == 202
    job_info = res_post.json()
    assert job_info["job_type"] == "VIDEO_INDEX"
    job_id = job_info["id"]

    # In eager mode, job should have completed
    job = JobService.get_job(db_session, job_id)
    assert job is not None
    assert job.status == "COMPLETED"

    # 3. GET /api/videos/{id}/index returns everything
    res_get = client.get(f"/api/videos/{video_id}/index")
    assert res_get.status_code == 200
    data = res_get.json()
    assert data["video_id"] == video_id
    assert data["status"] == "READY"
    assert len(data["scenes"]) >= 1
    assert "silences" in data
    assert len(data["fillers"]) >= 1  # detects "um"
    assert "repeated_takes" in data
    assert len(data["visuals"]) >= 1
    assert len(data["chapters"]) >= 1
    assert data["hook"] is not None
    assert "hook" in data["hook"]
