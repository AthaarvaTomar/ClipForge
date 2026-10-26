from collections.abc import Generator

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.database import SessionLocal
from app.models.timeline import TimelineOpModel, TimelineVersionModel
from app.models.video import Video
from app.schemas.timeline import Timeline
from app.services.timeline_engine import apply
from app.services.timeline_service import (
    TimelineNotFoundError,
    TimelineService,
    TimelineVersionConflictError,
)


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def sample_video(db_session: Session) -> Video:
    video = Video(
        filename="service_test.mp4",
        file_path="/tmp/service_test.mp4",
        duration=60.0,
        width=1920,
        height=1080,
        fps=30.0,
        orientation="landscape",
        status="uploaded",
    )
    db_session.add(video)
    db_session.commit()
    db_session.refresh(video)
    return video


def test_create_timeline_and_initial_snapshot(
    db_session: Session, sample_video: Video
) -> None:
    """Creating a timeline sets version=1, current_seq=0, and writes initial version snapshot."""
    created = TimelineService.create_timeline(
        db_session,
        video_id=sample_video.id,
        source_duration_ms=60000,
    )
    assert created.id is not None
    assert created.video_id == sample_video.id
    assert created.version == 1
    assert len(created.tracks) == 0

    model = TimelineService.get_timeline_model(db_session, created.id)
    assert model.current_seq == 0
    assert model.version == 1

    # Check initial snapshot
    snapshots = db_session.execute(
        select(TimelineVersionModel).where(
            TimelineVersionModel.timeline_id == created.id
        )
    ).scalars().all()
    assert len(snapshots) == 1
    assert snapshots[0].version == 1


def test_grouped_apply_and_single_step_undo(
    db_session: Session, sample_video: Video
) -> None:
    """Ops sent together share a group_id, so an agent action is one single undo step."""
    timeline = TimelineService.create_timeline(
        db_session,
        video_id=sample_video.id,
        source_duration_ms=60000,
    )

    # 1. User action: add video track (Group 1)
    user_op = {
        "type": "add_track",
        "track_id": "trk_v1",
        "track_type": "video",
        "name": "Main Video",
    }
    tl_after_user = TimelineService.apply_ops(
        db_session,
        timeline_id=timeline.id,
        ops=[user_op],
        expected_version=1,
        actor="user",
    )
    assert tl_after_user.version == 2
    assert len(tl_after_user.tracks) == 1

    # Add an item to the video track (Group 2)
    add_item_op = {
        "type": "add_item",
        "track_id": "trk_v1",
        "item": {
            "id": "item_1",
            "source": sample_video.id,
            "src_in": 0,
            "src_out": 20000,
            "start": 0,
        },
    }
    tl_with_item = TimelineService.apply_ops(
        db_session,
        timeline_id=timeline.id,
        ops=[add_item_op],
        expected_version=2,
        actor="user",
    )
    assert tl_with_item.version == 3
    assert len(tl_with_item.tracks[0].items) == 1

    # Save state before agent action for verification
    state_before_agent = tl_with_item.model_dump(mode="json")

    # 2. Agent action: multi-op batch in Group 3 (split item_1 and add caption)
    agent_ops = [
        {
            "type": "split",
            "track_id": "trk_v1",
            "item_id": "item_1",
            "split_time": 8000,
            "new_item_id": "item_1_part2",
        },
        {
            "type": "add_caption",
            "text": "Hook phrase",
            "start": 0,
            "duration_ms": 5000,
        },
    ]
    tl_after_agent = TimelineService.apply_ops(
        db_session,
        timeline_id=timeline.id,
        ops=agent_ops,
        expected_version=3,
        actor="agent",
    )
    assert tl_after_agent.version == 4
    # Video track now has 2 split items, and a new caption track was added
    assert len(tl_after_agent.tracks) == 2
    assert len(tl_after_agent.tracks[0].items) == 2

    # Check that both agent ops share the exact same group_id in DB
    ops_in_db = db_session.execute(
        select(TimelineOpModel)
        .where(TimelineOpModel.timeline_id == timeline.id)
        .order_by(TimelineOpModel.seq.asc())
    ).scalars().all()
    assert len(ops_in_db) == 4
    # Ops 3 and 4 are from agent and share group_id
    assert ops_in_db[2].group_id == ops_in_db[3].group_id
    assert ops_in_db[2].actor == "agent"
    assert ops_in_db[3].actor == "agent"

    # 3. Single UNDO step: must revert BOTH agent operations
    tl_undone = TimelineService.undo(
        db_session,
        timeline_id=timeline.id,
        expected_version=4,
    )
    assert tl_undone.version == 5
    # Video track is back to 1 un-split item, and caption track is gone
    assert len(tl_undone.tracks) == 1
    assert len(tl_undone.tracks[0].items) == 1
    assert tl_undone.tracks[0].items[0].id == "item_1"
    assert tl_undone.tracks[0].items[0].duration == 20000

    # Tracks match state_before_agent exactly
    assert tl_undone.model_dump(mode="json")["tracks"] == state_before_agent["tracks"]

    # 4. REDO step: must re-apply BOTH agent operations
    tl_redone = TimelineService.redo(
        db_session,
        timeline_id=timeline.id,
        expected_version=5,
    )
    assert tl_redone.version == 6
    assert len(tl_redone.tracks) == 2
    redone_tracks = tl_redone.model_dump(mode="json")["tracks"]
    agent_tracks = tl_after_agent.model_dump(mode="json")["tracks"]
    assert redone_tracks == agent_tracks



def test_redo_stack_cleared_on_new_op(
    db_session: Session, sample_video: Video
) -> None:
    """A new operation applied after an undo clears all subsequent ops from the redo stack."""
    timeline = TimelineService.create_timeline(
        db_session,
        video_id=sample_video.id,
        source_duration_ms=60000,
    )

    # Op 1: add track
    TimelineService.apply_ops(
        db_session,
        timeline_id=timeline.id,
        ops=[
            {
                "type": "add_track",
                "track_id": "trk_1",
                "track_type": "video",
                "name": "Track 1",
            }
        ],
        expected_version=1,
    )

    # Op 2: add item
    TimelineService.apply_ops(
        db_session,
        timeline_id=timeline.id,
        ops=[
            {
                "type": "add_item",
                "track_id": "trk_1",
                "item": {
                    "id": "it_1",
                    "source": sample_video.id,
                    "src_in": 0,
                    "src_out": 10000,
                    "start": 0,
                },
            }
        ],
        expected_version=2,
    )

    # Undo Op 2
    tl_undone = TimelineService.undo(
        db_session,
        timeline_id=timeline.id,
        expected_version=3,
    )
    assert tl_undone.version == 4
    model = TimelineService.get_timeline_model(db_session, timeline.id)
    assert model.current_seq == 1

    # Verify Op 2 is currently in redo stack (seq=2 exists in timeline_ops)
    future_ops = db_session.execute(
        select(TimelineOpModel).where(
            TimelineOpModel.timeline_id == timeline.id,
            TimelineOpModel.seq > model.current_seq,
        )
    ).scalars().all()
    assert len(future_ops) == 1

    # Now apply a NEW operation (Op 3: add audio track)
    new_op = {
        "type": "add_track",
        "track_id": "trk_audio",
        "track_type": "audio",
        "name": "Audio Track",
    }
    tl_after_new = TimelineService.apply_ops(
        db_session,
        timeline_id=timeline.id,
        ops=[new_op],
        expected_version=4,
    )
    assert tl_after_new.version == 5

    # Verify redo stack was cleared: no ops exist with seq > current_seq
    model = TimelineService.get_timeline_model(db_session, timeline.id)
    assert model.current_seq == 2
    cleared_ops = db_session.execute(
        select(TimelineOpModel).where(
            TimelineOpModel.timeline_id == timeline.id,
            TimelineOpModel.seq > model.current_seq,
        )
    ).scalars().all()
    assert len(cleared_ops) == 0

    # Calling redo does nothing because redo stack was cleared
    tl_after_redo = TimelineService.redo(
        db_session,
        timeline_id=timeline.id,
        expected_version=5,
    )
    assert tl_after_redo.version == 5  # No op reapplied, version unchanged


def test_optimistic_concurrency_409_conflict(
    db_session: Session, sample_video: Video
) -> None:
    """Mismatch in expected_version raises TimelineVersionConflictError with current version."""
    timeline = TimelineService.create_timeline(
        db_session,
        video_id=sample_video.id,
        source_duration_ms=60000,
    )
    assert timeline.version == 1

    # Attempt to apply op with wrong version (expected 99 instead of 1)
    with pytest.raises(TimelineVersionConflictError) as exc_info:
        TimelineService.apply_ops(
            db_session,
            timeline_id=timeline.id,
            ops=[{"type": "add_track", "track_id": "trk_v", "track_type": "video"}],
            expected_version=99,
        )

    err = exc_info.value
    assert err.current_version == 1
    assert err.expected_version == 99

    # Test conflict on undo
    with pytest.raises(TimelineVersionConflictError):
        TimelineService.undo(
            db_session,
            timeline_id=timeline.id,
            expected_version=42,
        )

    # Test conflict on redo
    with pytest.raises(TimelineVersionConflictError):
        TimelineService.redo(
            db_session,
            timeline_id=timeline.id,
            expected_version=42,
        )


def test_timeline_snapshots_every_n_ops(
    db_session: Session, sample_video: Video, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Snapshot is automatically created in timeline_versions every N operations."""
    # Set snapshot interval to every 2 ops for testing
    monkeypatch.setattr(settings, "TIMELINE_SNAPSHOT_INTERVAL", 2)

    timeline = TimelineService.create_timeline(
        db_session,
        video_id=sample_video.id,
        source_duration_ms=60000,
    )
    # Starts with initial snapshot at version 1
    initial_snapshots = db_session.execute(
        select(TimelineVersionModel).where(
            TimelineVersionModel.timeline_id == timeline.id
        )
    ).scalars().all()
    assert len(initial_snapshots) == 1

    # Apply 1 op (current_seq=1, no snapshot yet)
    TimelineService.apply_ops(
        db_session,
        timeline_id=timeline.id,
        ops=[{"type": "add_track", "track_id": "trk_1", "track_type": "video"}],
        expected_version=1,
    )
    snapshots_after_1 = db_session.execute(
        select(TimelineVersionModel).where(
            TimelineVersionModel.timeline_id == timeline.id
        )
    ).scalars().all()
    assert len(snapshots_after_1) == 1

    # Apply 1 more op (current_seq=2, crosses multiple of 2 -> snapshot created!)
    TimelineService.apply_ops(
        db_session,
        timeline_id=timeline.id,
        ops=[
            {
                "type": "add_item",
                "track_id": "trk_1",
                "item": {
                    "id": "it_1",
                    "source": sample_video.id,
                    "src_in": 0,
                    "src_out": 5000,
                    "start": 0,
                },
            }
        ],
        expected_version=2,
    )
    snapshots_after_2 = db_session.execute(
        select(TimelineVersionModel).where(
            TimelineVersionModel.timeline_id == timeline.id
        )
    ).scalars().all()
    assert len(snapshots_after_2) == 2
    assert snapshots_after_2[1].version == 3

    # Test restoring snapshot
    restored = TimelineService.restore_version(
        db_session,
        timeline_id=timeline.id,
        target_version=1,
        expected_version=3,
    )
    assert restored.version == 4
    assert len(restored.tracks) == 0  # Version 1 had 0 tracks


def test_timeline_state_always_matches_log(
    db_session: Session, sample_video: Video
) -> None:
    """The timeline state must always match replaying ops 1..current_seq from the database."""
    timeline = TimelineService.create_timeline(
        db_session,
        video_id=sample_video.id,
        source_duration_ms=60000,
    )

    # Perform a sequence of operations, undos, and new edits
    # 1. Add track
    TimelineService.apply_ops(
        db_session,
        timeline.id,
        [{"type": "add_track", "track_id": "t1", "track_type": "video"}],
        expected_version=1,
    )
    # 2. Add item 1
    TimelineService.apply_ops(
        db_session,
        timeline.id,
        [
            {
                "type": "add_item",
                "track_id": "t1",
                "item": {
                    "id": "i1",
                    "source": sample_video.id,
                    "src_in": 0,
                    "src_out": 10000,
                    "start": 0,
                },
            }
        ],
        expected_version=2,
    )
    # 3. Add item 2
    TimelineService.apply_ops(
        db_session,
        timeline.id,
        [
            {
                "type": "add_item",
                "track_id": "t1",
                "item": {
                    "id": "i2",
                    "source": sample_video.id,
                    "src_in": 10000,
                    "src_out": 20000,
                    "start": 10000,
                },
            }
        ],
        expected_version=3,
    )
    # 4. Undo item 2
    TimelineService.undo(db_session, timeline.id, expected_version=4)

    # 5. Add caption instead
    TimelineService.apply_ops(
        db_session,
        timeline.id,
        [{"type": "add_caption", "text": "Replay check", "start": 0, "duration_ms": 3000}],
        expected_version=5,
    )

    # Query current DB model
    model = TimelineService.get_timeline_model(db_session, timeline.id)
    current_schema = model.to_schema()

    # Replay all logged ops from 1..current_seq starting from a blank timeline
    active_ops = db_session.execute(
        select(TimelineOpModel)
        .where(
            TimelineOpModel.timeline_id == timeline.id,
            TimelineOpModel.seq <= model.current_seq,
        )
        .order_by(TimelineOpModel.seq.asc())
    ).scalars().all()

    replayed = Timeline(
        id=timeline.id,
        video_id=sample_video.id,
        version=1,
        source_duration_ms=60000,
        tracks=[],
    )
    for op_rec in active_ops:
        replayed, _ = apply(replayed, op_rec.op)

    # Tracks and items in current_schema must match the replayed log state exactly
    current_tracks = current_schema.model_dump(mode="json")["tracks"]
    replayed_tracks = replayed.model_dump(mode="json")["tracks"]
    assert current_tracks == replayed_tracks



def test_timeline_not_found_raises(db_session: Session) -> None:
    """Non-existent timeline ID raises TimelineNotFoundError."""
    with pytest.raises(TimelineNotFoundError):
        TimelineService.get_timeline_model(db_session, "non_existent_id")
