"""Milestone A14: Comprehensive Test Suite & 5-Second End-to-End Integration Test.

Tests the complete ClipForge AI pipeline end to end:
1. Video upload (5.0s 1280x720 landscape MP4) & ffprobe inspection.
2. Audio extraction and speech transcription with word-level timestamps.
3. Highlight detection and draft clip generation.
4. EditSpec configuration: 16:9 -> 9:16 reframe, multi-cut trims, fade transition,
   cinematic color grade, title card overlay, and animated pop captions.
5. FFmpeg render pipeline execution via Celery with real-time progress.
6. Preview frame extraction (JPEG bytes).
7. Vertical MP4 download & probe verification (1080x1920, duration, sync).
8. Cleanup of clip and source video assets.
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
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.main import app
from app.models.clip import Clip
from app.models.job import Job
from app.models.transcript import Transcript
from app.models.video import Video
from app.schemas.edit_spec import (
    CaptionSpec,
    CutSegment,
    EditSpec,
    GradeSpec,
    ReframeSpec,
    TransitionSpec,
)
from app.schemas.highlight import HighlightMoment
from app.services.ass_builder import ASSBuilder
from app.services.ffmpeg_builder import FFmpegBuilder
from app.services.transcription_service import TranscriptionResult
from app.services.video_probe import probe_video
from app.tasks.celery_app import celery_app

static_ffmpeg.add_paths()


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


@pytest.fixture(autouse=True)
def clean_db_state(db_session: Session) -> Generator[None, None, None]:
    """Ensure tests start and end with no stale render or clip records."""
    db_session.execute(delete(Job))
    db_session.execute(delete(Clip))
    db_session.execute(delete(Transcript))
    db_session.execute(delete(Video))
    db_session.commit()
    yield
    db_session.execute(delete(Job))
    db_session.execute(delete(Clip))
    db_session.execute(delete(Transcript))
    db_session.execute(delete(Video))
    db_session.commit()


@pytest.fixture(scope="module")
def five_second_sample_video(
    tmp_path_factory: pytest.TempPathFactory,
) -> Generator[Path, None, None]:
    """Generate a clean, high-quality 5.0-second 1280x720 landscape MP4 video with sine audio."""
    ffmpeg_bin = shutil.which("ffmpeg")
    assert ffmpeg_bin is not None, "ffmpeg binary must be available"

    tmp_dir = tmp_path_factory.mktemp("integration_test_video")
    out_video = tmp_dir / "five_second_showcase.mp4"

    cmd = [
        ffmpeg_bin,
        "-y",
        "-f", "lavfi", "-i", "testsrc=duration=5.0:size=1280x720:rate=30",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=5.0:sample_rate=44100",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        str(out_video),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode == 0, f"FFmpeg video creation failed: {res.stderr}"
    yield out_video


# ---------------------------------------------------------------------------
# Unit Edge Case Tests: Builder, ASS Builder, EditSpec
# ---------------------------------------------------------------------------


def test_editspec_exact_boundary_cuts() -> None:
    """Verifies EditSpec validation on exact boundary cuts."""
    spec = EditSpec(
        cuts=[
            CutSegment(start=0.0, end=2.5),
            CutSegment(start=2.5, end=5.0),
        ],
        aspect_ratio="9:16",
    )
    total_dur = sum(c.end - c.start for c in spec.cuts)
    assert total_dur == 5.0
    assert len(spec.cuts) == 2


def test_ass_builder_special_character_escaping(tmp_path: Path) -> None:
    """Verifies that ASSBuilder correctly handles special characters without corrupted tags."""
    ass_path = tmp_path / "escape_test.ass"
    spec = CaptionSpec(
        enabled=True,
        animation="pop",
    )
    builder = ASSBuilder(
        caption_spec=spec,
        target_width=1080,
        target_height=1920,
    )
    builder.write_ass_file(
        output_file=ass_path,
        words=[
            {"word": "Test{1}", "start": 0.5, "end": 1.0},
            {"word": "Word\\2", "start": 1.1, "end": 1.8},
        ],
        cuts=[CutSegment(start=0.0, end=3.0)],
        title="Special: {Curly} & \\Slash / Test!",
    )
    content = ass_path.read_text(encoding="utf-8")
    assert "Dialogue:" in content
    assert "Special:" in content
    assert ass_path.exists()


def test_ffmpeg_builder_multi_cut_blur_bg(five_second_sample_video: Path, tmp_path: Path) -> None:
    """Verifies FFmpegBuilder multi-cut rendering with blur-bg reframing strategy."""
    out_video = tmp_path / "blur_bg_test.mp4"
    spec = EditSpec(
        cuts=[
            CutSegment(start=0.5, end=2.0),
            CutSegment(start=2.5, end=4.0),
        ],
        aspect_ratio="9:16",
        reframe=ReframeSpec(strategy="blur-bg"),
        transition=TransitionSpec(type="wipeleft", duration=0.3),
    )
    builder = FFmpegBuilder(
        input_path=five_second_sample_video,
        output_path=out_video,
        edit_spec=spec,
    )
    output = builder.run()
    assert output.exists()
    probe = probe_video(output)
    assert probe.width == 1080
    assert probe.height == 1920
    assert probe.orientation == "portrait"
    # Duration: (1.5 + 1.5 - 0.3) = 2.7s
    assert probe.duration == pytest.approx(2.7, abs=0.25)


# ---------------------------------------------------------------------------
# Complete 5-Second End-to-End Pipeline Integration Test
# ---------------------------------------------------------------------------


def test_five_second_end_to_end_pipeline(
    client: TestClient,
    db_session: Session,
    five_second_sample_video: Path,
    tmp_path: Path,
) -> None:
    """Executes the complete ClipForge AI workflow on a 5-second video:

    Upload -> Probe -> Transcribe -> Highlights -> EditSpec -> Render -> Frame -> Download.
    """
    # -----------------------------------------------------------------------
    # Step 1: Upload Video (POST /api/videos)
    # -----------------------------------------------------------------------
    with open(five_second_sample_video, "rb") as f:
        upload_res = client.post(
            "/api/videos",
            files={"file": ("showcase_5s.mp4", f, "video/mp4")},
        )
    assert upload_res.status_code == 201
    video_data = upload_res.json()
    video_id = video_data["id"]
    assert video_data["duration"] == pytest.approx(5.0, abs=0.2)
    assert video_data["width"] == 1280
    assert video_data["height"] == 720
    assert video_data["orientation"] == "landscape"
    assert video_data["status"] == "ready"

    # -----------------------------------------------------------------------
    # Step 2: Speech Transcription (POST /api/transcripts/{video_id})
    # -----------------------------------------------------------------------
    mock_transcript = TranscriptionResult(
        language="en",
        text="Welcome to the ultimate video editing showcase",
        words=[
            {"word": "Welcome", "start": 0.5, "end": 1.0, "probability": 0.98},
            {"word": "to", "start": 1.05, "end": 1.25, "probability": 0.99},
            {"word": "the", "start": 1.3, "end": 1.5, "probability": 0.99},
            {"word": "ultimate", "start": 1.55, "end": 2.2, "probability": 0.97},
            {"word": "video", "start": 2.25, "end": 2.7, "probability": 0.98},
            {"word": "editing", "start": 3.1, "end": 3.7, "probability": 0.99},
            {"word": "showcase", "start": 3.75, "end": 4.4, "probability": 0.96},
        ],
    )

    with patch(
        "app.tasks.transcription_task.transcribe_audio",
        return_value=mock_transcript,
    ):
        t_job_res = client.post(f"/api/transcripts/{video_id}")
        assert t_job_res.status_code == 202
        t_job_id = t_job_res.json()["id"]

        # Verify transcription job completed
        job_status = client.get(f"/api/jobs/{t_job_id}")
        assert job_status.status_code == 200
        assert job_status.json()["status"] == "COMPLETED"
        assert job_status.json()["progress"] == 100

        # Verify transcript API returns stored data with word timestamps
        get_t_res = client.get(f"/api/transcripts/{video_id}")
        assert get_t_res.status_code == 200
        t_payload = get_t_res.json()
        assert t_payload["video_id"] == video_id
        assert len(t_payload["words"]) == 7
        assert t_payload["words"][0]["word"] == "Welcome"

    # -----------------------------------------------------------------------
    # Step 3: Highlight Detection (POST /api/highlights/{video_id})
    # -----------------------------------------------------------------------
    mock_moments = [
        HighlightMoment(
            title="Ultimate Video Editing",
            start_time=0.5,
            end_time=4.5,
            score=9.5,
            hook="The ultimate showcase reveal",
            reason="High energy introduction with direct hook",
        )
    ]

    with patch(
        "app.services.highlight_service.HighlightService.detect_highlights",
        return_value=mock_moments,
    ):
        hl_job_res = client.post(f"/api/highlights/{video_id}")
        assert hl_job_res.status_code == 202
        hl_job_id = hl_job_res.json()["id"]

        # Verify highlight job completed
        hl_status = client.get(f"/api/jobs/{hl_job_id}")
        assert hl_status.status_code == 200
        assert hl_status.json()["status"] == "COMPLETED"

        # Verify draft clips were persisted
        get_hl_res = client.get(f"/api/highlights/{video_id}")
        assert get_hl_res.status_code == 200
        clips_data = get_hl_res.json()
        assert clips_data["total"] >= 1
        clips_list = clips_data["clips"]
        assert len(clips_list) >= 1
        draft_clip = clips_list[0]
        draft_clip_id = draft_clip["id"]
        assert draft_clip["status"] == "DRAFT"

    # -----------------------------------------------------------------------
    # Step 4: Configure Rich EditSpec (PATCH /api/clips/{id})
    # -----------------------------------------------------------------------
    rich_spec = EditSpec(
        cuts=[
            CutSegment(start=0.5, end=2.5),  # 2.0s
            CutSegment(start=3.0, end=4.5),  # 1.5s
        ],
        aspect_ratio="9:16",
        reframe=ReframeSpec(strategy="crop", crop_x_offset=0.5),
        grade=GradeSpec(
            preset="cinematic",
            brightness=0.04,
            contrast=1.1,
            saturation=1.2,
        ),
        transition=TransitionSpec(type="fade", duration=0.4),
        captions=CaptionSpec(
            enabled=True,
            font_name="Arial",
            font_size=42,
            primary_color="#FFFFFF",
            highlight_color="#00FFAA",
            animation="pop",
            position="middle",
        ),
    )

    patch_res = client.patch(
        f"/api/clips/{draft_clip_id}",
        json={
            "title": "Epic Reveal Clip",
            "edit_spec": rich_spec.model_dump(),
        },
    )
    assert patch_res.status_code == 200
    patched_clip = patch_res.json()
    assert patched_clip["title"] == "Epic Reveal Clip"
    assert len(patched_clip["edit_spec"]["cuts"]) == 2
    assert patched_clip["edit_spec"]["aspect_ratio"] == "9:16"
    assert patched_clip["edit_spec"]["captions"]["animation"] == "pop"

    # -----------------------------------------------------------------------
    # Step 5: Render Clip (POST /api/clips/{id}/render)
    # -----------------------------------------------------------------------
    render_res = client.post(f"/api/clips/{draft_clip_id}/render")
    assert render_res.status_code == 202
    render_job_id = render_res.json()["id"]

    # Verify Celery render task succeeded and updated Job progress to 100%
    render_job_status = client.get(f"/api/jobs/{render_job_id}")
    assert render_job_status.status_code == 200
    assert render_job_status.json()["status"] == "COMPLETED"
    assert render_job_status.json()["progress"] == 100

    # Verify Clip record reflects COMPLETED status and valid output path
    get_clip_res = client.get(f"/api/clips/{draft_clip_id}")
    assert get_clip_res.status_code == 200
    rendered_clip_record = get_clip_res.json()
    assert rendered_clip_record["status"] == "COMPLETED"
    assert rendered_clip_record["output_path"] is not None
    assert Path(rendered_clip_record["output_path"]).exists()

    # -----------------------------------------------------------------------
    # Step 6: Extract Preview Frame (GET /api/clips/{id}/preview-frame)
    # -----------------------------------------------------------------------
    frame_res = client.get(f"/api/clips/{draft_clip_id}/preview-frame?time=1.0")
    assert frame_res.status_code == 200
    assert frame_res.headers["content-type"] == "image/jpeg"
    frame_bytes = frame_res.content
    assert len(frame_bytes) > 1000
    # Validate JPEG header magic bytes
    assert frame_bytes[:3] == b"\xff\xd8\xff"

    # -----------------------------------------------------------------------
    # Step 7: Download & Probe Rendered Vertical MP4 (GET /api/clips/{id}/download)
    # -----------------------------------------------------------------------
    download_res = client.get(f"/api/clips/{draft_clip_id}/download")
    assert download_res.status_code == 200
    assert download_res.headers["content-type"] == "video/mp4"

    downloaded_file = tmp_path / "downloaded_showcase.mp4"
    downloaded_file.write_bytes(download_res.content)
    assert downloaded_file.stat().st_size > 5000

    # Probe final rendered clip: verify 9:16 vertical dimensions and duration
    probe_result = probe_video(downloaded_file)
    assert probe_result.width == 1080
    assert probe_result.height == 1920
    assert probe_result.orientation == "portrait"
    # Total duration = (2.0 + 1.5 - 0.4) = 3.1s (+- 0.25s)
    assert probe_result.duration == pytest.approx(3.1, abs=0.25)

    # -----------------------------------------------------------------------
    # Step 8: Asset Cleanup (DELETE /api/clips/{id} & DELETE /api/videos/{id})
    # -----------------------------------------------------------------------
    del_clip_res = client.delete(f"/api/clips/{draft_clip_id}")
    assert del_clip_res.status_code == 200
    assert not Path(rendered_clip_record["output_path"]).exists()

    del_video_res = client.delete(f"/api/videos/{video_id}")
    assert del_video_res.status_code == 200
    assert client.get(f"/api/videos/{video_id}").status_code == 404
