from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.config import settings
from app.core.database import get_db
from app.services.tus_service import TusError, TusService

router = APIRouter(prefix="/upload/tus", tags=["Upload (Tus)"])
tus_service = TusService()

TUS_VERSION = "1.0.0"
TUS_EXTENSIONS = "creation,termination"


@router.options("")
@router.options("/{upload_id}")
def tus_options() -> Response:
    """Return supported Tus protocol capabilities."""
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    headers = {
        "Tus-Resumable": TUS_VERSION,
        "Tus-Version": TUS_VERSION,
        "Tus-Max-Size": str(max_bytes),
        "Tus-Extension": TUS_EXTENSIONS,
    }
    return Response(status_code=status.HTTP_204_NO_CONTENT, headers=headers)


@router.post("", status_code=status.HTTP_201_CREATED)
def tus_create_upload(
    upload_length: int | None = Header(None, alias="Upload-Length"),
    upload_metadata: str | None = Header(None, alias="Upload-Metadata"),
    tus_resumable: str | None = Header(None, alias="Tus-Resumable"),
) -> Response:
    """Create a new Tus upload session (Creation extension)."""
    if upload_length is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Upload-Length header is required",
        )

    try:
        upload_id = tus_service.create_upload(
            upload_length=upload_length,
            metadata_header=upload_metadata,
        )
    except TusError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e

    location = f"/api/upload/tus/{upload_id}"
    headers = {
        "Location": location,
        "Tus-Resumable": TUS_VERSION,
        "Upload-Offset": "0",
    }
    return Response(status_code=status.HTTP_201_CREATED, headers=headers)


@router.head("/{upload_id}")
def tus_get_upload_status(upload_id: str) -> Response:
    """Get current offset and length for an active upload."""
    info = tus_service.get_upload_info(upload_id)
    if not info:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Upload not found")

    headers = {
        "Upload-Offset": str(info["offset"]),
        "Upload-Length": str(info["upload_length"]),
        "Tus-Resumable": TUS_VERSION,
        "Cache-Control": "no-store",
    }
    return Response(status_code=status.HTTP_200_OK, headers=headers)


@router.patch("/{upload_id}", status_code=status.HTTP_204_NO_CONTENT)
async def tus_upload_chunk(
    upload_id: str,
    request: Request,
    upload_offset: int | None = Header(None, alias="Upload-Offset"),
    content_type: str | None = Header(None, alias="Content-Type"),
    tus_resumable: str | None = Header(None, alias="Tus-Resumable"),
    db: Session = Depends(get_db),
) -> Response:
    """Append byte chunk to the upload resource at the specified offset."""
    if upload_offset is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Upload-Offset header is required",
        )

    chunk = await request.body()
    if not chunk:
        # 0-byte patch check
        info = tus_service.get_upload_info(upload_id)
        if not info:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Upload not found")
        headers = {
            "Upload-Offset": str(info["offset"]),
            "Tus-Resumable": TUS_VERSION,
        }
        return Response(status_code=status.HTTP_204_NO_CONTENT, headers=headers)

    try:
        new_offset, is_completed = tus_service.append_chunk(
            upload_id=upload_id,
            offset=upload_offset,
            chunk=chunk,
        )
    except TusError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e)) from e

    headers = {
        "Upload-Offset": str(new_offset),
        "Tus-Resumable": TUS_VERSION,
    }

    if is_completed:
        try:
            video = tus_service.finalize_upload(upload_id, db=db)
            headers["Video-Id"] = video.id
            headers["Upload-Completed"] = "true"
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to finalize completed video upload: {e}",
            ) from e

    return Response(status_code=status.HTTP_204_NO_CONTENT, headers=headers)


@router.delete("/{upload_id}", status_code=status.HTTP_204_NO_CONTENT)
def tus_delete_upload(upload_id: str) -> Response:
    """Cancel and terminate an active upload (Termination extension)."""
    deleted = tus_service.delete_upload(upload_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Upload not found")

    headers = {"Tus-Resumable": TUS_VERSION}
    return Response(status_code=status.HTTP_204_NO_CONTENT, headers=headers)
