"""Presets endpoint providing available video editing presets (Task A12)."""

from fastapi import APIRouter

from app.schemas.preset import PresetsResponse
from app.services.preset_service import PresetService

router = APIRouter(prefix="/presets", tags=["Presets"])


@router.get(
    "",
    response_model=PresetsResponse,
    summary="List editing presets",
)
def get_presets() -> PresetsResponse:
    """Retrieve available color grades, transitions, caption animations, and fonts."""
    return PresetService.get_presets()
