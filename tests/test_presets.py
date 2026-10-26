"""Tests for video editing presets and GET /api/presets endpoint (Task A12)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.preset_service import PresetService


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_preset_service_loads_presets() -> None:
    presets = PresetService.get_presets()

    # Grades
    grade_ids = {g.id for g in presets.grades}
    assert "none" in grade_ids
    assert "cinematic" in grade_ids
    assert "warm" in grade_ids
    assert "vibrant" in grade_ids
    assert "cool" in grade_ids
    assert "bw" in grade_ids

    # Transitions
    trans_ids = {t.id for t in presets.transitions}
    assert "none" in trans_ids
    assert "fade" in trans_ids
    assert "wipeleft" in trans_ids
    assert "wiperight" in trans_ids
    assert "slideup" in trans_ids

    # Animations
    anim_ids = {a.id for a in presets.animations}
    assert "highlight" in anim_ids
    assert "pop" in anim_ids
    assert "fade" in anim_ids
    assert "bounce" in anim_ids
    assert "none" in anim_ids

    # Fonts
    font_names = {f.name for f in presets.fonts}
    assert "Arial" in font_names
    assert "Impact" in font_names
    assert "Montserrat" in font_names


def test_preset_service_fallback_to_defaults(tmp_path: Path) -> None:
    # Empty directory has no JSON files
    empty_dir = tmp_path / "empty_presets"
    empty_dir.mkdir()

    presets = PresetService.get_presets(presets_dir=empty_dir)
    assert len(presets.grades) > 0
    assert len(presets.transitions) > 0
    assert len(presets.animations) > 0
    assert len(presets.fonts) > 0


def test_api_get_presets(client: TestClient) -> None:
    response = client.get("/api/presets")
    assert response.status_code == 200
    data = response.json()

    assert "grades" in data
    assert "transitions" in data
    assert "animations" in data
    assert "fonts" in data

    assert len(data["grades"]) >= 6
    assert len(data["transitions"]) >= 5
    assert len(data["animations"]) >= 5
    assert len(data["fonts"]) >= 5

    # Check structure of a grade preset
    first_grade = data["grades"][0]
    assert "id" in first_grade
    assert "name" in first_grade
    assert "description" in first_grade
    assert "brightness" in first_grade
    assert "contrast" in first_grade
    assert "saturation" in first_grade

    # Check structure of a transition preset
    first_trans = data["transitions"][0]
    assert "id" in first_trans
    assert "name" in first_trans
    assert "default_duration" in first_trans

    # Check structure of an animation preset
    first_anim = data["animations"][0]
    assert "id" in first_anim
    assert "recommended_font_size" in first_anim

    # Check structure of a font preset
    first_font = data["fonts"][0]
    assert "id" in first_font
    assert "category" in first_font
    assert "is_system" in first_font
