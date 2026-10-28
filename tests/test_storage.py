import io
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.config import settings
from app.services.storage_service import (
    LocalStorageService,
    MinIOStorageService,
    get_storage,
)


def test_local_storage_lifecycle(tmp_path: Path):
    storage = LocalStorageService(base_dir=tmp_path)
    test_file = tmp_path / "sample.txt"
    content = b"ClipForge Local Storage Test"

    # Save bytes
    ref = storage.save_file(content, test_file)
    assert ref is not None
    assert storage.exists(test_file)
    assert storage.read_file(test_file) == content
    assert storage.get_local_path(test_file) == test_file.resolve()

    # Save stream
    stream_file = tmp_path / "stream.bin"
    stream = io.BytesIO(b"Stream data 12345")
    storage.save_file(stream, stream_file)
    assert storage.read_file(stream_file) == b"Stream data 12345"

    # URL
    url = storage.get_url(test_file)
    assert "sample.txt" in url

    # Delete
    assert storage.delete_file(test_file) is True
    assert not storage.exists(test_file)


def test_minio_storage_lifecycle(tmp_path: Path):
    with patch("app.services.storage_service.Minio") as mock_minio_cls:
        mock_client = MagicMock()
        mock_minio_cls.return_value = mock_client
        mock_client.bucket_exists.return_value = False

        storage = MinIOStorageService(
            endpoint="mock-minio:9000",
            access_key="test_key",
            secret_key="test_secret",
            bucket="test-bucket",
            secure=False,
        )

        mock_client.make_bucket.assert_called_once_with("test-bucket")

        # Save file
        test_path = tmp_path / "uploads" / "video.mp4"
        content = b"fake video content"
        res = storage.save_file(content, test_path)
        assert res.startswith("s3://test-bucket/")
        assert mock_client.put_object.called

        # Exists
        mock_client.stat_object.return_value = MagicMock()
        assert storage.exists(test_path) is True

        # Delete
        storage.delete_file(test_path)
        assert mock_client.remove_object.called

        # URL
        mock_client.presigned_get_object.return_value = "http://mock-minio:9000/test-bucket/video.mp4?sig=xyz"
        url = storage.get_url(test_path)
        assert "http://mock-minio:9000/test-bucket" in url


def test_storage_switching_by_env_var():
    # Test local backend
    with patch.object(settings, "STORAGE_BACKEND", "local"):
        svc_local = get_storage("local")
        assert isinstance(svc_local, LocalStorageService)

    # Test MinIO backend
    with patch.object(settings, "STORAGE_BACKEND", "minio"):
        with patch("app.services.storage_service.Minio") as mock_minio_cls:
            mock_client = MagicMock()
            mock_minio_cls.return_value = mock_client
            mock_client.bucket_exists.return_value = True

            svc_minio = get_storage("minio")
            assert isinstance(svc_minio, MinIOStorageService)
