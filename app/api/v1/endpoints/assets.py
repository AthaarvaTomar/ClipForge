"""Media Asset Library API endpoints (Milestone M1)."""

from __future__ import annotations

import mimetypes
import shutil
import uuid
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.core.database import get_db
from app.schemas.asset import (
    AssetListResponse,
    AssetResponse,
    ImportAssetRequest,
    StockSearchResponse,
)
from app.services.stock_asset_service import StockAssetService

router = APIRouter(prefix="/assets", tags=["assets"])


@router.get(
    "/search",
    response_model=StockSearchResponse,
    summary="Search stock B-roll video or images across Pexels or Pixabay with attribution",
)
def search_stock_media(
    q: str = Query(
        ..., min_length=1, description="Search query keyword (e.g., 'technology', 'nature')"
    ),
    media_type: Literal["video", "image"] = Query("video", description="Type of media to search"),
    provider: Literal["pexels", "pixabay"] = Query("pexels", description="Stock media provider"),
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(10, ge=1, le=50, description="Items per page"),
) -> StockSearchResponse:
    """Search stock footage and images with photographer / contributor attribution."""
    return StockAssetService.search(
        query=q,
        media_type=media_type,
        provider=provider,
        page=page,
        per_page=per_page,
    )


@router.post(
    "/import",
    response_model=AssetResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Import an external stock item into the local asset library",
)
def import_stock_asset(
    payload: ImportAssetRequest,
    db: Session = Depends(get_db),
) -> AssetResponse:
    """Download a stock clip or image, store it locally, and register attribution."""
    asset = StockAssetService.import_stock_asset(
        db=db,
        stock_item=payload.stock_item,
        custom_name=payload.custom_name,
    )
    return AssetResponse.model_validate(asset)


@router.post(
    "/upload",
    response_model=AssetResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a local image, video, or audio file into the asset library",
)
def upload_asset(
    file: UploadFile = File(..., description="Media file to upload"),
    name: str | None = Form(None, description="Custom asset name"),
    media_type: Literal["video", "image", "audio", "music"] | None = Form(
        None, description="Optional explicit media type"
    ),
    db: Session = Depends(get_db),
) -> AssetResponse:
    """Upload user-provided media asset into the library."""
    filename = file.filename or "uploaded_media"
    ext = Path(filename).suffix.lower()

    # Deduce media type if not provided
    if not media_type:
        if ext in (".mp4", ".mov", ".mkv", ".webm", ".avi"):
            media_type = "video"
        elif ext in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
            media_type = "image"
        elif ext in (".mp3", ".wav", ".aac", ".flac", ".ogg", ".m4a"):
            media_type = (
                "music" if "music" in filename.lower() or "bgm" in filename.lower() else "audio"
            )
        else:
            media_type = "video"

    assets_dir = settings.UPLOAD_DIR / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    target_path = assets_dir / f"{uuid.uuid4().hex}{ext}"

    with target_path.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    asset = StockAssetService.create_uploaded_asset(
        db=db,
        file_path=target_path,
        name=name or Path(filename).stem,
        media_type=media_type,
    )
    return AssetResponse.model_validate(asset)


@router.get(
    "",
    response_model=AssetListResponse,
    summary="List media assets in library",
)
def list_assets(
    media_type: Literal["video", "image", "audio", "music"] | None = Query(
        None, description="Filter by media type"
    ),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
) -> AssetListResponse:
    """Retrieve all assets stored in project library."""
    items, total = StockAssetService.list_assets(
        db=db,
        media_type=media_type,
        skip=skip,
        limit=limit,
    )
    return AssetListResponse(
        total=total,
        items=[AssetResponse.model_validate(item) for item in items],
    )


@router.get(
    "/{id}",
    response_model=AssetResponse,
    summary="Get media asset details",
)
def get_asset(
    id: str,
    db: Session = Depends(get_db),
) -> AssetResponse:
    """Retrieve single asset by ID."""
    asset = StockAssetService.get_asset(db, id)
    if not asset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Asset '{id}' not found")
    return AssetResponse.model_validate(asset)


@router.get(
    "/{id}/file",
    summary="Download or stream asset file",
)
def get_asset_file(
    id: str,
    db: Session = Depends(get_db),
) -> FileResponse:
    """Stream asset file content."""
    asset = StockAssetService.get_asset(db, id)
    if not asset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Asset '{id}' not found")

    file_path = Path(asset.file_path)
    if not file_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Asset file '{asset.file_path}' not found on server",
        )

    mime_type, _ = mimetypes.guess_type(str(file_path))
    return FileResponse(
        path=file_path,
        media_type=mime_type or "application/octet-stream",
        filename=f"{asset.name}{file_path.suffix}",
    )
