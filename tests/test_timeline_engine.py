import pytest

from app.schemas.timeline import Item, Timeline, Track, TrackType
from app.services.timeline_engine import TimelineOperationError, apply


@pytest.fixture
def sample_timeline() -> Timeline:
    """Fixture providing a base 3-track timeline for operation tests."""
    item1 = Item(
        id="item_v1",
        source="video_source",
        src_in=0,
        src_out=10000,
        start=0,
        volume=1.0,
    )
    item2 = Item(
        id="item_v2",
        source="video_source",
        src_in=10000,
        src_out=25000,
        start=10000,
        volume=1.0,
    )
    track_v = Track(
        id="trk_video",
        type=TrackType.VIDEO,
        name="Main Video",
        items=[item1, item2],
    )
    track_a = Track(
        id="trk_audio",
        type=TrackType.AUDIO,
        name="Music",
        items=[
            Item(
                id="item_a1",
                source="music_source",
                src_in=0,
                src_out=25000,
                start=0,
                volume=0.8,
            )
        ],
    )
    return Timeline(
        id="tl_test",
        video_id="video_source",
        version=1,
        source_duration_ms=60000,
        tracks=[track_v, track_a],
    )


def test_immutability(sample_timeline: Timeline) -> None:
    """The original timeline object must remain completely unmodified after applying an op."""
    original_dict = sample_timeline.model_dump(mode="json")
    new_tl, _ = apply(
        sample_timeline,
        {
            "type": "trim",
            "track_id": "trk_video",
            "item_id": "item_v1",
            "new_src_out": 5000,
        },
    )
    assert sample_timeline.model_dump(mode="json") == original_dict
    assert new_tl.tracks[0].items[0].src_out == 5000
    assert sample_timeline.tracks[0].items[0].src_out == 10000


def test_add_track_and_inverse(sample_timeline: Timeline) -> None:
    """add_track adds a track; inverse remove_track restores the original timeline."""
    op = {
        "type": "add_track",
        "track_id": "trk_overlay",
        "track_type": "overlay",
        "name": "B-Roll Overlay",
    }
    new_tl, inv_op = apply(sample_timeline, op)
    assert len(new_tl.tracks) == 3
    assert new_tl.tracks[-1].id == "trk_overlay"
    assert new_tl.tracks[-1].type == TrackType.OVERLAY

    # Apply inverse
    restored_tl, _ = apply(new_tl, inv_op)
    assert restored_tl == sample_timeline


def test_remove_track_and_inverse(sample_timeline: Timeline) -> None:
    """remove_track removes a track; inverse add_track restores the track and all items."""
    op = {"type": "remove_track", "track_id": "trk_audio"}
    new_tl, inv_op = apply(sample_timeline, op)
    assert len(new_tl.tracks) == 1
    assert new_tl.tracks[0].id == "trk_video"

    # Apply inverse
    restored_tl, _ = apply(new_tl, inv_op)
    assert restored_tl == sample_timeline


def test_add_item_and_inverse(sample_timeline: Timeline) -> None:
    """add_item places an item onto a track; inverse remove_item removes it."""
    new_item = {
        "id": "item_v3",
        "source": "video_source",
        "src_in": 30000,
        "src_out": 40000,
        "start": 26000,
    }
    op = {
        "type": "add_item",
        "track_id": "trk_video",
        "item": new_item,
    }
    new_tl, inv_op = apply(sample_timeline, op)
    assert len(new_tl.tracks[0].items) == 3
    assert new_tl.tracks[0].items[-1].id == "item_v3"

    # Apply inverse
    restored_tl, _ = apply(new_tl, inv_op)
    assert restored_tl == sample_timeline


def test_remove_item_and_inverse(sample_timeline: Timeline) -> None:
    """remove_item removes an item; inverse add_item restores it."""
    op = {
        "type": "remove_item",
        "track_id": "trk_video",
        "item_id": "item_v2",
    }
    new_tl, inv_op = apply(sample_timeline, op)
    assert len(new_tl.tracks[0].items) == 1
    assert new_tl.tracks[0].items[0].id == "item_v1"

    # Apply inverse
    restored_tl, _ = apply(new_tl, inv_op)
    assert restored_tl == sample_timeline


def test_split_and_inverse(sample_timeline: Timeline) -> None:
    """split slices an item into two pieces; inverse merge joins them back exactly."""
    # Split item_v1 [0 - 10000ms] at 4000ms
    op = {
        "type": "split",
        "track_id": "trk_video",
        "item_id": "item_v1",
        "split_time": 4000,
        "new_item_id": "item_v1_right",
    }
    new_tl, inv_op = apply(sample_timeline, op)
    video_track = new_tl.tracks[0]
    assert len(video_track.items) == 3

    left = video_track.items[0]
    right = video_track.items[1]
    assert left.id == "item_v1"
    assert left.start == 0
    assert left.src_in == 0
    assert left.src_out == 4000
    assert left.duration == 4000

    assert right.id == "item_v1_right"
    assert right.start == 4000
    assert right.src_in == 4000
    assert right.src_out == 10000
    assert right.duration == 6000

    # Apply inverse (merge)
    restored_tl, _ = apply(new_tl, inv_op)
    assert restored_tl == sample_timeline


def test_trim_and_inverse(sample_timeline: Timeline) -> None:
    """trim modifies src_in, src_out, and start; inverse restores original values."""
    op = {
        "type": "trim",
        "track_id": "trk_video",
        "item_id": "item_v1",
        "new_src_in": 1000,
        "new_src_out": 8000,
        "new_start": 500,
    }
    new_tl, inv_op = apply(sample_timeline, op)
    trimmed = new_tl.tracks[0].items[0]
    assert trimmed.src_in == 1000
    assert trimmed.src_out == 8000
    assert trimmed.start == 500
    assert trimmed.duration == 7000

    # Apply inverse
    restored_tl, _ = apply(new_tl, inv_op)
    assert restored_tl == sample_timeline


def test_move_and_inverse(sample_timeline: Timeline) -> None:
    """move relocates an item across tracks or time; inverse restores track and start."""
    # Move item_a1 from trk_audio to a new position on trk_audio
    op = {
        "type": "move",
        "item_id": "item_a1",
        "from_track_id": "trk_audio",
        "to_track_id": "trk_audio",
        "new_start": 5000,
    }
    new_tl, inv_op = apply(sample_timeline, op)
    assert new_tl.tracks[1].items[0].start == 5000

    # Apply inverse
    restored_tl, _ = apply(new_tl, inv_op)
    assert restored_tl == sample_timeline


def test_ripple_delete_and_inverse(sample_timeline: Timeline) -> None:
    """ripple_delete deletes an item and shifts subsequent items left; inverse restores them."""
    # Track currently has: item_v1 [0 - 10000], item_v2 [10000 - 25000]
    op = {
        "type": "ripple_delete",
        "track_id": "trk_video",
        "item_id": "item_v1",
    }
    new_tl, inv_op = apply(sample_timeline, op)
    assert len(new_tl.tracks[0].items) == 1
    # item_v2 was at 10000, should have shifted left by item_v1's duration (10000ms) to start at 0
    shifted = new_tl.tracks[0].items[0]
    assert shifted.id == "item_v2"
    assert shifted.start == 0

    # Apply inverse (ripple_insert)
    restored_tl, _ = apply(new_tl, inv_op)
    assert restored_tl == sample_timeline


def test_set_volume_and_inverse(sample_timeline: Timeline) -> None:
    """set_volume changes item volume; inverse restores old volume."""
    op = {
        "type": "set_volume",
        "track_id": "trk_audio",
        "item_id": "item_a1",
        "volume": 0.35,
    }
    new_tl, inv_op = apply(sample_timeline, op)
    assert new_tl.tracks[1].items[0].volume == 0.35

    # Apply inverse
    restored_tl, _ = apply(new_tl, inv_op)
    assert restored_tl == sample_timeline


def test_set_grade_and_inverse(sample_timeline: Timeline) -> None:
    """set_grade updates color grade; inverse restores previous grade."""
    grade_data = {
        "preset": "cinematic",
        "brightness": 0.1,
        "contrast": 1.2,
        "saturation": 1.1,
    }
    op = {
        "type": "set_grade",
        "track_id": "trk_video",
        "item_id": "item_v1",
        "grade": grade_data,
    }
    new_tl, inv_op = apply(sample_timeline, op)
    assert new_tl.tracks[0].items[0].grade is not None
    assert new_tl.tracks[0].items[0].grade.preset == "cinematic"

    # Apply inverse
    restored_tl, _ = apply(new_tl, inv_op)
    assert restored_tl == sample_timeline


def test_set_transition_and_inverse(sample_timeline: Timeline) -> None:
    """set_transition updates transition; inverse restores previous transition."""
    trans_data = {"type": "fade", "duration_ms": 750}
    op = {
        "type": "set_transition",
        "track_id": "trk_video",
        "item_id": "item_v2",
        "transition": trans_data,
    }
    new_tl, inv_op = apply(sample_timeline, op)
    assert new_tl.tracks[0].items[1].transition is not None
    assert new_tl.tracks[0].items[1].transition.type == "fade"
    assert new_tl.tracks[0].items[1].transition.duration_ms == 750

    # Apply inverse
    restored_tl, _ = apply(new_tl, inv_op)
    assert restored_tl == sample_timeline


def test_add_caption_and_inverse(sample_timeline: Timeline) -> None:
    """add_caption creates a caption item and track; inverse restores."""
    op = {
        "type": "add_caption",
        "text": "Welcome to ClipForge AI!",
        "start": 500,
        "duration_ms": 2500,
    }
    new_tl, inv_op = apply(sample_timeline, op)
    assert len(new_tl.tracks) == 3
    caption_track = next(t for t in new_tl.tracks if t.type == TrackType.CAPTION)
    assert len(caption_track.items) == 1
    assert caption_track.items[0].text == "Welcome to ClipForge AI!"
    assert caption_track.items[0].start == 500
    assert caption_track.items[0].duration == 2500

    # Apply inverse
    restored_tl, _ = apply(new_tl, inv_op)
    assert restored_tl == sample_timeline


def test_update_caption_and_inverse(sample_timeline: Timeline) -> None:
    """update_caption alters text and timing; inverse restores original caption."""
    # First add a caption track and item
    cap_track = Track(
        id="trk_cap",
        type=TrackType.CAPTION,
        name="Captions",
        items=[
            Item(
                id="cap_1",
                source="caption",
                src_in=0,
                src_out=3000,
                start=0,
                text="Initial text",
            )
        ],
    )
    sample_timeline.tracks.append(cap_track)

    op = {
        "type": "update_caption",
        "track_id": "trk_cap",
        "item_id": "cap_1",
        "text": "Updated speech text",
        "duration_ms": 4500,
    }
    new_tl, inv_op = apply(sample_timeline, op)
    updated = new_tl.tracks[-1].items[0]
    assert updated.text == "Updated speech text"
    assert updated.duration == 4500

    # Apply inverse
    restored_tl, _ = apply(new_tl, inv_op)
    assert restored_tl == sample_timeline


def test_error_cases(sample_timeline: Timeline) -> None:
    """Verify that invalid operations raise TimelineOperationError with informative messages."""
    # 1. Missing type
    with pytest.raises(TimelineOperationError, match="missing required 'type'"):
        apply(sample_timeline, {})

    # 2. Unknown op type
    with pytest.raises(TimelineOperationError, match="Unknown operation type"):
        apply(sample_timeline, {"type": "nonexistent_op"})

    # 3. Track not found
    with pytest.raises(TimelineOperationError, match="Track 'missing_trk' not found"):
        apply(sample_timeline, {"type": "remove_track", "track_id": "missing_trk"})

    # 4. Item not found
    with pytest.raises(TimelineOperationError, match="Item 'missing_item' not found"):
        apply(
            sample_timeline,
            {
                "type": "remove_item",
                "track_id": "trk_video",
                "item_id": "missing_item",
            },
        )

    # 5. Invalid split time (outside item range)
    with pytest.raises(TimelineOperationError, match="strictly between"):
        apply(
            sample_timeline,
            {
                "type": "split",
                "track_id": "trk_video",
                "item_id": "item_v1",
                "split_time": 15000,  # item_v1 is [0 - 10000ms]
            },
        )

    # 6. Trim resulting in src_in >= src_out
    with pytest.raises(TimelineOperationError, match="strictly less"):
        apply(
            sample_timeline,
            {
                "type": "trim",
                "track_id": "trk_video",
                "item_id": "item_v1",
                "new_src_in": 8000,
                "new_src_out": 5000,
            },
        )

    # 7. Move causing overlap
    with pytest.raises(TimelineOperationError, match="overlapping items"):
        apply(
            sample_timeline,
            {
                "type": "move",
                "item_id": "item_v2",
                "from_track_id": "trk_video",
                "to_track_id": "trk_video",
                "new_start": 5000,  # item_v1 is [0 - 10000ms], overlaps!
            },
        )
