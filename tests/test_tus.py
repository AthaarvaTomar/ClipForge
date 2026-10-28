import base64
import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def create_tiny_test_video(output_path: Path, duration: int = 2) -> Path:
    """Create a minimal real MP4 video for probe testing."""
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"testsrc=duration={duration}:size=320x240:rate=25",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency=1000:duration={duration}",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        str(output_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return output_path


def test_tus_options():
    resp = client.options("/api/upload/tus")
    assert resp.status_code == 204
    assert resp.headers.get("Tus-Resumable") == "1.0.0"
    assert "creation" in resp.headers.get("Tus-Extension", "")


def test_tus_resumable_upload_lifecycle(tmp_path: Path):
    # 1. Create a real sample video file
    video_path = tmp_path / "test_tus.mp4"
    create_tiny_test_video(video_path, duration=2)
    video_bytes = video_path.read_bytes()
    total_length = len(video_bytes)
    assert total_length > 0

    # 2. Initiate Tus upload (POST)
    meta_fn = base64.b64encode(b"sample_resumable.mp4").decode("ascii")
    headers = {
        "Tus-Resumable": "1.0.0",
        "Upload-Length": str(total_length),
        "Upload-Metadata": f"filename {meta_fn},filetype dmlkZW8vbXA0",
    }
    post_resp = client.post("/api/upload/tus", headers=headers)
    assert post_resp.status_code == 201
    location = post_resp.headers["Location"]
    assert location.startswith("/api/upload/tus/")
    upload_id = location.split("/")[-1]

    # 3. Check upload offset (HEAD)
    head_resp = client.head(f"/api/upload/tus/{upload_id}", headers={"Tus-Resumable": "1.0.0"})
    assert head_resp.status_code == 200
    assert head_resp.headers["Upload-Offset"] == "0"
    assert head_resp.headers["Upload-Length"] == str(total_length)

    # 4. Upload Part 1 (First half of file)
    halfway = total_length // 2
    part1_data = video_bytes[:halfway]

    patch1_resp = client.patch(
        f"/api/upload/tus/{upload_id}",
        content=part1_data,
        headers={
            "Tus-Resumable": "1.0.0",
            "Upload-Offset": "0",
            "Content-Type": "application/offset+octet-stream",
        },
    )
    assert patch1_resp.status_code == 204
    assert patch1_resp.headers["Upload-Offset"] == str(halfway)

    # 5. Simulate interruption: verify offset
    head_after_part1 = client.head(
        f"/api/upload/tus/{upload_id}",
        headers={"Tus-Resumable": "1.0.0"},
    )
    assert head_after_part1.status_code == 200
    current_offset = int(head_after_part1.headers["Upload-Offset"])
    assert current_offset == halfway

    # 6. Verify offset mismatch rejection (409 Conflict)
    conflict_resp = client.patch(
        f"/api/upload/tus/{upload_id}",
        content=b"corrupt chunk",
        headers={
            "Tus-Resumable": "1.0.0",
            "Upload-Offset": "0",  # Wrong offset!
            "Content-Type": "application/offset+octet-stream",
        },
    )
    assert conflict_resp.status_code == 409

    # 7. Resume upload from current offset (Part 2 to completion)
    part2_data = video_bytes[halfway:]
    patch2_resp = client.patch(
        f"/api/upload/tus/{upload_id}",
        content=part2_data,
        headers={
            "Tus-Resumable": "1.0.0",
            "Upload-Offset": str(halfway),
            "Content-Type": "application/offset+octet-stream",
        },
    )
    assert patch2_resp.status_code == 204
    assert patch2_resp.headers["Upload-Offset"] == str(total_length)
    assert patch2_resp.headers.get("Upload-Completed") == "true"
    video_id = patch2_resp.headers.get("Video-Id")
    assert video_id is not None

    # 8. Verify video record exists in Video API
    video_get = client.get(f"/api/videos/{video_id}")
    assert video_get.status_code == 200
    video_data = video_get.json()
    assert video_data["filename"] == "sample_resumable.mp4"
    assert video_data["status"] == "ready"
    assert video_data["duration"] > 1.5


def test_tus_delete():
    # Create upload session
    headers = {
        "Tus-Resumable": "1.0.0",
        "Upload-Length": "1000",
    }
    post_resp = client.post("/api/upload/tus", headers=headers)
    assert post_resp.status_code == 201
    upload_id = post_resp.headers["Location"].split("/")[-1]

    # Delete upload
    del_resp = client.delete(f"/api/upload/tus/{upload_id}", headers={"Tus-Resumable": "1.0.0"})
    assert del_resp.status_code == 204

    # Verify 404 after delete
    head_resp = client.head(f"/api/upload/tus/{upload_id}", headers={"Tus-Resumable": "1.0.0"})
    assert head_resp.status_code == 404
