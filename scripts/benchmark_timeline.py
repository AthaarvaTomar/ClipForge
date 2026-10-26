"""Timeline Performance Benchmark Script (Task T6).

Measures and validates:
1. Engine throughput: 500 ops apply in under 1.0s in timeline_engine.apply.
2. Batch API latency: 500 ops apply in under 2.0s through POST /api/timelines/{id}/ops.
3. Responsiveness: Concurrent requests (/health) stay responsive while the 500-op batch is running.
"""

import json
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.main import app
from app.models.video import Video
from app.schemas.timeline import Timeline
from app.services.timeline_engine import apply


def benchmark_engine(ops_count: int = 500) -> float:
    """Benchmark raw timeline_engine.apply pure function for N operations."""
    tl = Timeline(
        id="bench_tl",
        video_id="bench_vid",
        version=1,
        source_duration_ms=ops_count * 200,
        tracks=[],
    )
    # Add initial track
    tl, _ = apply(tl, {"op": "add_track", "track_type": "video", "name": "Main Video"})

    # Prepare operations
    ops: list[dict[str, Any]] = [
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

    assert len(tl.tracks[0].items) == ops_count, "Item count mismatch in engine benchmark"
    return elapsed


def is_live_server_running(url: str = "http://127.0.0.1:8000/health") -> bool:
    """Check if an active Uvicorn instance is accessible."""
    try:
        with urllib.request.urlopen(url, timeout=0.5) as response:
            return response.status == 200
    except Exception:
        return False


def benchmark_batch_api_live(
    base_url: str,
    video_id: str,
    ops_count: int = 500,
) -> tuple[float, list[float]]:
    """Benchmark batch API over actual HTTP sockets against a running server."""
    # 1. Create a fresh timeline
    create_payload = json.dumps({"video_id": video_id}).encode("utf-8")
    req = urllib.request.Request(
        f"{base_url}/api/timelines",
        data=create_payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as resp:
        tl_data = json.loads(resp.read().decode("utf-8"))
    tl_id = tl_data["id"]

    # 2. Setup initial track
    setup_payload = json.dumps({
        "expected_version": 1,
        "ops": [{"op": "add_track", "track_type": "video", "name": "Main Video"}],
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{base_url}/api/timelines/{tl_id}/ops",
        data=setup_payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req):
        pass

    # 3. Prepare 500 ops batch
    ops: list[dict[str, Any]] = [
        {
            "op": "add_item",
            "track_index": 0,
            "item": {
                "id": f"api_item_{i:04d}",
                "source": video_id,
                "src_in": 0,
                "src_out": 100,
                "start": i * 150,
            },
        }
        for i in range(ops_count)
    ]
    batch_bytes = json.dumps({
        "expected_version": 2,
        "actor": "agent",
        "ops": ops,
    }).encode("utf-8")

    # Warmup probe
    with urllib.request.urlopen(f"{base_url}/health"):
        pass

    concurrent_latencies: list[float] = []

    def run_concurrent_probes() -> None:
        for _ in range(15):
            t0 = time.perf_counter()
            with urllib.request.urlopen(f"{base_url}/health") as r:
                assert r.status == 200
            concurrent_latencies.append((time.perf_counter() - t0) * 1000.0)
            time.sleep(0.01)

    start_api = time.perf_counter()
    with ThreadPoolExecutor(max_workers=2) as executor:
        probe_future = executor.submit(run_concurrent_probes)

        def do_batch() -> dict[str, Any]:
            batch_req = urllib.request.Request(
                f"{base_url}/api/timelines/{tl_id}/ops",
                data=batch_bytes,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(batch_req) as b_resp:
                return json.loads(b_resp.read().decode("utf-8"))

        batch_future = executor.submit(do_batch)
        batch_res = batch_future.result()
        probe_future.result()

    batch_elapsed = time.perf_counter() - start_api
    assert len(batch_res["tracks"][0]["items"]) == ops_count, "Item count mismatch in result"
    return batch_elapsed, concurrent_latencies


def benchmark_batch_api_testclient(
    client: TestClient,
    video_id: str,
    ops_count: int = 500,
) -> tuple[float, list[float]]:
    """Benchmark batch API using FastAPI TestClient when live server is not active."""
    create_res = client.post("/api/timelines", json={"video_id": video_id})
    assert create_res.status_code == 201, f"Failed to create timeline: {create_res.text}"
    tl_id = create_res.json()["id"]

    setup_res = client.post(
        f"/api/timelines/{tl_id}/ops",
        json={
            "expected_version": 1,
            "ops": [{"op": "add_track", "track_type": "video", "name": "Main Video"}],
        },
    )
    assert setup_res.status_code == 200, f"Track setup failed: {setup_res.text}"

    ops: list[dict[str, Any]] = [
        {
            "op": "add_item",
            "track_index": 0,
            "item": {
                "id": f"api_item_{i:04d}",
                "source": video_id,
                "src_in": 0,
                "src_out": 100,
                "start": i * 150,
            },
        }
        for i in range(ops_count)
    ]

    client.get("/health")
    probe_client = TestClient(app)
    probe_client.get("/health")
    concurrent_latencies: list[float] = []

    def run_concurrent_probes() -> None:
        for _ in range(15):
            t0 = time.perf_counter()
            resp = probe_client.get("/health")
            t_el = (time.perf_counter() - t0) * 1000.0
            if resp.status_code == 200:
                concurrent_latencies.append(t_el)
            time.sleep(0.01)

    batch_payload = {
        "expected_version": 2,
        "actor": "agent",
        "ops": ops,
    }

    start_api = time.perf_counter()
    with ThreadPoolExecutor(max_workers=2) as executor:
        probe_future = executor.submit(run_concurrent_probes)
        batch_res = client.post(f"/api/timelines/{tl_id}/ops", json=batch_payload)
        probe_future.result()
    batch_elapsed = time.perf_counter() - start_api

    assert batch_res.status_code == 200, f"Batch API failed: {batch_res.text}"
    data = batch_res.json()
    assert len(data["tracks"][0]["items"]) == ops_count, "Item count mismatch in result"
    return batch_elapsed, concurrent_latencies


def main() -> None:
    print("=" * 65)
    print("ClipForge AI — Timeline Performance Benchmark (Task T6)")
    print("=" * 65)

    # 1. Engine Benchmark
    ops_count = 500
    print(f"\n[1/3] Benchmarking Engine apply() with {ops_count} operations...")
    engine_time = benchmark_engine(ops_count)
    engine_throughput = ops_count / engine_time
    engine_pass = engine_time < 1.0
    status_str = "PASS (< 1.0s)" if engine_pass else "FAIL (>= 1.0s)"
    print(f"  Duration:   {engine_time:.4f}s ({engine_throughput:.1f} ops/sec)")
    print(f"  Status:     {status_str}")

    # 2. Setup Test Database fixture for API Benchmark
    db = SessionLocal()
    video = Video(
        filename="benchmark_source.mp4",
        file_path="storage/uploads/benchmark_source.mp4",
        status="uploaded",
        duration=ops_count * 0.5,
    )
    db.add(video)
    db.commit()
    db.refresh(video)
    video_id = video.id
    db.close()

    try:
        live_server = is_live_server_running()
        mode_desc = "Live Uvicorn Server (HTTP)" if live_server else "FastAPI TestClient"
        print(f"\n[2/3] Benchmarking Batch API with {ops_count} ops [{mode_desc}]...")
        print(f"[3/3] Monitoring Concurrent Request Latency during batch [{mode_desc}]...")

        if live_server:
            batch_time, latencies = benchmark_batch_api_live(
                "http://127.0.0.1:8000", video_id, ops_count
            )
            max_allowed_probe = 250.0  # HTTP network latency limit
        else:
            client = TestClient(app)
            batch_time, latencies = benchmark_batch_api_testclient(
                client, video_id, ops_count
            )
            max_allowed_probe = 500.0  # In-process testclient GIL limit

        batch_pass = batch_time < 2.0
        batch_status = "PASS (< 2.0s)" if batch_pass else "FAIL (>= 2.0s)"
        print(f"  Batch Duration: {batch_time:.4f}s ({ops_count / batch_time:.1f} ops/sec)")
        print(f"  Status:         {batch_status}")

        avg_lat = sum(latencies) / len(latencies) if latencies else 0.0
        max_lat = max(latencies) if latencies else 0.0
        resp_pass = len(latencies) > 0 and max_lat < max_allowed_probe
        resp_status = f"PASS (< {max_allowed_probe:.0f}ms)" if resp_pass else "FAIL"

        print(f"\nConcurrent Responsiveness Probes ({len(latencies)} requests):")
        print(f"  Average Latency: {avg_lat:.2f}ms")
        print(f"  Max Latency:     {max_lat:.2f}ms")
        print(f"  Status:          {resp_status}")

        print("\n" + "=" * 65)
        print("Summary Results:")
        print(f"  1. Engine 500 Ops:     {engine_time:.4f}s  [{status_str}]")
        print(f"  2. Batch API 500 Ops:  {batch_time:.4f}s  [{batch_status}]")
        print(f"  3. Server Responsive:  {max_lat:.2f}ms max [{resp_status}]")
        print("=" * 65)

        all_passed = engine_pass and batch_pass and resp_pass
        if not all_passed:
            print("\nBenchmark FAILED one or more threshold constraints.")
            sys.exit(1)

        print("\nAll benchmark targets PASSED successfully!")
        sys.exit(0)

    finally:
        db_clean = SessionLocal()
        vid = db_clean.get(Video, video_id)
        if vid:
            db_clean.delete(vid)
            db_clean.commit()
        db_clean.close()


if __name__ == "__main__":
    main()
