import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.schemas.timeline import (
    Item,
    ItemTransition,
    Timeline,
    Track,
    TrackType,
)


def test_valid_timeline_round_trip() -> None:
    """A valid multi-track timeline should round-trip identically through JSON."""
    item_v1 = Item(
        id="item-v1",
        source="video-123",
        src_in=0,
        src_out=5000,
        start=0,
        volume=1.0,
        transition=ItemTransition(type="fade", duration_ms=500),
    )
    item_v2 = Item(
        id="item-v2",
        source="video-123",
        src_in=10000,
        src_out=18000,
        start=5000,
        volume=1.0,
    )
    track_video = Track(
        id="track-v1",
        type=TrackType.VIDEO,
        name="Main Video",
        items=[item_v1, item_v2],
    )

    item_audio = Item(
        id="item-a1",
        source="music-track",
        src_in=0,
        src_out=13000,
        start=0,
        volume=0.8,
    )
    track_audio = Track(
        id="track-a1",
        type=TrackType.AUDIO,
        name="Background Music",
        items=[item_audio],
    )

    item_caption = Item(
        id="item-c1",
        source="source",
        src_in=500,
        src_out=3000,
        start=500,
        text="Hello world captions",
    )
    track_caption = Track(
        id="track-c1",
        type=TrackType.CAPTION,
        name="Captions",
        items=[item_caption],
    )

    timeline = Timeline(
        id="tl-001",
        video_id="video-123",
        version=1,
        tracks=[track_video, track_audio, track_caption],
        source_duration_ms=30000,
        metadata={"project": "Demo Reel"},
    )

    # Validate computed properties
    assert item_v1.duration == 5000
    assert item_v1.end == 5000
    assert item_v2.duration == 8000
    assert item_v2.end == 13000
    assert timeline.duration == 13000

    # JSON serialization and round-trip
    json_str = timeline.model_dump_json()
    restored = Timeline.model_validate_json(json_str)

    assert restored.id == timeline.id
    assert restored.video_id == timeline.video_id
    assert restored.version == 1
    assert len(restored.tracks) == 3
    assert restored.tracks[0].items[0].id == "item-v1"
    assert restored.tracks[0].items[0].duration == 5000
    assert restored.duration == 13000


def test_invalid_src_in_greater_or_equal_src_out() -> None:
    """Item where src_in >= src_out must be rejected with clear message."""
    with pytest.raises(ValidationError) as exc_info:
        Item(
            id="bad-item",
            source="video-123",
            src_in=5000,
            src_out=5000,
            start=0,
        )
    assert "src_in (5000ms) must be strictly less than src_out (5000ms)" in str(exc_info.value)

    with pytest.raises(ValidationError) as exc_info2:
        Item(
            id="bad-item-2",
            source="video-123",
            src_in=6000,
            src_out=3000,
            start=0,
        )
    assert "src_in (6000ms) must be strictly less than src_out (3000ms)" in str(exc_info2.value)


def test_invalid_negative_timestamps() -> None:
    """Negative timestamps should be rejected by field constraints."""
    with pytest.raises(ValidationError):
        Item(
            id="neg-start",
            source="video-123",
            src_in=0,
            src_out=1000,
            start=-100,
        )

    with pytest.raises(ValidationError):
        Item(
            id="neg-in",
            source="video-123",
            src_in=-10,
            src_out=1000,
            start=0,
        )


def test_invalid_overlapping_items_on_track() -> None:
    """Overlapping items on the same track must be rejected with a descriptive message."""
    # Item 1: start=0, duration=3000 (0 to 3000)
    item1 = Item(
        id="item-1",
        source="video-123",
        src_in=0,
        src_out=3000,
        start=0,
    )
    # Item 2: start=2500, duration=3000 (starts before Item 1 ends!)
    item2 = Item(
        id="item-2",
        source="video-123",
        src_in=10000,
        src_out=13000,
        start=2500,
    )

    with pytest.raises(ValidationError) as exc_info:
        Track(
            id="track-overlap",
            type=TrackType.VIDEO,
            items=[item1, item2],
        )

    err_msg = str(exc_info.value)
    assert "overlapping items" in err_msg
    assert "item 'item-1' [0ms - 3000ms]" in err_msg
    assert "item 'item-2' starting at 2500ms" in err_msg


def test_adjacent_items_do_not_overlap() -> None:
    """Items where previous item ends exactly when next starts should be accepted."""
    item1 = Item(
        id="item-1",
        source="video-123",
        src_in=0,
        src_out=3000,
        start=0,
    )
    item2 = Item(
        id="item-2",
        source="video-123",
        src_in=3000,
        src_out=6000,
        start=3000,  # Exactly at 3000
    )
    track = Track(
        id="track-adjacent",
        type=TrackType.VIDEO,
        items=[item1, item2],
    )
    assert len(track.items) == 2


def test_item_exceeding_source_duration() -> None:
    """An item cutting beyond the source video's known duration must fail validation."""
    item = Item(
        id="item-exceed",
        source="video-123",
        src_in=0,
        src_out=15000,  # 15s
        start=0,
    )
    track = Track(id="track-1", type=TrackType.VIDEO, items=[item])

    with pytest.raises(ValidationError) as exc_info:
        Timeline(
            id="tl-exceed",
            video_id="video-123",
            tracks=[track],
            source_duration_ms=10000,  # Source is only 10s!
        )

    assert "src_out (15000ms) exceeds source duration (10000ms)" in str(exc_info.value)


def test_fastapi_endpoint_422_on_invalid_timeline() -> None:
    """FastAPI endpoint consuming Timeline should return HTTP 422 with structured error details."""
    app = FastAPI()

    @app.post("/test/timeline")
    def receive_timeline(tl: Timeline) -> dict[str, str]:
        return {"status": "valid", "id": tl.id}

    client = TestClient(app)

    # Valid payload
    valid_payload = {
        "id": "tl-ok",
        "video_id": "vid-1",
        "version": 1,
        "tracks": [
            {
                "id": "t1",
                "type": "video",
                "items": [
                    {
                        "id": "i1",
                        "source": "vid-1",
                        "src_in": 100,
                        "src_out": 2000,
                        "start": 0,
                    }
                ],
            }
        ],
    }
    res_ok = client.post("/test/timeline", json=valid_payload)
    assert res_ok.status_code == 200
    assert res_ok.json() == {"status": "valid", "id": "tl-ok"}

    # Invalid payload: src_in > src_out
    invalid_payload = {
        "id": "tl-bad",
        "video_id": "vid-1",
        "version": 1,
        "tracks": [
            {
                "id": "t1",
                "type": "video",
                "items": [
                    {
                        "id": "i1",
                        "source": "vid-1",
                        "src_in": 3000,
                        "src_out": 1000,
                        "start": 0,
                    }
                ],
            }
        ],
    }
    res_bad = client.post("/test/timeline", json=invalid_payload)
    assert res_bad.status_code == 422
    err_json = res_bad.json()
    assert "detail" in err_json
    error_str = str(err_json["detail"])
    assert "src_in (3000ms) must be strictly less than src_out (1000ms)" in error_str
