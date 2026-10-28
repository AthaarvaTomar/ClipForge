import base64
import json
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.config import settings
from app.core.logging import logger
from app.models.video import Video
from app.services.video_probe import probe_video


class TusError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


class TusService:
    def __init__(self, upload_dir: Path | None = None) -> None:
        self.upload_dir = upload_dir or settings.UPLOAD_DIR
        self.tus_dir = self.upload_dir / "tus"
        self.tus_dir.mkdir(parents=True, exist_ok=True)

    def _info_path(self, upload_id: str) -> Path:
        return self.tus_dir / f"{upload_id}.info"

    def _part_path(self, upload_id: str) -> Path:
        return self.tus_dir / f"{upload_id}.part"

    def parse_metadata(self, metadata_header: str | None) -> dict[str, str]:
        """Parse comma-separated key-value Tus metadata (e.g. filename dGVzdC5tcDQ=)."""
        if not metadata_header:
            return {}
        result: dict[str, str] = {}
        for item in metadata_header.split(","):
            parts = item.strip().split(" ", 1)
            key = parts[0].strip()
            if not key:
                continue
            if len(parts) > 1:
                try:
                    val = base64.b64decode(parts[1].strip()).decode("utf-8", errors="replace")
                except Exception:
                    val = parts[1].strip()
            else:
                val = ""
            result[key] = val
        return result

    def create_upload(self, upload_length: int, metadata_header: str | None = None) -> str:
        max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
        if upload_length > max_bytes:
            raise TusError(
                f"Upload length {upload_length} exceeds limit of {settings.MAX_UPLOAD_SIZE_MB}MB",
                status_code=413,
            )

        upload_id = str(uuid.uuid4())
        meta = self.parse_metadata(metadata_header)

        info: dict[str, Any] = {
            "upload_id": upload_id,
            "upload_length": upload_length,
            "offset": 0,
            "metadata": meta,
        }

        part_p = self._part_path(upload_id)
        part_p.touch(exist_ok=True)

        info_p = self._info_path(upload_id)
        info_p.write_text(json.dumps(info), encoding="utf-8")

        logger.info(f"Created Tus upload session {upload_id} (length={upload_length})")
        return upload_id

    def get_upload_info(self, upload_id: str) -> dict[str, Any] | None:
        info_p = self._info_path(upload_id)
        part_p = self._part_path(upload_id)

        if not info_p.exists() or not part_p.exists():
            return None

        try:
            info = json.loads(info_p.read_text(encoding="utf-8"))
            # Sync offset with actual file size on disk
            info["offset"] = part_p.stat().st_size
            return info
        except Exception as e:
            logger.warning(f"Failed to read Tus info {info_p}: {e}")
            return None

    def append_chunk(self, upload_id: str, offset: int, chunk: bytes) -> tuple[int, bool]:
        """Appends chunk at given offset. Returns (new_offset, is_completed)."""
        info = self.get_upload_info(upload_id)
        if not info:
            raise TusError("Upload not found", status_code=404)

        current_offset = info["offset"]
        if offset != current_offset:
            raise TusError(
                f"Offset mismatch: expected {current_offset}, received {offset}",
                status_code=409,
            )

        part_p = self._part_path(upload_id)
        with open(part_p, "ab") as f:
            f.write(chunk)

        new_offset = part_p.stat().st_size
        upload_length = info["upload_length"]

        info["offset"] = new_offset
        self._info_path(upload_id).write_text(json.dumps(info), encoding="utf-8")

        is_completed = new_offset >= upload_length
        return new_offset, is_completed

    def finalize_upload(self, upload_id: str, db: Session) -> Video:
        info = self.get_upload_info(upload_id)
        if not info:
            raise TusError("Upload not found", status_code=404)

        part_p = self._part_path(upload_id)
        meta = info.get("metadata", {})
        original_filename = meta.get("filename", f"upload_{upload_id}.mp4")

        # Determine extension
        ext = Path(original_filename).suffix.lower()
        if ext not in [".mp4", ".mov", ".mkv"]:
            ext = ".mp4"

        video_id = str(uuid.uuid4())
        final_destination = self.upload_dir / f"{video_id}{ext}"
        self.upload_dir.mkdir(parents=True, exist_ok=True)

        # Move completed part file to final destination
        part_p.replace(final_destination)

        # Probe video properties
        probe_meta = probe_video(final_destination)

        video = Video(
            id=video_id,
            filename=original_filename,
            file_path=str(final_destination.resolve()),
            duration=probe_meta.duration,
            width=probe_meta.width,
            height=probe_meta.height,
            fps=probe_meta.fps,
            orientation=probe_meta.orientation,
            status="ready",
        )
        db.add(video)
        db.commit()
        db.refresh(video)

        # Clean up info file
        info_p = self._info_path(upload_id)
        if info_p.exists():
            info_p.unlink()

        logger.info(f"Finalized Tus upload {upload_id} -> Video {video_id} ({video.filename})")
        return video

    def delete_upload(self, upload_id: str) -> bool:
        part_p = self._part_path(upload_id)
        info_p = self._info_path(upload_id)
        deleted = False

        if part_p.exists():
            part_p.unlink()
            deleted = True
        if info_p.exists():
            info_p.unlink()
            deleted = True

        return deleted
