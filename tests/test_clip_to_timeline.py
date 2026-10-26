import uuid
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.main import app
from app.models.clip import Clip
from app.models.transcript import Transcript
from app.models.video import Video
from app.schemas.clip import ClipCreate
from app.schemas.edit_spec import CaptionSpec, CutSegment, EditSpec, GradeSpec, TransitionSpec
from app.schemas.timeline import TrackType
from app.services.clip_converter import ClipConverter
from app.services.timeline_service import TimelineService


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def test_video_with_transcript() -> Generator[tuple[str, str], None, None]:
    db = SessionLocal()
    video = Video(
        filename="clip_converter_test.mp4",
        file_path="storage/uploads/clip_converter_test.mp4",
        status="uploaded",
        duration=60.0,
    )
    db.add(video)
    db.commit()
    db.refresh(video)

    words = [
        {"start": 1.0, "end": 1.4, "word": "Hello"},
        {"start": 1.5, "end": 2.0, "word": "world"},
        {"start": 11.0, "end": 11.5, "word": "viral"},
        {"start": 11.6, "end": 12.2, "word": "moment"},
        {"start": 21.0, "end": 21.8, "word": "conclusion"},
    ]
    transcript = Transcript(
        video_id=video.id,
        language="en",
        text="Hello world viral moment conclusion",
        words=words,
    )
    db.add(transcript)
    db.commit()
    db.refresh(transcript)

    v_id = video.id
    t_id = transcript.id
    db.close()

    yield v_id, t_id

    db_clean = SessionLocal()
    vid = db_clean.get(Video, v_id)
    if vid:
        db_clean.delete(vid)
        db_clean.commit()
    db_clean.close()


def test_convert_single_cut_draft_clip_to_timeline(
    test_video_with_transcript: tuple[str, str],
) -> None:
    video_id, _ = test_video_with_transcript
    db = SessionLocal()
    try:
        video = db.get(Video, video_id)
        clip = Clip(
            video_id=video_id,
            title="Intro Hook",
            start_time=10.0,
            end_time=25.0,
            edit_spec={
                "cuts": [{"start": 10.0, "end": 25.0}],
                "aspect_ratio": "9:16",
                "hook": "Wait till the end",
            },
            status="DRAFT",
        )
        db.add(clip)
        db.commit()
        db.refresh(clip)

        timeline = ClipConverter.clip_to_timeline(clip, video=video)
        assert timeline.video_id == video_id
        assert timeline.source_duration_ms == 60000
        assert len(timeline.tracks) >= 1

        v_track = next(t for t in timeline.tracks if t.type == TrackType.VIDEO)
        assert len(v_track.items) == 1
        item = v_track.items[0]
        assert item.src_in == 10000
        assert item.src_out == 25000
        assert item.start == 0
        assert item.duration == 15000
        assert timeline.metadata["clip_id"] == clip.id
        assert timeline.metadata["hook"] == "Wait till the end"
    finally:
        db.close()


def test_convert_multi_cut_clip_with_grades_and_transitions(
    test_video_with_transcript: tuple[str, str],
) -> None:
    video_id, _ = test_video_with_transcript
    db = SessionLocal()
    try:
        video = db.get(Video, video_id)
        spec = EditSpec(
            cuts=[
                CutSegment(start=0.0, end=4.0),
                CutSegment(start=10.0, end=16.0),
                CutSegment(start=20.0, end=25.0),
            ],
            aspect_ratio="9:16",
            grade=GradeSpec(preset="cinematic", contrast=1.2),
            transition=TransitionSpec(type="fade", duration=0.5),
            captions=CaptionSpec(enabled=True, font_name="Montserrat"),
        )
        clip = Clip(
            video_id=video_id,
            title="Multi Cut Feature",
            start_time=0.0,
            end_time=25.0,
            edit_spec=spec.model_dump(mode="json"),
            status="DRAFT",
        )
        db.add(clip)
        db.commit()
        db.refresh(clip)

        timeline = ClipConverter.clip_to_timeline(clip, video=video)
        v_track = next(t for t in timeline.tracks if t.type == TrackType.VIDEO)
        assert len(v_track.items) == 3

        # Cut 0: 0 to 4s (duration 4000ms, start 0)
        assert v_track.items[0].start == 0
        assert v_track.items[0].src_in == 0
        assert v_track.items[0].src_out == 4000
        assert v_track.items[0].grade is not None
        assert v_track.items[0].grade.preset == "cinematic"

        # Cut 1: 10 to 16s (duration 6000ms, start 4000)
        assert v_track.items[1].start == 4000
        assert v_track.items[1].src_in == 10000
        assert v_track.items[1].src_out == 16000
        assert v_track.items[1].transition is not None
        assert v_track.items[1].transition.type == "fade"
        assert v_track.items[1].transition.duration_ms == 500

        # Cut 2: 20 to 25s (duration 5000ms, start 10000)
        assert v_track.items[2].start == 10000
        assert v_track.items[2].src_in == 20000
        assert v_track.items[2].src_out == 25000

        # Total timeline playback duration across cuts = 4000 + 6000 + 5000 = 15000ms
        assert timeline.duration == 15000
    finally:
        db.close()


def test_convert_clip_with_transcript_word_timestamps(
    test_video_with_transcript: tuple[str, str],
) -> None:
    video_id, transcript_id = test_video_with_transcript
    db = SessionLocal()
    try:
        video = db.get(Video, video_id)
        transcript = db.get(Transcript, transcript_id)

        # Cuts covering "Hello world" [0-3s] and "viral moment" [10-15s]
        spec = EditSpec(
            cuts=[
                CutSegment(start=0.0, end=3.0),
                CutSegment(start=10.0, end=15.0),
            ],
            captions=CaptionSpec(enabled=True, animation="pop"),
        )
        clip = Clip(
            video_id=video_id,
            title="Captioned Clip",
            start_time=0.0,
            end_time=15.0,
            edit_spec=spec.model_dump(mode="json"),
            status="DRAFT",
        )
        db.add(clip)
        db.commit()
        db.refresh(clip)

        timeline = ClipConverter.clip_to_timeline(clip, video=video, transcript=transcript)
        cap_track = next(t for t in timeline.tracks if t.type == TrackType.CAPTION)
        assert len(cap_track.items) >= 4  # Hello, world, viral, moment

        words_in_cap = [itm.text for itm in cap_track.items]
        assert "Hello" in words_in_cap
        assert "world" in words_in_cap
        assert "viral" in words_in_cap
        assert "moment" in words_in_cap

        # Verify no overlapping items on caption track
        for i in range(len(cap_track.items) - 1):
            assert cap_track.items[i].end <= cap_track.items[i + 1].start
    finally:
        db.close()


def test_get_clip_timeline_endpoint(
    client: TestClient,
    test_video_with_transcript: tuple[str, str],
) -> None:
    video_id, _ = test_video_with_transcript

    # 1. Create a draft clip via API
    clip_payload = ClipCreate(
        video_id=video_id,
        title="API Draft Clip",
        edit_spec=EditSpec(cuts=[CutSegment(start=5.0, end=15.0)]),
    ).model_dump(mode="json")

    create_res = client.post("/api/clips", json=clip_payload)
    assert create_res.status_code == 201
    clip_id = create_res.json()["id"]

    # 2. First call to GET /api/clips/{id}/timeline converts and returns a valid timeline
    tl_res = client.get(f"/api/clips/{clip_id}/timeline")
    assert tl_res.status_code == 200
    tl_data = tl_res.json()
    assert tl_data["video_id"] == video_id
    assert tl_data["version"] == 1
    assert len(tl_data["tracks"]) >= 1
    tl_id = tl_data["id"]

    # 3. Clip record in DB is now linked to timeline_id
    clip_res = client.get(f"/api/clips/{clip_id}")
    assert clip_res.status_code == 200
    assert clip_res.json()["timeline_id"] == tl_id

    # 4. Subsequent call to GET /api/clips/{id}/timeline returns the same linked timeline
    tl_res2 = client.get(f"/api/clips/{clip_id}/timeline")
    assert tl_res2.status_code == 200
    assert tl_res2.json()["id"] == tl_id

    # 5. Fetch directly through Timeline API: GET /api/timelines/{id}
    direct_tl = client.get(f"/api/timelines/{tl_id}")
    assert direct_tl.status_code == 200
    assert direct_tl.json()["id"] == tl_id

    # 6. Apply an operation on the opened timeline to verify full compatibility with Timeline API
    op_res = client.post(
        f"/api/timelines/{tl_id}/ops",
        json={
            "expected_version": 1,
            "actor": "user",
            "ops": [{"op": "add_track", "track_type": "audio", "name": "BGM Track"}],
        },
    )
    assert op_res.status_code == 200
    assert op_res.json()["version"] == 2
    assert any(t["name"] == "BGM Track" for t in op_res.json()["tracks"])


def test_post_clip_timeline_force_recreate(
    client: TestClient,
    test_video_with_transcript: tuple[str, str],
) -> None:
    video_id, _ = test_video_with_transcript

    # Create clip
    clip_payload = ClipCreate(
        video_id=video_id,
        title="Updatable Clip",
        edit_spec=EditSpec(cuts=[CutSegment(start=2.0, end=8.0)]),
    ).model_dump(mode="json")
    create_res = client.post("/api/clips", json=clip_payload)
    clip_id = create_res.json()["id"]

    # Open timeline v1
    tl_res1 = client.get(f"/api/clips/{clip_id}/timeline")
    assert tl_res1.status_code == 200
    tl1_id = tl_res1.json()["id"]
    item = tl_res1.json()["tracks"][0]["items"][0]
    assert item["src_out"] - item["src_in"] == 6000  # 8 - 2 = 6s

    # Update clip EditSpec with 2 cuts
    patch_res = client.patch(
        f"/api/clips/{clip_id}",
        json={
            "edit_spec": {
                "cuts": [
                    {"start": 1.0, "end": 4.0},
                    {"start": 10.0, "end": 14.0},
                ],
            },
        },
    )
    assert patch_res.status_code == 200

    # Force re-convert using POST /api/clips/{id}/timeline
    tl_res2 = client.post(f"/api/clips/{clip_id}/timeline")
    assert tl_res2.status_code == 200
    tl2_data = tl_res2.json()
    assert tl2_data["id"] != tl1_id  # Fresh timeline created
    assert len(tl2_data["tracks"][0]["items"]) == 2


def test_batch_convert_all_draft_clips(
    test_video_with_transcript: tuple[str, str],
) -> None:
    video_id, _ = test_video_with_transcript
    db = SessionLocal()
    try:
        # Create 3 unlinked draft clips
        clips = [
            Clip(
                video_id=video_id,
                title=f"Draft Clip {i}",
                start_time=float(i * 10),
                end_time=float((i + 1) * 10),
                edit_spec={"cuts": [{"start": float(i * 10), "end": float((i + 1) * 10)}]},
                status="DRAFT",
            )
            for i in range(3)
        ]
        db.add_all(clips)
        db.commit()

        # Batch convert
        timelines = TimelineService.convert_all_draft_clips(db, video_id=video_id)
        assert len(timelines) == 3

        # Verify all 3 have timeline_id populated
        for c in clips:
            db.refresh(c)
            assert c.timeline_id is not None
            tl = TimelineService.get_timeline(db, c.timeline_id)
            assert tl.video_id == video_id
            assert len(tl.tracks) >= 1
    finally:
        db.close()


def test_clip_not_found_returns_404(client: TestClient) -> None:
    res = client.get(f"/api/clips/{uuid.uuid4()}/timeline")
    assert res.status_code == 404
