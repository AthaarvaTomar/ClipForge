import io
import os
import shutil
from abc import ABC, abstractmethod
from pathlib import Path
from typing import BinaryIO

from app.config import settings
from app.core.logging import logger

try:
    from minio import Minio
    from minio.error import S3Error
    HAS_MINIO = True
except ImportError:
    HAS_MINIO = False
    Minio = None  # type: ignore
    S3Error = Exception  # type: ignore


class StorageServiceError(Exception):
    """Base exception for storage operations."""
    pass


class BaseStorageService(ABC):
    """Abstract storage interface supporting local and object storage (MinIO/S3)."""

    @abstractmethod
    def save_file(self, content: bytes | BinaryIO, dest_path: str | Path) -> str:
        """Save file content and return storage reference/path."""
        pass

    @abstractmethod
    def get_local_path(self, path: str | Path) -> Path:
        """Get or download a local filesystem path for the given file."""
        pass

    @abstractmethod
    def read_file(self, path: str | Path) -> bytes:
        """Read file content as bytes."""
        pass

    @abstractmethod
    def delete_file(self, path: str | Path) -> bool:
        """Delete file from storage. Returns True if deleted or did not exist."""
        pass

    @abstractmethod
    def exists(self, path: str | Path) -> bool:
        """Check if file exists in storage."""
        pass

    @abstractmethod
    def get_url(self, path: str | Path) -> str:
        """Get public or presigned URL for the file."""
        pass


class LocalStorageService(BaseStorageService):
    """Local disk storage implementation."""

    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = base_dir or Path(".")

    def save_file(self, content: bytes | BinaryIO, dest_path: str | Path) -> str:
        p = Path(dest_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, (bytes, bytearray)):
            p.write_bytes(content)
        else:
            with open(p, "wb") as f:
                shutil.copyfileobj(content, f)
        return str(p.resolve())

    def get_local_path(self, path: str | Path) -> Path:
        p = Path(path)
        return p.resolve()

    def read_file(self, path: str | Path) -> bytes:
        p = self.get_local_path(path)
        if not p.exists():
            raise StorageServiceError(f"File not found: {p}")
        return p.read_bytes()

    def delete_file(self, path: str | Path) -> bool:
        p = Path(path)
        if p.exists():
            try:
                p.unlink()
                return True
            except OSError as e:
                logger.warning(f"Failed to unlink {p}: {e}")
                return False
        return True

    def exists(self, path: str | Path) -> bool:
        return Path(path).exists()

    def get_url(self, path: str | Path) -> str:
        # For local storage, returns the normalized relative path
        p = Path(path)
        return f"/files/{p.as_posix()}"


class MinIOStorageService(BaseStorageService):
    """MinIO / S3 object storage implementation."""

    def __init__(
        self,
        endpoint: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
        bucket: str | None = None,
        secure: bool | None = None,
    ) -> None:
        if not HAS_MINIO:
            raise StorageServiceError("minio package is not installed.")

        self.endpoint = endpoint or settings.MINIO_ENDPOINT
        self.access_key = access_key or settings.MINIO_ACCESS_KEY
        self.secret_key = secret_key or settings.MINIO_SECRET_KEY
        self.bucket = bucket or settings.MINIO_BUCKET
        self.secure = secure if secure is not None else settings.MINIO_SECURE

        self.client = Minio(
            self.endpoint,
            access_key=self.access_key,
            secret_key=self.secret_key,
            secure=self.secure,
        )
        self.cache_dir = Path("./data/minio_cache")
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        self._ensure_bucket()

    def _ensure_bucket(self) -> None:
        try:
            if not self.client.bucket_exists(self.bucket):
                self.client.make_bucket(self.bucket)
                logger.info(f"Created MinIO bucket '{self.bucket}'")
        except Exception as e:
            logger.warning(f"MinIO bucket check failed (server may be offline): {e}")

    def _object_key(self, path: str | Path) -> str:
        # Convert local path to normalized S3 object key
        s = str(path).replace("\\", "/").strip("./").lstrip("/")
        return s

    def save_file(self, content: bytes | BinaryIO, dest_path: str | Path) -> str:
        obj_key = self._object_key(dest_path)

        if isinstance(content, (bytes, bytearray)):
            data_bytes = bytes(content)
            data_stream = io.BytesIO(data_bytes)
            length = len(data_bytes)
        else:
            content.seek(0, os.SEEK_END)
            length = content.tell()
            content.seek(0)
            data_stream = content  # type: ignore

        try:
            self.client.put_object(
                bucket_name=self.bucket,
                object_name=obj_key,
                data=data_stream,
                length=length,
            )
            logger.info(
                f"Uploaded object '{obj_key}' to MinIO bucket '{self.bucket}' ({length} bytes)"
            )
        except Exception as e:
            logger.error(f"Failed to upload to MinIO: {e}")
            raise StorageServiceError(f"MinIO upload error: {e}") from e

        # Also write locally for immediate zero-latency processing
        local_p = Path(dest_path)
        local_p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, (bytes, bytearray)):
            local_p.write_bytes(content)
        else:
            data_stream.seek(0)
            with open(local_p, "wb") as f:
                shutil.copyfileobj(data_stream, f)

        return f"s3://{self.bucket}/{obj_key}"

    def get_local_path(self, path: str | Path) -> Path:
        local_p = Path(path)
        if local_p.exists():
            return local_p.resolve()

        obj_key = self._object_key(path)
        cached_p = self.cache_dir / obj_key
        cached_p.parent.mkdir(parents=True, exist_ok=True)

        try:
            self.client.fget_object(self.bucket, obj_key, str(cached_p))
            return cached_p.resolve()
        except Exception as e:
            logger.error(f"Failed to download object '{obj_key}' from MinIO: {e}")
            raise StorageServiceError(f"MinIO download error: {e}") from e

    def read_file(self, path: str | Path) -> bytes:
        obj_key = self._object_key(path)
        try:
            response = self.client.get_object(self.bucket, obj_key)
            try:
                return response.read()
            finally:
                response.close()
                response.release_conn()
        except Exception:
            # Fallback to local path if present
            local_p = Path(path)
            if local_p.exists():
                return local_p.read_bytes()
            raise

    def delete_file(self, path: str | Path) -> bool:
        obj_key = self._object_key(path)
        try:
            self.client.remove_object(self.bucket, obj_key)
        except Exception as e:
            logger.warning(f"MinIO remove_object '{obj_key}' error: {e}")

        local_p = Path(path)
        if local_p.exists():
            try:
                local_p.unlink()
            except OSError:
                pass
        return True

    def exists(self, path: str | Path) -> bool:
        obj_key = self._object_key(path)
        try:
            self.client.stat_object(self.bucket, obj_key)
            return True
        except Exception:
            return Path(path).exists()

    def get_url(self, path: str | Path) -> str:
        obj_key = self._object_key(path)
        try:
            from datetime import timedelta
            url = self.client.presigned_get_object(self.bucket, obj_key, expires=timedelta(hours=2))
            return str(url)
        except Exception:
            protocol = "https" if self.secure else "http"
            return f"{protocol}://{self.endpoint}/{self.bucket}/{obj_key}"


_storage_instances: dict[str, BaseStorageService] = {}


def get_storage(backend: str | None = None) -> BaseStorageService:
    """Factory returning active storage service based on backend ('local' or 'minio')."""
    selected_backend = (backend or settings.STORAGE_BACKEND).lower().strip()

    if selected_backend in ("minio", "s3"):
        if "minio" not in _storage_instances:
            _storage_instances["minio"] = MinIOStorageService()
        return _storage_instances["minio"]

    if "local" not in _storage_instances:
        _storage_instances["local"] = LocalStorageService()
    return _storage_instances["local"]
