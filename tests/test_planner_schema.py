from typing import Any

import pytest

from app.schemas.timeline import Item, Timeline, Track, TrackType
from app.schemas.timeline_ops import (
    AddCaptionOp,
    RippleDeleteOp,
    SetGradeOp,
    SetTransitionOp,
    SetVolumeOp,
    SplitOp,
    TrimOp,
)
from app.services.timeline_engine import apply
from app.services.tool_schema import (
    TimelineToolSchemaService,
    TimelineToolValidationError,
)


@pytest.fixture
def sample_timeline() -> Timeline:
    """Fixture providing a base timeline for engine round-trip verification."""
    item1 = Item(
        id="item_v1",
        source="vid_src_1",
        src_in=0,
        src_out=10000,
        start=0,
        volume=1.0,
    )
    item2 = Item(
        id="item_v2",
        source="vid_src_1",
        src_in=10000,
        src_out=25000,
        start=10000,
        volume=1.0,
    )
    track_v = Track(
        id="trk_video",
        type=TrackType.VIDEO,
        name="Main Video",
        items=[item1, item2],
    )
    return Timeline(
        id="tl_planner_test",
        video_id="vid_src_1",
        version=1,
        source_duration_ms=60000,
        tracks=[track_v],
    )


def test_generate_function_declarations_all_13_ops() -> None:
    """Validate that Gemini function declarations are generated for all 13 timeline operations."""
    declarations = TimelineToolSchemaService.get_tool_declarations()
    assert len(declarations) == 13

    expected_ops = {
        "add_track",
        "remove_track",
        "add_item",
        "remove_item",
        "split",
        "trim",
        "move",
        "ripple_delete",
        "set_volume",
        "set_grade",
        "set_transition",
        "add_caption",
        "update_caption",
    }
    generated_names = {decl["name"] for decl in declarations}
    assert generated_names == expected_ops

    for decl in declarations:
        assert isinstance(decl["name"], str) and decl["name"]
        assert isinstance(decl["description"], str) and decl["description"]
        params = decl["parameters"]
        assert params["type"] == "OBJECT"
        assert "properties" in params
        assert isinstance(params["properties"], dict)

        # Ensure no un-inlined $defs or $ref remain in parameters
        params_str = str(params)
        assert "$ref" not in params_str
        assert "$defs" not in params_str

        # Ensure internal discriminator 'type' was not exposed to LLM
        assert "type" not in params["properties"]


def test_gemini_tools_payload_format() -> None:
    """Ensure the top-level tools structure matches Gemini REST API specification."""
    payload = TimelineToolSchemaService.get_gemini_tools_payload()
    assert isinstance(payload, list)
    assert len(payload) == 1
    assert "functionDeclarations" in payload[0]
    assert len(payload[0]["functionDeclarations"]) == 13


def test_split_declaration_parameters() -> None:
    """Verify parameters schema for split operation."""
    decl = TimelineToolSchemaService.generate_function_declaration("split")
    props = decl["parameters"]["properties"]
    assert "track_id" in props
    assert props["track_id"]["type"] == "STRING"
    assert "item_id" in props
    assert props["item_id"]["type"] == "STRING"
    assert "split_time" in props
    assert props["split_time"]["type"] == "INTEGER"
    assert set(decl["parameters"]["required"]) == {"track_id", "item_id", "split_time"}


def test_parse_tool_call_valid_ops() -> None:
    """Verify parsing and validation of valid tool calls across operation models."""
    # 1. Split
    split_op = TimelineToolSchemaService.parse_tool_call(
        "split",
        {"track_id": "trk_video", "item_id": "item_v1", "split_time": 4000},
    )
    assert isinstance(split_op, SplitOp)
    assert split_op.type == "split"
    assert split_op.split_time == 4000

    # 2. Trim
    trim_op = TimelineToolSchemaService.parse_tool_call(
        "trim",
        {"track_id": "trk_video", "item_id": "item_v1", "new_src_in": 1000, "new_src_out": 8000},
    )
    assert isinstance(trim_op, TrimOp)
    assert trim_op.new_src_in == 1000
    assert trim_op.new_src_out == 8000

    # 3. Ripple delete
    rd_op = TimelineToolSchemaService.parse_tool_call(
        "ripple_delete",
        {"track_id": "trk_video", "item_id": "item_v1"},
    )
    assert isinstance(rd_op, RippleDeleteOp)
    assert rd_op.item_id == "item_v1"

    # 4. Set volume
    vol_op = TimelineToolSchemaService.parse_tool_call(
        "set_volume",
        {"track_id": "trk_video", "item_id": "item_v1", "volume": 0.5},
    )
    assert isinstance(vol_op, SetVolumeOp)
    assert vol_op.volume == 0.5

    # 5. Set grade
    grade_op = TimelineToolSchemaService.parse_tool_call(
        "set_grade",
        {
            "track_id": "trk_video",
            "item_id": "item_v1",
            "grade": {"preset": "cinematic", "brightness": 0.1, "contrast": 1.2, "saturation": 1.1},
        },
    )
    assert isinstance(grade_op, SetGradeOp)
    assert grade_op.grade.preset == "cinematic"

    # 6. Set transition
    trans_op = TimelineToolSchemaService.parse_tool_call(
        "set_transition",
        {
            "track_id": "trk_video",
            "item_id": "item_v2",
            "transition": {"type": "fade", "duration_ms": 600},
        },
    )
    assert isinstance(trans_op, SetTransitionOp)
    assert trans_op.transition.type == "fade"
    assert trans_op.transition.duration_ms == 600

    # 7. Add caption
    cap_op = TimelineToolSchemaService.parse_tool_call(
        "add_caption",
        {"text": "Test Caption", "start": 500, "duration_ms": 2500},
    )
    assert isinstance(cap_op, AddCaptionOp)
    assert cap_op.text == "Test Caption"
    assert cap_op.duration_ms == 2500


def test_parse_tool_call_rejects_missing_required_fields() -> None:
    """Missing required arguments must raise TimelineToolValidationError."""
    with pytest.raises(TimelineToolValidationError) as exc:
        TimelineToolSchemaService.parse_tool_call("split", {"track_id": "trk_1"})
    assert "split" in str(exc.value)


def test_parse_tool_call_rejects_negative_timestamps() -> None:
    """Negative millisecond timestamps must be rejected."""
    with pytest.raises(TimelineToolValidationError):
        TimelineToolSchemaService.parse_tool_call(
            "split",
            {"track_id": "trk_1", "item_id": "itm_1", "split_time": -500},
        )


def test_parse_tool_call_rejects_invalid_volume_range() -> None:
    """Volume multiplier outside [0.0, 2.0] must be rejected."""
    with pytest.raises(TimelineToolValidationError):
        TimelineToolSchemaService.parse_tool_call(
            "set_volume",
            {"track_id": "trk_1", "item_id": "itm_1", "volume": 3.5},
        )


def test_parse_tool_call_rejects_unknown_tool() -> None:
    """Unknown tool names must be rejected with helpful error."""
    with pytest.raises(TimelineToolValidationError) as exc:
        TimelineToolSchemaService.parse_tool_call("non_existent_tool", {})
    assert "Unknown tool name" in str(exc.value)


def test_parse_tool_call_rejects_forbidden_extra_fields() -> None:
    """Extra unexpected arguments must be rejected."""
    with pytest.raises(TimelineToolValidationError):
        TimelineToolSchemaService.parse_tool_call(
            "ripple_delete",
            {"track_id": "trk_1", "item_id": "itm_1", "unrecognized_flag": True},
        )


def test_validate_plan_ops_batch() -> None:
    """Validate batch operation sequence emitted by an AI planner."""
    raw_ops: list[dict[str, Any]] = [
        {
            "name": "split",
            "args": {"track_id": "trk_video", "item_id": "item_v1", "split_time": 4000},
        },
        {
            "type": "ripple_delete",
            "track_id": "trk_video",
            "item_id": "item_v1",
        },
        {
            "name": "set_volume",
            "args": {"track_id": "trk_video", "item_id": "item_v2", "volume": 0.8},
        },
    ]
    validated = TimelineToolSchemaService.validate_plan_ops(raw_ops)
    assert len(validated) == 3
    assert validated[0]["type"] == "split"
    assert validated[1]["type"] == "ripple_delete"
    assert validated[2]["type"] == "set_volume"


def test_round_trip_with_timeline_engine(sample_timeline: Timeline) -> None:
    """Verify that an operation validated by schema service applies cleanly in engine."""
    tool_name = "split"
    tool_args: dict[str, Any] = {
        "track_id": "trk_video",
        "item_id": "item_v1",
        "split_time": 4000,
        "new_item_id": "item_v1_split_right",
    }
    validated_op = TimelineToolSchemaService.parse_tool_call(
        name=tool_name,
        args=tool_args,
    )
    op_dict = validated_op.model_dump(mode="json")

    # Apply through TimelineEngine
    new_tl, inverse_op = apply(sample_timeline, op_dict)
    assert len(new_tl.tracks[0].items) == 3
    assert new_tl.tracks[0].items[0].src_out == 4000
    assert new_tl.tracks[0].items[1].id == "item_v1_split_right"

    # Restore via inverse
    restored_tl, _ = apply(new_tl, inverse_op)
    assert restored_tl == sample_timeline
