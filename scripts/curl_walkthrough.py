"""Curl walkthrough script for Timeline API (Task T5).

Covers:
1. POST /api/timelines (create from video)
2. GET /api/timelines/{id} (fetch)
3. POST /api/timelines/{id}/ops (batch apply)
4. POST /api/timelines/{id}/ops (409 version conflict verification)
5. POST /api/timelines/{id}/undo (undo latest group)
6. POST /api/timelines/{id}/redo (redo next group)
7. GET /api/timelines/{id}/history (view op log & snapshots)
8. POST /api/timelines/{id}/restore/{version} (restore snapshot)
"""

import json
import subprocess
import sys


def run_curl(cmd: list[str]) -> tuple[int, dict]:
    result = subprocess.run(cmd, capture_output=True, text=True)
    try:
        data = json.loads(result.stdout)
    except Exception:
        data = {"raw": result.stdout, "stderr": result.stderr}
    return result.returncode, data


def main() -> None:
    base_url = "http://127.0.0.1:8000"

    print("=" * 60)
    print("ClipForge AI — Timeline API Curl Walkthrough")
    print("=" * 60)

    # Step 0: Fetch or create a test video
    _, vids_res = run_curl(["curl.exe", "-s", f"{base_url}/api/videos"])
    videos = vids_res.get("videos", [])
    if not videos:
        print("Error: No videos found in database. Run pytest first to populate test video.")
        sys.exit(1)
    video_id = videos[0]["id"]
    print(f"Using Video ID: {video_id} (duration: {videos[0].get('duration')}s)")

    # Step 1: Create Timeline
    print("\n--- 1. POST /api/timelines (Create timeline) ---")
    payload = json.dumps({"video_id": video_id})
    _, tl = run_curl([
        "curl.exe", "-s", "-X", "POST",
        f"{base_url}/api/timelines",
        "-H", "Content-Type: application/json",
        "-d", payload,
    ])
    tl_id = tl["id"]
    version = tl["version"]
    dur = tl.get("source_duration_ms")
    print(f"Created Timeline ID: {tl_id}, Version: {version}, Duration: {dur}ms")

    # Step 2: GET Timeline
    print(f"\n--- 2. GET /api/timelines/{tl_id} ---")
    _, tl_fetched = run_curl(["curl.exe", "-s", f"{base_url}/api/timelines/{tl_id}"])
    print(f"Fetched Timeline tracks count: {len(tl_fetched['tracks'])}")

    # Step 3: Batch apply operations (Add track and add item)
    print(f"\n--- 3. POST /api/timelines/{tl_id}/ops (Batch Edit) ---")
    ops_payload = json.dumps({
        "expected_version": version,
        "actor": "agent",
        "ops": [
            {"op": "add_track", "track_type": "video", "name": "Main Video"},
            {
                "op": "add_item",
                "track_index": 0,
                "item": {
                    "source": video_id,
                    "src_in": 0,
                    "src_out": 4000,
                    "start": 0,
                },
            },
        ],
    })
    _, tl_edited = run_curl([
        "curl.exe", "-s", "-X", "POST",
        f"{base_url}/api/timelines/{tl_id}/ops",
        "-H", "Content-Type: application/json",
        "-d", ops_payload,
    ])
    version = tl_edited["version"]
    item_count = len(tl_edited["tracks"][0]["items"])
    tracks_count = len(tl_edited["tracks"])
    print(f"Applied 2 ops! New Version: {version}, Tracks: {tracks_count}, Items: {item_count}")

    # Step 4: Verify 409 Version Conflict
    print(f"\n--- 4. POST /api/timelines/{tl_id}/ops (409 Conflict Test) ---")
    stale_payload = json.dumps({
        "expected_version": 1,  # Outdated version!
        "actor": "user",
        "ops": [{"op": "add_track", "track_type": "audio", "name": "BGM"}],
    })
    _, conflict_res = run_curl([
        "curl.exe", "-s", "-X", "POST",
        f"{base_url}/api/timelines/{tl_id}/ops",
        "-H", "Content-Type: application/json",
        "-d", stale_payload,
    ])
    conflict_msg = conflict_res.get("error", {}).get("message", conflict_res)
    print(f"Conflict response (HTTP 409): {conflict_msg}")

    # Step 5: Undo latest group
    print(f"\n--- 5. POST /api/timelines/{tl_id}/undo (Undo Agent Edit) ---")
    undo_payload = json.dumps({"expected_version": version})
    _, tl_undone = run_curl([
        "curl.exe", "-s", "-X", "POST",
        f"{base_url}/api/timelines/{tl_id}/undo",
        "-H", "Content-Type: application/json",
        "-d", undo_payload,
    ])
    version = tl_undone["version"]
    print(f"Undone! New Version: {version}, Tracks count: {len(tl_undone['tracks'])}")

    # Step 6: Redo the group
    print(f"\n--- 6. POST /api/timelines/{tl_id}/redo (Redo Edit) ---")
    redo_payload = json.dumps({"expected_version": version})
    _, tl_redone = run_curl([
        "curl.exe", "-s", "-X", "POST",
        f"{base_url}/api/timelines/{tl_id}/redo",
        "-H", "Content-Type: application/json",
        "-d", redo_payload,
    ])
    version = tl_redone["version"]
    redone_items = len(tl_redone["tracks"][0]["items"])
    redone_tracks = len(tl_redone["tracks"])
    print(f"Redone! New Version: {version}, Tracks: {redone_tracks}, Items: {redone_items}")

    # Step 7: Get History
    print(f"\n--- 7. GET /api/timelines/{tl_id}/history ---")
    _, history = run_curl(["curl.exe", "-s", f"{base_url}/api/timelines/{tl_id}/history"])
    print(f"Total ops recorded: {len(history['ops'])}, Snapshots: {len(history['versions'])}")
    for op_entry in history["ops"]:
        op_name = op_entry["op"].get("op") or op_entry["op"].get("type")
        grp = op_entry["group_id"][:8]
        print(f"  Seq {op_entry['seq']}: op={op_name}, actor={op_entry['actor']}, group={grp}...")

    # Step 8: Restore Version 1 snapshot
    print(f"\n--- 8. POST /api/timelines/{tl_id}/restore/1 (Restore Snapshot) ---")
    restore_payload = json.dumps({"expected_version": version})
    _, tl_restored = run_curl([
        "curl.exe", "-s", "-X", "POST",
        f"{base_url}/api/timelines/{tl_id}/restore/1",
        "-H", "Content-Type: application/json",
        "-d", restore_payload,
    ])
    version = tl_restored["version"]
    print(f"Restored to snapshot 1! New Version: {version}, Tracks: {len(tl_restored['tracks'])}")
    print("\nCurl walkthrough completed successfully!")


if __name__ == "__main__":
    main()
