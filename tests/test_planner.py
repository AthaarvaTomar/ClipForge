"""Integration and unit tests for Phase 6: AI Edit Planner (Milestones P2, P3, P4, P5, P6, P7)."""

import uuid
from collections.abc import Generator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.main import app
from app.models.timeline import TimelineModel
from app.models.video import Video
from app.models.video_index import VideoIndex
from app.schemas.timeline import Item, Track, TrackType
from app.services.context_builder import ContextBuilderService
from app.services.planner_service import (
    EditPlannerService,
    TimelinePlanValidationError,
)
from app.services.timeline_engine import apply
from app.services.timeline_service import TimelineService
from app.tasks.celery_app import celery_app


@pytest.fixture(autouse=True)
def configure_celery_eager() -> Any:
    """Ensure Celery tasks execute synchronously within tests."""
    original_eager = celery_app.conf.task_always_eager
    original_backend = celery_app.conf.result_backend
    celery_app.conf.task_always_eager = True
    celery_app.conf.result_backend = "cache+memory://"
    yield
    celery_app.conf.task_always_eager = original_eager
    celery_app.conf.result_backend = original_backend


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    """Fixture providing a fresh isolated database session."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def sample_video_and_timeline(db_session: Session) -> tuple[Video, TimelineModel]:
    """Fixture creating a test video, video index, and multi-track timeline."""
    test_id = str(uuid.uuid4())
    video = Video(
        id=test_id,
        filename="planner_test_video.mp4",
        file_path="data/uploads/planner_test_video.mp4",
        duration=180.0,
        width=1920,
        height=1080,
        fps=30.0,
        orientation="landscape",
        status="READY",
    )
    db_session.add(video)
    db_session.commit()

    # Create video index with sample silences, repeated takes, and visuals
    index = VideoIndex(
        video_id=video.id,
        status="READY",
        scenes=[
            {"start": 0.0, "end": 60.0},
            {"start": 60.0, "end": 120.0},
            {"start": 120.0, "end": 180.0},
        ],
        silences=[
            {"start": 12.0, "end": 14.5},
            {"start": 45.0, "end": 47.0},
            {"start": 90.0, "end": 92.5},
        ],
        fillers=[{"word": "um", "start": 5.0, "end": 5.5}],
        repeated_takes=[
            {
                "group_id": "take_grp_1",
                "chosen_take_id": "take_1b",
                "candidates": [
                    {"id": "take_1a", "start": 20.0, "end": 35.0, "text": "Hello world welcome"},
                    {
                        "id": "take_1b",
                        "start": 36.0,
                        "end": 50.0,
                        "text": "Hello world welcome to ClipForge",
                    },
                ],
            }
        ],
        visuals=[
            {
                "scene_index": 0,
                "timestamp_s": 30.0,
                "tags": ["host", "talking"],
                "caption": "Host speaking into mic",
            },
            {
                "scene_index": 1,
                "timestamp_s": 90.0,
                "tags": ["screen", "demo"],
                "caption": "Screen recording demo",
            },
        ],
        chapters=[
            {"title": "Introduction", "start": 0.0, "end": 60.0, "summary": "Opening remarks"},
            {
                "title": "Deep Dive",
                "start": 60.0,
                "end": 180.0,
                "summary": "Core feature walkthrough",
            },
        ],
        hook={
            "start": 36.0,
            "end": 50.0,
            "virality_score": 92,
            "text": "Wait until you see this edit!",
        },
    )
    db_session.add(index)
    db_session.commit()

    # Create timeline with 2 video items and an audio item
    item1 = Item(
        id="item_vid_1",
        source=video.id,
        src_in=0,
        src_out=60000,
        start=0,
        volume=1.0,
    )
    item2 = Item(
        id="item_vid_2",
        source=video.id,
        src_in=60000,
        src_out=180000,
        start=60000,
        volume=1.0,
    )
    track_v = Track(
        id="trk_main_video",
        type=TrackType.VIDEO,
        name="Main Video",
        items=[item1, item2],
    )
    track_a = Track(
        id="trk_main_audio",
        type=TrackType.AUDIO,
        name="Background Audio",
        items=[
            Item(
                id="item_aud_1",
                source="music_asset",
                src_in=0,
                src_out=180000,
                start=0,
                volume=0.8,
            )
        ],
    )
    tl_model = TimelineService.create_timeline(
        db=db_session,
        video_id=video.id,
        tracks=[track_v, track_a],
        source_duration_ms=180000,
    )
    return video, TimelineService.get_timeline_model(db_session, tl_model.id)


def test_p2_context_builder_compact_summary(
    sample_video_and_timeline: tuple[Video, TimelineModel],
) -> None:
    """Milestone P2: Compact index summary and current timeline summary within a token budget."""
    _, tl_model = sample_video_and_timeline
    timeline = tl_model.to_schema()

    # Generate index with 100+ items simulating a 3-hour video
    simulated_3hr_index = {
        "chapters": [
            {"title": f"Chapter {i}", "start": i * 300, "summary": f"Summary {i}"}
            for i in range(25)
        ],
        "silences": [{"start": i * 15, "end": i * 15 + 2.0} for i in range(120)],
        "repeated_takes": [
            {
                "group_id": f"take_{i}",
                "chosen_take_id": f"take_{i}_b",
                "candidates": [{"id": f"take_{i}_a"}, {"id": f"take_{i}_b"}],
            }
            for i in range(30)
        ],
        "visuals": [
            {
                "scene_index": i,
                "timestamp_s": i * 60,
                "tags": ["tag1", "tag2"],
                "caption": f"Scene {i}",
            }
            for i in range(60)
        ],
        "hook": {"start": 10.0, "end": 25.0, "virality_score": 95, "text": "Catchy hook"},
        "highlights": [
            {"title": f"Highlight {i}", "start": i * 500, "end": i * 500 + 30, "score": 90}
            for i in range(10)
        ],
    }

    prompt = ContextBuilderService.build_planner_prompt(
        user_prompt="remove all silences and tighten start",
        timeline=timeline,
        index=simulated_3hr_index,
    )

    # A 3-hour index should compact into < 8,000 characters (~2,000 tokens)
    assert len(prompt) < 8000
    assert "Timeline ID:" in prompt
    assert "Chapters:" in prompt
    assert "Silences (" in prompt
    assert "Repeated Takes (" in prompt
    assert "Visual Scenes:" in prompt
    assert "remove all silences and tighten start" in prompt


def test_p3_plan_endpoint_and_job(sample_video_and_timeline: tuple[Video, TimelineModel]) -> None:
    """Milestone P3: POST /api/timelines/{id}/plan {prompt} returns {rationale, ops[]}."""
    _, tl_model = sample_video_and_timeline
    client = TestClient(app)

    # 1. Create plan
    resp = client.post(
        f"/api/timelines/{tl_model.id}/plan",
        json={"prompt": "remove all silences", "dry_run": False},
    )
    assert resp.status_code == 200
    plan_data = resp.json()
    assert plan_data["timeline_id"] == tl_model.id
    plan_id = plan_data["id"]

    # 2. Retrieve plan via GET
    get_resp = client.get(f"/api/timelines/{tl_model.id}/plan/{plan_id}")
    assert get_resp.status_code == 200
    plan_details = get_resp.json()
    assert plan_details["id"] == plan_id
    assert "ops" in plan_details
    assert isinstance(plan_details["ops"], list)
    assert len(plan_details["ops"]) > 0
    assert "rationale" in plan_details
    assert plan_details["status"] in ("VALIDATED", "PENDING")


def test_p4_validate_and_repair(sample_video_and_timeline: tuple[Video, TimelineModel]) -> None:
    """Milestone P4: Apply ops to a copy, reject invalid ones, retry/repair once."""
    _, tl_model = sample_video_and_timeline
    timeline = tl_model.to_schema()

    # Construct plan with 1 valid op, 1 out-of-bounds split op, and 1 valid op
    ops = [
        {
            "type": "trim",
            "track_id": "trk_main_video",
            "item_id": "item_vid_1",
            "new_src_in": 1000,
            "new_src_out": 50000,
        },
        {
            "type": "split",
            "track_id": "trk_main_video",
            "item_id": "item_vid_1",
            "split_time": 999999,  # Invalid: way beyond item_vid_1 end
        },
        {
            "type": "set_volume",
            "track_id": "trk_main_audio",
            "item_id": "item_aud_1",
            "volume": 0.4,
        },
    ]

    repaired_ops, err = EditPlannerService.validate_and_repair_plan(
        timeline=timeline,
        ops=ops,
        user_prompt="test repair",
        max_retries=1,
    )
    # The invalid split op should be pruned/repaired, leaving the 2 valid ops
    assert len(repaired_ops) == 2
    assert repaired_ops[0]["type"] == "trim"
    assert repaired_ops[1]["type"] == "set_volume"

    # Verify unrepairable invalid op sequence raises TimelinePlanValidationError
    fatal_ops = [
        {"type": "remove_item", "track_id": "non_existent_trk", "item_id": "non_existent_itm"}
        for _ in range(3)
    ]
    with pytest.raises(TimelinePlanValidationError):
        EditPlannerService.validate_and_repair_plan(
            timeline=timeline,
            ops=fatal_ops,
            user_prompt="test fatal",
            max_retries=0,
        )


def test_p5_apply_plan_single_undo_group(
    sample_video_and_timeline: tuple[Video, TimelineModel], db_session: Session
) -> None:
    """Milestone P5: POST .../plan/{id}/apply applies ops as one undo group with actor agent."""
    _, tl_model = sample_video_and_timeline
    client = TestClient(app)

    initial_version = tl_model.version
    initial_schema = tl_model.to_schema()

    # Create plan with multiple ops
    plan_resp = client.post(
        f"/api/timelines/{tl_model.id}/plan",
        json={"prompt": "tighten first 15s", "dry_run": True},
    )
    assert plan_resp.status_code == 200
    plan_id = plan_resp.json()["id"]

    # Apply plan
    apply_resp = client.post(
        f"/api/timelines/{tl_model.id}/plan/{plan_id}/apply",
        json={},
    )
    assert apply_resp.status_code == 200
    applied_tl = apply_resp.json()
    assert applied_tl["version"] > initial_version
    assert applied_tl["tracks"][0]["items"][0]["src_in"] == 2500

    # Check op log: actor must be "agent"
    history_resp = client.get(f"/api/timelines/{tl_model.id}/history")
    history_data = history_resp.json()
    assert len(history_data["ops"]) > 0
    latest_op = history_data["ops"][-1]
    assert latest_op["actor"] == "agent"

    # Single undo step reverts the entire plan back to initial items
    undo_resp = client.post(
        f"/api/timelines/{tl_model.id}/undo",
        json={"expected_version": applied_tl["version"]},
    )
    assert undo_resp.status_code == 200
    reverted_tl = undo_resp.json()
    assert reverted_tl["version"] == applied_tl["version"] + 1
    assert (
        reverted_tl["tracks"][0]["items"][0]["src_in"] == initial_schema.tracks[0].items[0].src_in
    )


def test_p6_demo_prompts(
    sample_video_and_timeline: tuple[Video, TimelineModel], db_session: Session
) -> None:
    """Milestone P6: Core demo prompts working deterministically on sample footage."""
    _, tl_model = sample_video_and_timeline
    timeline = tl_model.to_schema()

    demo_prompts = [
        "tighten first 15s",
        "remove repeated takes",
        "remove all silences",
        "add B-roll",
        "make 3 Shorts",
    ]

    for prompt in demo_prompts:
        rationale, ops = EditPlannerService.generate_plan(
            db=db_session,
            timeline_id=tl_model.id,
            prompt=prompt,
        )
        assert len(rationale) > 0
        assert len(ops) > 0

        # Verify operations apply without raising TimelineOperationError
        test_tl = timeline.model_copy(deep=True)
        for op in ops:
            test_tl, _ = apply(test_tl, op)
        assert test_tl.version == timeline.version


def test_p7_websocket_live_events(sample_video_and_timeline: tuple[Video, TimelineModel]) -> None:
    """Milestone P7: WebSocket /ws/timelines/{id} pushing op-applied events."""
    _, tl_model = sample_video_and_timeline
    client = TestClient(app)

    with client.websocket_connect(f"/ws/timelines/{tl_model.id}") as websocket:
        # Check initial connection acknowledgment
        init_event = websocket.receive_json()
        assert init_event["event"] == "CONNECTED"
        assert init_event["timeline_id"] == tl_model.id

        # Trigger plan application through REST endpoint
        plan_resp = client.post(
            f"/api/timelines/{tl_model.id}/plan",
            json={"prompt": "tighten start", "dry_run": True},
        )
        plan_id = plan_resp.json()["id"]

        client.post(f"/api/timelines/{tl_model.id}/plan/{plan_id}/apply", json={})

        # Verify live event was pushed to the websocket connection
        live_event = websocket.receive_json()
        assert live_event["event"] == "OP_APPLIED"
        assert live_event["timeline_id"] == tl_model.id
        assert live_event["actor"] == "agent"
        assert live_event["plan_id"] == plan_id
