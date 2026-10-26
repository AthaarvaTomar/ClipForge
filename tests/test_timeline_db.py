import uuid
from collections.abc import Generator

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import SessionLocal, engine
from app.models import TimelineModel, TimelineOpModel, TimelineVersionModel, Video
from app.schemas.timeline import Item, Timeline, Track, TrackType


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def test_timeline_tables_exist() -> None:
    """Verify that timelines, timeline_ops, and timeline_versions tables exist."""
    inspector = inspect(engine)
    table_names = inspector.get_table_names()
    assert "timelines" in table_names
    assert "timeline_ops" in table_names
    assert "timeline_versions" in table_names


def test_timeline_crud_and_schema_integration(db_session: Session) -> None:
    """Verify timeline creation, reading, and relationship to Video."""
    video = Video(
        filename="interview.mp4",
        file_path="/tmp/interview.mp4",
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

    # Build Pydantic timeline
    pydantic_timeline = Timeline(
        id=str(uuid.uuid4()),
        video_id=video.id,
        version=0,
        source_duration_ms=60000,
        tracks=[
            Track(
                id="trk_v1",
                name="Main Video",
                type=TrackType.VIDEO,
                items=[
                    Item(
                        id="itm_v1",
                        source=video.id,
                        src_in=0,
                        src_out=15000,
                        start=0,
                    )
                ],
            )
        ],
    )

    # Create DB record
    timeline_row = TimelineModel(
        id=pydantic_timeline.id,
        video_id=pydantic_timeline.video_id,
        version=pydantic_timeline.version,
        source_duration_ms=pydantic_timeline.source_duration_ms,
        data=pydantic_timeline.model_dump(mode="json"),
    )
    db_session.add(timeline_row)
    db_session.commit()
    db_session.refresh(timeline_row)

    assert timeline_row.id == pydantic_timeline.id
    assert timeline_row.video_id == video.id
    assert timeline_row.version == 0
    assert timeline_row.source_duration_ms == 60000
    assert timeline_row.created_at is not None
    assert timeline_row.updated_at is not None

    # Read back and rehydrate Pydantic model
    rehydrated = Timeline.model_validate(timeline_row.data)
    assert rehydrated.id == pydantic_timeline.id
    assert len(rehydrated.tracks) == 1
    assert rehydrated.tracks[0].items[0].duration == 15000


def test_timeline_ops_and_grouping(db_session: Session) -> None:
    """Verify timeline_ops logging, actor types, ordering, and unique constraint."""
    video = Video(
        filename="test_ops.mp4",
        file_path="/tmp/test_ops.mp4",
        duration=30.0,
        status="uploaded",
    )
    db_session.add(video)
    db_session.commit()

    timeline_row = TimelineModel(
        id=str(uuid.uuid4()),
        video_id=video.id,
        version=2,
        data={"id": "dummy", "tracks": []},
    )
    db_session.add(timeline_row)
    db_session.commit()

    group_id = str(uuid.uuid4())

    op1 = TimelineOpModel(
        timeline_id=timeline_row.id,
        seq=1,
        group_id=group_id,
        op={"type": "add_track", "track_id": "trk_1"},
        inverse_op={"type": "remove_track", "track_id": "trk_1"},
        actor="user",
    )
    op2 = TimelineOpModel(
        timeline_id=timeline_row.id,
        seq=2,
        group_id=group_id,
        op={"type": "add_item", "track_id": "trk_1", "item_id": "itm_1"},
        inverse_op={"type": "remove_item", "item_id": "itm_1"},
        actor="agent",
    )
    db_session.add_all([op1, op2])
    db_session.commit()

    # Query back via relationship
    queried_timeline = db_session.execute(
        select(TimelineModel).where(TimelineModel.id == timeline_row.id)
    ).scalar_one()

    assert len(queried_timeline.ops) == 2
    assert queried_timeline.ops[0].seq == 1
    assert queried_timeline.ops[0].actor == "user"
    assert queried_timeline.ops[1].seq == 2
    assert queried_timeline.ops[1].actor == "agent"
    assert queried_timeline.ops[0].group_id == queried_timeline.ops[1].group_id

    # Verify duplicate (timeline_id, seq) triggers IntegrityError
    dup_op = TimelineOpModel(
        timeline_id=timeline_row.id,
        seq=1,
        group_id=str(uuid.uuid4()),
        op={"type": "noop"},
        inverse_op={"type": "noop"},
        actor="user",
    )
    db_session.add(dup_op)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_timeline_versions_snapshot(db_session: Session) -> None:
    """Verify snapshot versions storage and unique constraint."""
    video = Video(
        filename="test_versions.mp4",
        file_path="/tmp/test_versions.mp4",
        duration=10.0,
        status="uploaded",
    )
    db_session.add(video)
    db_session.commit()

    timeline_row = TimelineModel(
        id=str(uuid.uuid4()),
        video_id=video.id,
        version=5,
        data={"id": "v5", "tracks": []},
    )
    db_session.add(timeline_row)
    db_session.commit()

    v1 = TimelineVersionModel(
        timeline_id=timeline_row.id,
        version=5,
        snapshot={"version": 5, "tracks": []},
    )
    db_session.add(v1)
    db_session.commit()

    queried_timeline = db_session.execute(
        select(TimelineModel).where(TimelineModel.id == timeline_row.id)
    ).scalar_one()

    assert len(queried_timeline.versions) == 1
    assert queried_timeline.versions[0].version == 5
    assert queried_timeline.versions[0].snapshot["version"] == 5

    # Verify duplicate version constraint
    dup_v = TimelineVersionModel(
        timeline_id=timeline_row.id,
        version=5,
        snapshot={"version": 5, "tracks": []},
    )
    db_session.add(dup_v)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_timeline_cascade_deletion(db_session: Session) -> None:
    """Verify that deleting a Video cascades to Timeline, Ops, and Versions."""
    video = Video(
        filename="cascade_test.mp4",
        file_path="/tmp/cascade_test.mp4",
        duration=20.0,
        status="uploaded",
    )
    db_session.add(video)
    db_session.commit()

    timeline_row = TimelineModel(
        id=str(uuid.uuid4()),
        video_id=video.id,
        version=1,
        data={"id": "cascade_tl"},
    )
    db_session.add(timeline_row)
    db_session.commit()

    op = TimelineOpModel(
        timeline_id=timeline_row.id,
        seq=1,
        group_id=str(uuid.uuid4()),
        op={"type": "noop"},
        inverse_op={"type": "noop"},
        actor="user",
    )
    ver = TimelineVersionModel(
        timeline_id=timeline_row.id,
        version=1,
        snapshot={"version": 1},
    )
    db_session.add_all([op, ver])
    db_session.commit()

    # Delete video
    db_session.delete(video)
    db_session.commit()

    # Verify cascade
    assert (
        db_session.execute(
            select(TimelineModel).where(TimelineModel.id == timeline_row.id)
        ).scalar_one_or_none()
        is None
    )
    assert (
        db_session.execute(
            select(TimelineOpModel).where(
                TimelineOpModel.timeline_id == timeline_row.id
            )
        ).scalar_one_or_none()
        is None
    )
    assert (
        db_session.execute(
            select(TimelineVersionModel).where(
                TimelineVersionModel.timeline_id == timeline_row.id
            )
        ).scalar_one_or_none()
        is None
    )
