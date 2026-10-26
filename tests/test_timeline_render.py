"""Tests for Milestones R3 (Render task, progress, cancel) and R4 (Preview frame)."""

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
from app.models.timeline import TimelineModel, TimelineVersionModel
from app.models.video import Video
from app.schemas.edit_spec import GradeSpec
from app.schemas.timeline import Item, Timeline, Track, TrackType
from app.services.job_service import JobService
from app.services.timeline_service import TimelineService
from app.services.video_probe import probe_video
from app.tasks.celery_app import celery_app
from app.tasks.timeline_render_task import render_timeline_task


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

    tmp_dir = tmp_path_factory.mktemp("timeline_render_video")
    out_video = tmp_dir / "sample_video.mp4"

    cmd = [
        ffmpeg_bin, "-y",
        "-f", "lavfi", "-i", "testsrc=duration=3.0:size=1280x720:rate=30",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=3.0:sample_rate=44100",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        str(out_video),
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    yield out_video


def test_render_timeline_task_active_and_pinned_version(
    db_session: Session, sample_video: Path
) -> None:
    # 1. Setup Video
    video = Video(
        filename="timeline_src.mp4",
        file_path=str(sample_video),
        duration=3.0,
        width=1280,
        height=720,
        fps=30.0,
        orientation="landscape",
        status="ready",
    )
    db_session.add(video)
    db_session.commit()
    db_session.refresh(video)

    # 2. Setup Timeline Version 1 (1.0s cut)
    item_v1 = Item(
        id="it_v1",
        source=video.id,
        src_in=0,
        src_out=1000,
        start=0,
        volume=1.0,
    )
    track_v1 = Track(
        id="trk_v1",
        type=TrackType.VIDEO,
        items=[item_v1],
    )
    tl_id = f"tl_pinned_{uuid.uuid4().hex[:8]}"
    tl_schema_v1 = Timeline(
        id=tl_id,
        video_id=video.id,
        version=1,
        tracks=[track_v1],
        metadata={"aspect_ratio": "9:16"},
    )
    tl_model = TimelineModel(
        id=tl_schema_v1.id,
        video_id=video.id,
        version=1,
        current_seq=0,
        data=tl_schema_v1.model_dump(mode="json"),
    )
    db_session.add(tl_model)
    v1_snapshot = TimelineVersionModel(
        timeline_id=tl_schema_v1.id,
        version=1,
        snapshot=tl_schema_v1.model_dump(mode="json"),
    )
    db_session.add(v1_snapshot)
    db_session.commit()

    # 3. Apply op to bump to Version 2 (extend cut to 2.0s)
    trim_op = {
        "type": "trim",
        "track_id": "trk_v1",
        "item_id": "it_v1",
        "new_src_out": 2000,
    }
    TimelineService.apply_ops(
        db=db_session,
        timeline_id=tl_schema_v1.id,
        ops=[trim_op],
        expected_version=1,
    )

    # 4. Render pinned Version 1
    job_v1 = JobService.create_job(
        db=db_session,
        job_type="TIMELINE_RENDER",
        video_id=video.id,
    )
    res_v1 = render_timeline_task(
        job_id=job_v1.id,
        timeline_id=tl_schema_v1.id,
        version=1,
    )
    assert res_v1["version"] == 1
    p1 = Path(res_v1["output_path"])
    assert p1.is_file()
    meta1 = probe_video(p1)
    assert 0.9 <= meta1.duration <= 1.2

    # 5. Render active Version 2 (without specifying version)
    job_v2 = JobService.create_job(
        db=db_session,
        job_type="TIMELINE_RENDER",
        video_id=video.id,
    )
    res_v2 = render_timeline_task(
        job_id=job_v2.id,
        timeline_id=tl_schema_v1.id,
        version=None,
    )
    assert res_v2["version"] == 2
    p2 = Path(res_v2["output_path"])
    assert p2.is_file()
    meta2 = probe_video(p2)
    assert 1.8 <= meta2.duration <= 2.2


def test_api_timeline_render_download_and_cancel_flow(
    client: TestClient, db_session: Session, sample_video: Path
) -> None:
    # 1. Setup Video & Timeline
    video = Video(
        filename="api_tl_test.mp4",
        file_path=str(sample_video),
        duration=3.0,
        width=1280,
        height=720,
        fps=30.0,
        orientation="landscape",
        status="ready",
    )
    db_session.add(video)
    db_session.commit()
    db_session.refresh(video)

    item = Item(
        id="it_api",
        source=video.id,
        src_in=0,
        src_out=1500,
        start=0,
    )
    track = Track(
        id="trk_api",
        type=TrackType.VIDEO,
        items=[item],
    )
    tl = TimelineService.create_timeline(
        db=db_session,
        video_id=video.id,
        tracks=[track],
        metadata={"aspect_ratio": "9:16"},
    )

    # 2. Trigger render via POST /api/timelines/{id}/render
    render_res = client.post(f"/api/timelines/{tl.id}/render")
    assert render_res.status_code == 202
    job_data = render_res.json()
    assert job_data["job_type"] == "TIMELINE_RENDER"
    job_id = job_data["id"]

    # Verify job completed in DB (celery eager)
    job_record = JobService.get_job(db_session, job_id)
    assert job_record is not None
    assert job_record.status == "COMPLETED"

    # 3. Download rendered timeline via GET /api/timelines/{id}/download
    download_res = client.get(f"/api/timelines/{tl.id}/download")
    assert download_res.status_code == 200
    assert download_res.headers["content-type"] == "video/mp4"
    assert len(download_res.content) > 0

    # 4. Cancel endpoint test
    cancel_res = client.post(f"/api/timelines/{tl.id}/cancel?job_id={job_id}")
    assert cancel_res.status_code == 200
    assert cancel_res.json()["ok"] is True


def test_api_preview_frame_changes_with_grade(
    client: TestClient, db_session: Session, sample_video: Path
) -> None:
    """Task R4 verification: changing a grade changes the returned preview frame."""
    video = Video(
        filename="frame_test.mp4",
        file_path=str(sample_video),
        duration=3.0,
        width=1280,
        height=720,
        fps=30.0,
        orientation="landscape",
        status="ready",
    )
    db_session.add(video)
    db_session.commit()
    db_session.refresh(video)

    item = Item(
        id="it_frame",
        source=video.id,
        src_in=0,
        src_out=2000,
        start=0,
        grade=GradeSpec(preset="none"),
    )
    track = Track(
        id="trk_frame",
        type=TrackType.VIDEO,
        items=[item],
    )
    tl = TimelineService.create_timeline(
        db=db_session,
        video_id=video.id,
        tracks=[track],
        metadata={"aspect_ratio": "9:16"},
    )

    # 1. Fetch frame at t=0.5s with grade="none"
    res_normal = client.get(f"/api/timelines/{tl.id}/frame?t=0.5")
    assert res_normal.status_code == 200
    assert res_normal.headers["content-type"] == "image/jpeg"
    frame_normal = res_normal.content
    assert len(frame_normal) > 0
    assert frame_normal.startswith(b"\xff\xd8")

    # 2. Update item grade to black-and-white ("bw") via set_grade op
    grade_op = {
        "type": "set_grade",
        "track_id": "trk_frame",
        "item_id": "it_frame",
        "grade": {"preset": "bw"},
    }
    client.post(
        f"/api/timelines/{tl.id}/ops",
        json={"expected_version": 1, "ops": [grade_op]},
    )

    # 3. Fetch frame again at t=0.5s with grade="bw"
    res_graded = client.get(f"/api/timelines/{tl.id}/frame?t=0.5")
    assert res_graded.status_code == 200
    assert res_graded.headers["content-type"] == "image/jpeg"
    frame_graded = res_graded.content
    assert len(frame_graded) > 0
    assert frame_graded.startswith(b"\xff\xd8")

    # 4. Verify that changing the grade changed the returned frame bytes!
    assert frame_normal != frame_graded
