import uuid
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.main import app
from app.models.video import Video


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def test_video_id() -> Generator[str, None, None]:
    db = SessionLocal()
    video = Video(
        filename="timeline_api_test.mp4",
        file_path="storage/uploads/timeline_api_test.mp4",
        status="uploaded",
        duration=60.0,
    )
    db.add(video)
    db.commit()
    db.refresh(video)
    vid_id = video.id
    db.close()

    yield vid_id

    # Cascade delete will clean up timelines created for this video
    db_clean = SessionLocal()
    vid = db_clean.get(Video, vid_id)
    if vid:
        db_clean.delete(vid)
        db_clean.commit()
    db_clean.close()


def test_create_timeline_api(client: TestClient, test_video_id: str) -> None:
    # 1. Successful timeline creation
    res = client.post(
        "/api/timelines",
        json={"video_id": test_video_id},
    )
    assert res.status_code == 201
    data = res.json()
    assert data["video_id"] == test_video_id
    assert data["version"] == 1
    assert data["source_duration_ms"] == 60000
    assert data["tracks"] == []
    assert "id" in data

    # 2. Unknown video ID returns 404
    bad_res = client.post(
        "/api/timelines",
        json={"video_id": str(uuid.uuid4())},
    )
    assert bad_res.status_code == 404


def test_get_timeline_api(client: TestClient, test_video_id: str) -> None:
    create_res = client.post(
        "/api/timelines",
        json={"video_id": test_video_id},
    )
    timeline_id = create_res.json()["id"]

    # 1. Successfully retrieve timeline
    get_res = client.get(f"/api/timelines/{timeline_id}")
    assert get_res.status_code == 200
    assert get_res.json()["id"] == timeline_id

    # 2. Unknown timeline returns 404
    bad_res = client.get(f"/api/timelines/{uuid.uuid4()}")
    assert bad_res.status_code == 404


def test_apply_ops_batch_and_concurrency_409(client: TestClient, test_video_id: str) -> None:
    create_res = client.post(
        "/api/timelines",
        json={"video_id": test_video_id},
    )
    timeline_id = create_res.json()["id"]

    # 1. Apply a batch of 2 operations (add track and add item)
    batch_payload = {
        "expected_version": 1,
        "actor": "agent",
        "ops": [
            {"op": "add_track", "track_type": "video", "name": "V1"},
            {
                "op": "add_item",
                "track_index": 0,
                "item": {
                    "source": test_video_id,
                    "src_in": 0,
                    "src_out": 5000,
                    "start": 0,
                },
            },
        ],
    }
    ops_res = client.post(f"/api/timelines/{timeline_id}/ops", json=batch_payload)
    assert ops_res.status_code == 200
    tl_v2 = ops_res.json()
    assert tl_v2["version"] == 2
    assert len(tl_v2["tracks"]) == 1
    assert len(tl_v2["tracks"][0]["items"]) == 1

    # 2. Optimistic concurrency conflict (409) if client repeats with expected_version=1
    conflict_res = client.post(f"/api/timelines/{timeline_id}/ops", json=batch_payload)
    assert conflict_res.status_code == 409
    conflict_data = conflict_res.json()
    assert conflict_data["current_version"] == 2
    assert conflict_data["expected_version"] == 1

    # 3. Invalid operation returns 422
    bad_op_payload = {
        "expected_version": 2,
        "ops": [{"op": "unknown_op_type"}],
    }
    bad_op_res = client.post(f"/api/timelines/{timeline_id}/ops", json=bad_op_payload)
    assert bad_op_res.status_code == 422


def test_undo_and_redo_api(client: TestClient, test_video_id: str) -> None:
    create_res = client.post(
        "/api/timelines",
        json={"video_id": test_video_id},
    )
    timeline_id = create_res.json()["id"]

    # Add track (version 1 -> 2)
    client.post(
        f"/api/timelines/{timeline_id}/ops",
        json={
            "expected_version": 1,
            "ops": [{"op": "add_track", "track_type": "video", "name": "V1"}],
        },
    )

    # Add item (version 2 -> 3)
    client.post(
        f"/api/timelines/{timeline_id}/ops",
        json={
            "expected_version": 2,
            "ops": [
                {
                    "op": "add_item",
                    "track_index": 0,
                    "item": {
                        "source": test_video_id,
                        "src_in": 1000,
                        "src_out": 4000,
                        "start": 0,
                    },
                }
            ],
        },
    )

    # 1. Undo with mismatched version returns 409
    undo_conflict = client.post(
        f"/api/timelines/{timeline_id}/undo",
        json={"expected_version": 1},
    )
    assert undo_conflict.status_code == 409
    assert undo_conflict.json()["current_version"] == 3

    # 2. Undo with correct version 3 -> version 4 (item removed, track still exists)
    undo_res = client.post(
        f"/api/timelines/{timeline_id}/undo",
        json={"expected_version": 3},
    )
    assert undo_res.status_code == 200
    tl_undone = undo_res.json()
    assert tl_undone["version"] == 4
    assert len(tl_undone["tracks"]) == 1
    assert len(tl_undone["tracks"][0]["items"]) == 0

    # 3. Redo with mismatched version returns 409
    redo_conflict = client.post(
        f"/api/timelines/{timeline_id}/redo",
        json={"expected_version": 2},
    )
    assert redo_conflict.status_code == 409
    assert redo_conflict.json()["current_version"] == 4

    # 4. Redo with correct version 4 -> version 5 (item restored)
    redo_res = client.post(
        f"/api/timelines/{timeline_id}/redo",
        json={"expected_version": 4},
    )
    assert redo_res.status_code == 200
    tl_redone = redo_res.json()
    assert tl_redone["version"] == 5
    assert len(tl_redone["tracks"][0]["items"]) == 1


def test_get_history_and_restore_version_api(client: TestClient, test_video_id: str) -> None:
    create_res = client.post(
        "/api/timelines",
        json={"video_id": test_video_id},
    )
    timeline_id = create_res.json()["id"]

    # Apply an op to create version 2
    client.post(
        f"/api/timelines/{timeline_id}/ops",
        json={
            "expected_version": 1,
            "actor": "user",
            "ops": [{"op": "add_track", "track_type": "video", "name": "Main"}],
        },
    )

    # 1. Check history
    history_res = client.get(f"/api/timelines/{timeline_id}/history")
    assert history_res.status_code == 200
    history_data = history_res.json()
    assert history_data["timeline_id"] == timeline_id
    assert history_data["current_version"] == 2
    assert history_data["current_seq"] == 1
    assert len(history_data["ops"]) == 1
    assert history_data["ops"][0]["seq"] == 1
    assert history_data["ops"][0]["actor"] == "user"
    assert len(history_data["versions"]) >= 1  # Initial snapshot at version 1

    # 2. Restore version 1 snapshot (restore with outdated version returns 409)
    restore_conflict = client.post(
        f"/api/timelines/{timeline_id}/restore/1",
        json={"expected_version": 1},
    )
    assert restore_conflict.status_code == 409

    # 3. Restore version 1 with expected_version=2 -> restores snapshot, bumps to version 3
    restore_res = client.post(
        f"/api/timelines/{timeline_id}/restore/1",
        json={"expected_version": 2},
    )
    assert restore_res.status_code == 200
    restored_tl = restore_res.json()
    assert restored_tl["version"] == 3
    assert restored_tl["tracks"] == []  # Track removed as per version 1 snapshot

    # 4. Attempt to restore non-existent snapshot version returns 422
    bad_restore = client.post(
        f"/api/timelines/{timeline_id}/restore/999",
        json={"expected_version": 3},
    )
    assert bad_restore.status_code == 422
