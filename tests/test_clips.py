from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.database import SessionLocal
from app.main import app
from app.models.video import Video
from app.schemas.edit_spec import (
    CaptionSpec,
    CutSegment,
    EditSpec,
    GradeSpec,
    ReframeSpec,
    TransitionSpec,
)


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def test_video_id() -> Generator[str, None, None]:
    db = SessionLocal()
    video = Video(
        filename="test_clips.mp4",
        file_path="storage/uploads/test_clips.mp4",
        status="uploaded",
        duration=120.0,
    )
    db.add(video)
    db.commit()
    db.refresh(video)
    vid_id = video.id
    db.close()

    yield vid_id

    # Cleanup
    db_clean = SessionLocal()
    vid = db_clean.get(Video, vid_id)
    if vid:
        db_clean.delete(vid)
        db_clean.commit()
    db_clean.close()


# ---------------------------------------------------------------------------
# Unit tests for EditSpec Pydantic validation
# ---------------------------------------------------------------------------


def test_editspec_valid() -> None:
    spec = EditSpec(
        cuts=[
            CutSegment(start=5.0, end=15.0),
            CutSegment(start=20.0, end=35.0),
        ],
        aspect_ratio="9:16",
        reframe=ReframeSpec(strategy="crop", crop_x_offset=0.2),
        captions=CaptionSpec(
            enabled=True,
            style="bold-highlight",
            font_size=42,
            primary_color="#FFFFFF",
            highlight_color="#FFFF00",
            animation="pop",
            position="bottom",
        ),
        grade=GradeSpec(preset="cinematic", brightness=0.05, contrast=1.2),
        transition=TransitionSpec(type="fade", duration=0.4),
        hook="Wait until you hear this!",
        reason="High engagement opening",
        score=9.4,
    )

    assert len(spec.cuts) == 2
    assert spec.aspect_ratio == "9:16"
    assert spec.total_duration == (15.0 - 5.0) + (35.0 - 20.0)  # 25.0s
    assert spec.captions.highlight_color == "#FFFF00"
    assert spec.grade.preset == "cinematic"


def test_editspec_empty_cuts_rejected() -> None:
    with pytest.raises(ValidationError) as exc:
        EditSpec(cuts=[])
    err_msg = str(exc.value).lower()
    assert "at least 1 item" in err_msg or "at least one cut" in err_msg


def test_cutsegment_end_before_start_rejected() -> None:
    with pytest.raises(ValidationError) as exc:
        CutSegment(start=10.0, end=8.0)
    assert "greater than start time" in str(exc.value).lower()


def test_cutsegment_end_equal_start_rejected() -> None:
    with pytest.raises(ValidationError) as exc:
        CutSegment(start=10.0, end=10.0)
    assert "greater than start time" in str(exc.value).lower()


def test_editspec_overlapping_cuts_rejected() -> None:
    with pytest.raises(ValidationError) as exc:
        EditSpec(
            cuts=[
                CutSegment(start=5.0, end=20.0),
                CutSegment(start=15.0, end=30.0),  # starts before previous ends
            ]
        )
    assert "overlaps" in str(exc.value).lower()


def test_editspec_out_of_order_cuts_rejected() -> None:
    with pytest.raises(ValidationError) as exc:
        EditSpec(
            cuts=[
                CutSegment(start=30.0, end=40.0),
                CutSegment(start=10.0, end=20.0),
            ]
        )
    assert "overlaps" in str(exc.value).lower() or "chronological" in str(exc.value).lower()


def test_editspec_invalid_hex_color() -> None:
    with pytest.raises(ValidationError):
        CaptionSpec(primary_color="not-a-color")


def test_editspec_invalid_aspect_ratio() -> None:
    with pytest.raises(ValidationError):
        EditSpec(
            cuts=[CutSegment(start=0.0, end=10.0)],
            aspect_ratio="21:9",  # type: ignore[arg-type]
        )


# ---------------------------------------------------------------------------
# API Endpoints CRUD Integration Tests
# ---------------------------------------------------------------------------


def test_create_clip_success(client: TestClient, test_video_id: str) -> None:
    payload = {
        "video_id": test_video_id,
        "title": "Viral Hook Moment",
        "edit_spec": {
            "cuts": [
                {"start": 10.0, "end": 25.0},
                {"start": 30.0, "end": 45.0},
            ],
            "aspect_ratio": "9:16",
            "captions": {
                "enabled": True,
                "style": "clean",
                "font_size": 36,
                "highlight_color": "#00FFCC",
            },
            "hook": "Here is the real truth",
            "score": 9.1,
        },
    }

    resp = client.post("/api/clips", json=payload)
    assert resp.status_code == 201
    data = resp.json()

    assert data["id"] is not None
    assert data["video_id"] == test_video_id
    assert data["title"] == "Viral Hook Moment"
    assert data["start_time"] == 10.0
    assert data["end_time"] == 45.0
    assert data["status"] == "DRAFT"
    assert len(data["edit_spec"]["cuts"]) == 2


def test_create_clip_video_not_found(client: TestClient) -> None:
    payload = {
        "video_id": "00000000-0000-0000-0000-000000000000",
        "title": "Ghost Clip",
        "edit_spec": {
            "cuts": [{"start": 0.0, "end": 10.0}],
        },
    }
    resp = client.post("/api/clips", json=payload)
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


def test_create_clip_invalid_cut_exceeds_video_duration(
    client: TestClient, test_video_id: str
) -> None:
    # Video duration is 120s
    payload = {
        "video_id": test_video_id,
        "title": "Exceeding Duration",
        "edit_spec": {
            "cuts": [{"start": 100.0, "end": 150.0}],
        },
    }
    resp = client.post("/api/clips", json=payload)
    assert resp.status_code == 422
    assert "exceeds video duration" in resp.json()["detail"].lower()


def test_create_clip_invalid_spec_returns_422(client: TestClient, test_video_id: str) -> None:
    # Cut end before start
    payload = {
        "video_id": test_video_id,
        "title": "Backwards Cut",
        "edit_spec": {
            "cuts": [{"start": 20.0, "end": 10.0}],
        },
    }
    resp = client.post("/api/clips", json=payload)
    assert resp.status_code == 422


def test_get_and_list_clips(client: TestClient, test_video_id: str) -> None:
    # 1. Create two clips
    clip1_resp = client.post(
        "/api/clips",
        json={
            "video_id": test_video_id,
            "title": "List Clip 1",
            "edit_spec": {"cuts": [{"start": 5.0, "end": 15.0}]},
        },
    )
    assert clip1_resp.status_code == 201
    clip1_id = clip1_resp.json()["id"]

    clip2_resp = client.post(
        "/api/clips",
        json={
            "video_id": test_video_id,
            "title": "List Clip 2",
            "edit_spec": {"cuts": [{"start": 25.0, "end": 40.0}]},
        },
    )
    assert clip2_resp.status_code == 201
    clip2_id = clip2_resp.json()["id"]

    # 2. Get single clip by ID
    get_resp = client.get(f"/api/clips/{clip1_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == clip1_id
    assert get_resp.json()["title"] == "List Clip 1"

    # 3. List all clips filtered by video_id
    list_resp = client.get(f"/api/clips?video_id={test_video_id}")
    assert list_resp.status_code == 200
    list_data = list_resp.json()
    assert list_data["total"] >= 2
    clip_ids = [c["id"] for c in list_data["clips"]]
    assert clip1_id in clip_ids
    assert clip2_id in clip_ids


def test_patch_clip_updates(client: TestClient, test_video_id: str) -> None:
    # Create initial clip
    init_resp = client.post(
        "/api/clips",
        json={
            "video_id": test_video_id,
            "title": "Original Title",
            "edit_spec": {
                "cuts": [{"start": 10.0, "end": 20.0}],
                "aspect_ratio": "9:16",
            },
        },
    )
    clip_id = init_resp.json()["id"]

    # Update title and EditSpec
    patch_resp = client.patch(
        f"/api/clips/{clip_id}",
        json={
            "title": "Updated Title After Review",
            "edit_spec": {
                "cuts": [
                    {"start": 12.0, "end": 22.0},
                    {"start": 25.0, "end": 35.0},
                ],
                "aspect_ratio": "1:1",
                "grade": {"preset": "warm", "saturation": 1.2},
            },
            "status": "QUEUED",
        },
    )
    assert patch_resp.status_code == 200
    updated_data = patch_resp.json()
    assert updated_data["title"] == "Updated Title After Review"
    assert updated_data["start_time"] == 12.0
    assert updated_data["end_time"] == 35.0
    assert updated_data["status"] == "QUEUED"
    assert updated_data["edit_spec"]["aspect_ratio"] == "1:1"
    assert updated_data["edit_spec"]["grade"]["preset"] == "warm"


def test_patch_clip_invalid_times_rejected(client: TestClient, test_video_id: str) -> None:
    init_resp = client.post(
        "/api/clips",
        json={
            "video_id": test_video_id,
            "title": "Time Test Clip",
            "edit_spec": {"cuts": [{"start": 10.0, "end": 20.0}]},
        },
    )
    clip_id = init_resp.json()["id"]

    # End time before start time
    patch_resp = client.patch(
        f"/api/clips/{clip_id}",
        json={"start_time": 30.0, "end_time": 25.0},
    )
    assert patch_resp.status_code == 422


def test_delete_clip(client: TestClient, test_video_id: str) -> None:
    create_resp = client.post(
        "/api/clips",
        json={
            "video_id": test_video_id,
            "title": "Clip To Delete",
            "edit_spec": {"cuts": [{"start": 5.0, "end": 15.0}]},
        },
    )
    clip_id = create_resp.json()["id"]

    # Delete
    del_resp = client.delete(f"/api/clips/{clip_id}")
    assert del_resp.status_code == 200
    assert del_resp.json()["ok"] is True

    # Confirm 404
    get_resp = client.get(f"/api/clips/{clip_id}")
    assert get_resp.status_code == 404

    # Second delete returns 404
    del_again_resp = client.delete(f"/api/clips/{clip_id}")
    assert del_again_resp.status_code == 404
