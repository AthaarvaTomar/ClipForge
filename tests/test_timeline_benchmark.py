import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.main import app
from app.models.video import Video
from app.schemas.timeline import Timeline
from app.services.timeline_engine import apply


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def test_video_id() -> Any:
    db = SessionLocal()
    video = Video(
        filename="perf_bench_video.mp4",
        file_path="storage/uploads/perf_bench_video.mp4",
        status="uploaded",
        duration=500.0,
    )
    db.add(video)
    db.commit()
    db.refresh(video)
    vid_id = video.id
    db.close()

    yield vid_id

    db_clean = SessionLocal()
    vid = db_clean.get(Video, vid_id)
    if vid:
        db_clean.delete(vid)
        db_clean.commit()
    db_clean.close()


def test_engine_500_ops_under_one_second() -> None:
    """Validate 500 ops apply in under 1.0s in timeline_engine (Task T6)."""
    ops_count = 500
    tl = Timeline(
        id="bench_engine",
        video_id="bench_vid",
        version=1,
        source_duration_ms=ops_count * 200,
        tracks=[],
    )
    tl, _ = apply(tl, {"op": "add_track", "track_type": "video", "name": "Video Track"})

    ops = [
        {
            "op": "add_item",
            "track_index": 0,
            "item": {
                "id": f"item_{i:04d}",
                "source": "bench_vid",
                "src_in": 0,
                "src_out": 100,
                "start": i * 150,
            },
        }
        for i in range(ops_count)
    ]

    start = time.perf_counter()
    for op in ops:
        tl, _ = apply(tl, op)
    elapsed = time.perf_counter() - start

    assert len(tl.tracks[0].items) == ops_count
    # Requirement: under 1 s in the engine
    assert elapsed < 1.0, f"Engine took {elapsed:.4f}s, expected < 1.0s"


def test_batch_api_500_ops_under_two_seconds(
    client: TestClient,
    test_video_id: str,
) -> None:
    """Validate 500 ops apply in under 2.0s through one batch API call (Task T6)."""
    ops_count = 500
    # 1. Create timeline
    res = client.post("/api/timelines", json={"video_id": test_video_id})
    assert res.status_code == 201
    tl_id = res.json()["id"]

    # 2. Add track (v1 -> v2)
    track_res = client.post(
        f"/api/timelines/{tl_id}/ops",
        json={
            "expected_version": 1,
            "ops": [{"op": "add_track", "track_type": "video", "name": "V1"}],
        },
    )
    assert track_res.status_code == 200

    # 3. 500 ops batch
    ops = [
        {
            "op": "add_item",
            "track_index": 0,
            "item": {
                "id": f"batch_item_{i:04d}",
                "source": test_video_id,
                "src_in": 0,
                "src_out": 100,
                "start": i * 150,
            },
        }
        for i in range(ops_count)
    ]

    start = time.perf_counter()
    batch_res = client.post(
        f"/api/timelines/{tl_id}/ops",
        json={
            "expected_version": 2,
            "actor": "agent",
            "ops": ops,
        },
    )
    elapsed = time.perf_counter() - start

    assert batch_res.status_code == 200
    data = batch_res.json()
    assert data["version"] == 3
    assert len(data["tracks"][0]["items"]) == ops_count
    # Requirement: under 2 s through one batch API call
    assert elapsed < 2.0, f"Batch API took {elapsed:.4f}s, expected < 2.0s"


def test_concurrent_requests_remain_responsive(
    client: TestClient,
    test_video_id: str,
) -> None:
    """Validate other requests stay responsive while 500 ops batch executes (Task T6)."""
    ops_count = 500
    res = client.post("/api/timelines", json={"video_id": test_video_id})
    tl_id = res.json()["id"]

    client.post(
        f"/api/timelines/{tl_id}/ops",
        json={
            "expected_version": 1,
            "ops": [{"op": "add_track", "track_type": "video", "name": "V1"}],
        },
    )

    ops = [
        {
            "op": "add_item",
            "track_index": 0,
            "item": {
                "id": f"resp_item_{i:04d}",
                "source": test_video_id,
                "src_in": 0,
                "src_out": 100,
                "start": i * 150,
            },
        }
        for i in range(ops_count)
    ]

    # Warmup probe client
    probe_client = TestClient(app)
    probe_client.get("/health")
    probe_client.get(f"/api/timelines/{tl_id}")

    probe_results: list[int] = []

    def probe_loop() -> None:
        for _ in range(10):
            r1 = probe_client.get("/health")
            probe_results.append(r1.status_code)
            r2 = probe_client.get(f"/api/timelines/{tl_id}")
            probe_results.append(r2.status_code)
            time.sleep(0.01)

    with ThreadPoolExecutor(max_workers=2) as executor:
        probe_future = executor.submit(probe_loop)
        batch_res = client.post(
            f"/api/timelines/{tl_id}/ops",
            json={
                "expected_version": 2,
                "actor": "agent",
                "ops": ops,
            },
        )
        probe_future.result()

    assert batch_res.status_code == 200
    assert len(probe_results) >= 10
    # Every concurrent request succeeded with 200 OK
    assert all(code == 200 for code in probe_results)
