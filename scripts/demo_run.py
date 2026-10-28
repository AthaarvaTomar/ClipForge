#!/usr/bin/env python3
"""Automated Demo Run script rehearsing the entire ClipForge AI pipeline end-to-end.

Task S5: Phase 9 Scale, Measure, Demo.
"""

from __future__ import annotations

import base64
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from app.main import app
from app.tasks.celery_app import celery_app

# Enable eager execution in demo rehearsal so it runs standalone without Redis
celery_app.conf.task_always_eager = True
celery_app.conf.result_backend = "cache+memory://"

client = TestClient(app)


def log_step(step_num: int, title: str):
    print(f"\n[Step {step_num}] {title}", flush=True)
    print("-" * 55, flush=True)


def create_demo_video(path: Path, duration: int = 4) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"testsrc=duration={duration}:size=1280x720:rate=30",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency=440:duration={duration}",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        str(path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return path


def run_full_demo():
    print("=" * 70)
    print(" ClipForge AI — End-to-End Automated Demo Run (Task S5)")
    print("=" * 70)

    scratch = Path("./data/demo_tmp")
    scratch.mkdir(parents=True, exist_ok=True)
    demo_video = scratch / "demo_source.mp4"
    create_demo_video(demo_video, duration=4)

    # Step 1: Health & Presets
    log_step(1, "Verify System Health and Presets Catalog")
    health_resp = client.get("/health")
    assert health_resp.status_code == 200, f"Health check failed: {health_resp.text}"
    print(f"  Health: {health_resp.json()['status']} (200 OK)")

    presets_resp = client.get("/api/presets")
    assert presets_resp.status_code == 200
    presets = presets_resp.json()
    n_grades = len(presets.get("grades", []))
    n_trans = len(presets.get("transitions", []))
    print(f"  Loaded {n_grades} grade presets, {n_trans} transitions")

    # Step 2: Resumable Upload (Tus Protocol)
    log_step(2, "Upload Video via Resumable Tus Protocol")
    video_bytes = demo_video.read_bytes()
    total_bytes = len(video_bytes)

    meta_fn = base64.b64encode(b"demo_talking_head.mp4").decode("ascii")
    headers = {
        "Tus-Resumable": "1.0.0",
        "Upload-Length": str(total_bytes),
        "Upload-Metadata": f"filename {meta_fn},filetype dmlkZW8vbXA0",
    }
    init_resp = client.post("/api/upload/tus", headers=headers)
    assert init_resp.status_code == 201
    upload_url = init_resp.headers["Location"]
    upload_id = upload_url.split("/")[-1]
    print(f"  Initialized Tus session: {upload_id}")

    # Chunk 1 (interruption simulation)
    halfway = total_bytes // 2
    patch1 = client.patch(
        f"/api/upload/tus/{upload_id}",
        content=video_bytes[:halfway],
        headers={
            "Tus-Resumable": "1.0.0",
            "Upload-Offset": "0",
            "Content-Type": "application/offset+octet-stream",
        },
    )
    assert patch1.status_code == 204
    print(f"  Chunk 1 sent ({halfway}/{total_bytes} bytes). Simulating pause...")

    # Chunk 2 (resume to completion)
    patch2 = client.patch(
        f"/api/upload/tus/{upload_id}",
        content=video_bytes[halfway:],
        headers={
            "Tus-Resumable": "1.0.0",
            "Upload-Offset": str(halfway),
            "Content-Type": "application/offset+octet-stream",
        },
    )
    assert patch2.status_code == 204
    video_id = patch2.headers.get("Video-Id")
    assert video_id is not None
    print(f"  Upload completed & finalized! Video ID: {video_id}")

    # Step 3: Inspect Video Details
    log_step(3, "Inspect Video Metadata via API")
    video_resp = client.get(f"/api/videos/{video_id}")
    assert video_resp.status_code == 200
    v_data = video_resp.json()
    print(f"  Resolution: {v_data['width']}x{v_data['height']} ({v_data['orientation']})")
    print(f"  Duration:   {v_data['duration']}s @ {v_data['fps']} fps")

    # Step 4: Indexing and Intelligence
    log_step(4, "Run Footage Indexing (Scenes, Silences, Visuals)")
    with patch(
        "app.services.visual_service.VisualUnderstandingService.describe_scene_frame",
        return_value={
            "scene_index": 0,
            "timestamp": 0.0,
            "caption": "Talking head demonstration",
            "tags": ["demo", "speech"],
        },
    ):
        index_resp = client.post(f"/api/videos/{video_id}/index")
        assert index_resp.status_code in (200, 202)
        print(f"  Indexing enqueued/processed: {index_resp.json().get('status', 'OK')}", flush=True)

    # Step 5: Timeline Creation
    log_step(5, "Initialize Multi-Track Timeline from Video")
    initial_tracks = [
        {
            "id": "track_v1",
            "name": "V1",
            "type": "video",
            "items": [
                {
                    "id": "it_demo_v1",
                    "source": video_id,
                    "src_in": 0,
                    "src_out": 4000,
                    "start": 0,
                }
            ],
        }
    ]
    tl_create_resp = client.post(
        "/api/timelines",
        json={"video_id": video_id, "tracks": initial_tracks},
    )
    assert tl_create_resp.status_code == 201, f"Create timeline failed: {tl_create_resp.text}"
    tl_data = tl_create_resp.json()
    timeline_id = tl_data["id"]
    tl_info = f"version={tl_data['version']}, tracks={len(tl_data['tracks'])}"
    print(f"  Created Timeline ID: {timeline_id} ({tl_info})", flush=True)

    # Step 6: AI Edit Planner
    log_step(6, "Execute AI Edit Planner ('tighten first 15s and add B-roll')")
    plan_resp = client.post(
        f"/api/timelines/{timeline_id}/plan",
        json={"prompt": "tighten first 15s", "dry_run": True},
    )
    assert plan_resp.status_code in (200, 202), f"Plan failed: {plan_resp.text}"
    plan_data = plan_resp.json()
    rationale = plan_data.get("rationale", "Optimized timing")[:65]
    print(f"  Planner rationale: {rationale}...", flush=True)
    ops = plan_data.get("ops", [])
    print(f"  Generated {len(ops)} plan operations: {[op.get('op') for op in ops[:3]]}", flush=True)

    # Step 7: Batch Apply Ops & Undo/Redo Test
    log_step(7, "Apply Ops with Optimistic Concurrency and Test Undo/Redo")
    if ops:
        apply_resp = client.post(
            f"/api/timelines/{timeline_id}/ops",
            json={
                "expected_version": tl_data["version"],
                "actor": "agent",
                "ops": ops,
            },
        )
        assert apply_resp.status_code == 200
        new_version = apply_resp.json()["version"]
        print(f"  Applied {len(ops)} ops in 1 atomic group -> bumped to v{new_version}")

        # Test single undo step
        undo_resp = client.post(
            f"/api/timelines/{timeline_id}/undo",
            json={"expected_version": new_version},
        )
        assert undo_resp.status_code == 200, f"Undo failed: {undo_resp.text}"
        undone_version = undo_resp.json()["version"]
        print(f"  Undo succeeded! Restored to v{undone_version}")

        # Test redo
        redo_resp = client.post(
            f"/api/timelines/{timeline_id}/redo",
            json={"expected_version": undone_version},
        )
        assert redo_resp.status_code == 200, f"Redo failed: {redo_resp.text}"
        print(f"  Redo succeeded! Advanced to v{redo_resp.json()['version']}")

    # Step 8: Timeline Rendering & Metrics
    log_step(8, "Render Timeline to 9:16 Vertical Video")
    render_resp = client.post(f"/api/timelines/{timeline_id}/render")
    assert render_resp.status_code == 202
    render_job = render_resp.json()
    job_id = render_job["id"]
    print(f"  Enqueued render job {job_id} in queue 'rendering'")

    # Step 9: Extract Timeline Preview Frame
    log_step(9, "Extract Live Timeline Preview Frame")
    frame_resp = client.get(f"/api/timelines/{timeline_id}/frame?t=1.0")
    if frame_resp.status_code == 200:
        print(f"  Extracted live JPEG frame ({len(frame_resp.content)} bytes)")
    else:
        print(f"  Preview frame status: {frame_resp.status_code} (non-blocking in dev)")

    # Step 10: Operational Metrics Inspection
    log_step(10, "Inspect System Metrics (/api/metrics)")
    metrics_resp = client.get("/api/metrics")
    assert metrics_resp.status_code == 200
    m_data = metrics_resp.json()
    summary = m_data["summary"]
    print(f"  Total tasks tracked: {summary['total_tasks']}")
    print(f"  Avg wait time:       {summary['avg_wait_time_ms']:.1f}ms")
    print(f"  Avg render time:     {summary['avg_render_time_ms']:.1f}ms")
    print(f"  Realtime factor:     {summary['avg_realtime_factor']:.2f}x")

    print("\n" + "=" * 70)
    print(" Demo Run Successfully Rehearsed with Zero Blockers! [PASSED]")
    print("=" * 70)


if __name__ == "__main__":
    run_full_demo()
