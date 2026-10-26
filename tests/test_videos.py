import shutil
import subprocess
from collections.abc import Generator
from pathlib import Path

import pytest
import static_ffmpeg
from fastapi.testclient import TestClient

from app.main import app
from app.tasks.celery_app import celery_app

static_ffmpeg.add_paths()


@pytest.fixture(autouse=True)
def configure_celery_eager() -> Generator[None, None, None]:
    original_eager = celery_app.conf.task_always_eager
    original_backend = celery_app.conf.result_backend
    celery_app.conf.task_always_eager = True
    celery_app.conf.result_backend = "cache+memory://"
    yield
    celery_app.conf.task_always_eager = original_eager
    celery_app.conf.result_backend = original_backend


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(scope="session")
def sample_landscape_video(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Generate a 1280x720 landscape test video."""
    tmp_dir = tmp_path_factory.mktemp("videos")
    file_path = tmp_dir / "landscape_test.mp4"
    ffmpeg = shutil.which("ffmpeg")
    assert ffmpeg, "ffmpeg executable must be available"

    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=1280x720:d=1.5",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=44100:cl=mono",
            "-t",
            "1.5",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            str(file_path),
        ],
        check=True,
        capture_output=True,
    )
    return file_path


@pytest.fixture(scope="session")
def sample_portrait_video(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Generate a 720x1280 portrait test video."""
    tmp_dir = tmp_path_factory.mktemp("videos")
    file_path = tmp_dir / "portrait_test.mp4"
    ffmpeg = shutil.which("ffmpeg")
    assert ffmpeg, "ffmpeg executable must be available"

    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=red:s=720x1280:d=1.0",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=44100:cl=mono",
            "-t",
            "1.0",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            str(file_path),
        ],
        check=True,
        capture_output=True,
    )
    return file_path


def test_upload_landscape_video(client: TestClient, sample_landscape_video: Path) -> None:
    with open(sample_landscape_video, "rb") as f:
        response = client.post(
            "/api/videos",
            files={"file": ("landscape_test.mp4", f, "video/mp4")},
        )
    assert response.status_code == 201
    data = response.json()
    assert data["filename"] == "landscape_test.mp4"
    assert data["orientation"] == "landscape"
    assert data["width"] == 1280
    assert data["height"] == 720
    assert data["duration"] >= 1.4
    assert Path(data["file_path"]).exists()

    # Clean up created video
    del_res = client.delete(f"/api/videos/{data['id']}")
    assert del_res.status_code == 200
    assert not Path(data["file_path"]).exists()


def test_upload_portrait_video(client: TestClient, sample_portrait_video: Path) -> None:
    with open(sample_portrait_video, "rb") as f:
        response = client.post(
            "/api/videos",
            files={"file": ("portrait_test.mp4", f, "video/mp4")},
        )
    assert response.status_code == 201
    data = response.json()
    assert data["filename"] == "portrait_test.mp4"
    assert data["orientation"] == "portrait"
    assert data["width"] == 720
    assert data["height"] == 1280
    assert data["duration"] >= 0.9

    # Clean up
    client.delete(f"/api/videos/{data['id']}")


def test_upload_invalid_extension(client: TestClient) -> None:
    response = client.post(
        "/api/videos",
        files={"file": ("test.txt", b"plain text", "text/plain")},
    )
    assert response.status_code == 400
    assert "Unsupported file format" in response.json()["detail"]


def test_get_and_list_videos(client: TestClient, sample_landscape_video: Path) -> None:
    # Upload video
    with open(sample_landscape_video, "rb") as f:
        res = client.post(
            "/api/videos",
            files={"file": ("list_test.mp4", f, "video/mp4")},
        )
    assert res.status_code == 201
    video_id = res.json()["id"]

    # List videos
    list_res = client.get("/api/videos")
    assert list_res.status_code == 200
    list_data = list_res.json()
    assert list_data["total"] >= 1
    assert any(v["id"] == video_id for v in list_data["videos"])

    # Get single video
    get_res = client.get(f"/api/videos/{video_id}")
    assert get_res.status_code == 200
    assert get_res.json()["id"] == video_id

    # Get non-existent
    assert client.get("/api/videos/non-existent-id").status_code == 404

    # Delete video
    assert client.delete(f"/api/videos/{video_id}").status_code == 200
    assert client.get(f"/api/videos/{video_id}").status_code == 404
