import shutil
import subprocess
import tempfile
from collections.abc import Generator
from pathlib import Path

import pytest

from app.schemas.edit_spec import (
    CutSegment,
    EditSpec,
    GradeSpec,
    ReframeSpec,
    TransitionSpec,
)
from app.services.ffmpeg_builder import (
    FFmpegBuilder,
    FFmpegBuilderError,
    build_cuts_filter,
    build_grade_filter,
    build_reframe_filter,
    get_target_resolution,
)
from app.services.video_probe import probe_video


@pytest.fixture(scope="module")
def sample_16_9_video() -> Generator[Path, None, None]:
    """Generate a 2-second 1280x720 (16:9) video file with sine audio."""
    ffmpeg_bin = shutil.which("ffmpeg")
    assert ffmpeg_bin is not None, "ffmpeg must be installed"

    tmp_dir = Path(tempfile.mkdtemp(prefix="test_16_9_"))
    video_path = tmp_dir / "sample_16_9.mp4"

    cmd = [
        ffmpeg_bin,
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc=duration=3:size=1280x720:rate=30",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=1000:duration=3",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        str(video_path),
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    yield video_path

    shutil.rmtree(tmp_dir, ignore_errors=True)


@pytest.fixture(scope="module")
def sample_9_16_video() -> Generator[Path, None, None]:
    """Generate a 2-second 720x1280 (9:16) video file with sine audio."""
    ffmpeg_bin = shutil.which("ffmpeg")
    assert ffmpeg_bin is not None, "ffmpeg must be installed"

    tmp_dir = Path(tempfile.mkdtemp(prefix="test_9_16_"))
    video_path = tmp_dir / "sample_9_16.mp4"

    cmd = [
        ffmpeg_bin,
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc=duration=3:size=720x1280:rate=30",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=800:duration=3",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        str(video_path),
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    yield video_path

    shutil.rmtree(tmp_dir, ignore_errors=True)


@pytest.fixture(scope="module")
def sample_no_audio_video() -> Generator[Path, None, None]:
    """Generate a 2-second 640x360 video with NO audio track."""
    ffmpeg_bin = shutil.which("ffmpeg")
    assert ffmpeg_bin is not None, "ffmpeg must be installed"

    tmp_dir = Path(tempfile.mkdtemp(prefix="test_no_audio_"))
    video_path = tmp_dir / "no_audio.mp4"

    cmd = [
        ffmpeg_bin,
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc=duration=2:size=640x360:rate=30",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-an",
        str(video_path),
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    yield video_path

    shutil.rmtree(tmp_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Filter Generator Unit Tests
# ---------------------------------------------------------------------------


def test_target_resolution_mapping() -> None:
    assert get_target_resolution("9:16", 1920, 1080) == (1080, 1920)
    assert get_target_resolution("16:9", 1080, 1920) == (1920, 1080)
    assert get_target_resolution("1:1", 1920, 1080) == (1080, 1080)
    assert get_target_resolution("4:5", 1920, 1080) == (1080, 1350)


def test_build_cuts_filter_single() -> None:
    cuts = [CutSegment(start=2.0, end=7.5)]
    lines, v_out, a_out = build_cuts_filter(cuts, has_audio=True)
    assert len(lines) == 2
    assert v_out == "v_cut_0"
    assert a_out == "a_cut_0"
    assert "trim=start=2.0:end=7.5" in lines[0]


def test_build_cuts_filter_multi() -> None:
    cuts = [
        CutSegment(start=1.0, end=3.0),
        CutSegment(start=5.0, end=8.0),
    ]
    lines, v_out, a_out = build_cuts_filter(cuts, has_audio=True)
    assert len(lines) == 5  # 2 video trims, 2 audio trims, 1 concat
    assert v_out == "v_cat"
    assert a_out == "a_cat"
    assert "concat=n=2:v=1:a=1" in lines[-1]


def test_build_reframe_filter_crop() -> None:
    # 16:9 (1920x1080) to 9:16 (1080x1920)
    lines = build_reframe_filter(
        in_label="v_in",
        out_label="v_out",
        source_width=1920,
        source_height=1080,
        target_width=1080,
        target_height=1920,
        strategy="crop",
        crop_x_offset=0.25,
    )
    assert len(lines) == 1
    assert "scale=1080:1920:force_original_aspect_ratio=increase" in lines[0]
    assert "crop=1080:1920" in lines[0]
    assert "0.25" in lines[0]


def test_build_reframe_filter_blur_bg() -> None:
    lines = build_reframe_filter(
        in_label="v_in",
        out_label="v_out",
        source_width=1920,
        source_height=1080,
        target_width=1080,
        target_height=1920,
        strategy="blur-bg",
    )
    assert len(lines) == 4
    assert any("split=2" in line for line in lines)
    assert any("boxblur=" in line for line in lines)
    assert any("overlay=(W-w)/2:(H-h)/2" in line for line in lines)


def test_build_grade_filter_presets_and_custom() -> None:
    # Preset
    grade_preset = GradeSpec(preset="cinematic")
    lines_p = build_grade_filter("in", "out", grade_preset)
    assert "eq=" in lines_p[0]
    assert "colorbalance=" in lines_p[0]

    # Custom
    grade_custom = GradeSpec(preset="none", brightness=0.1, contrast=1.2, saturation=1.3)
    lines_c = build_grade_filter("in", "out", grade_custom)
    assert "brightness=0.100" in lines_c[0]
    assert "contrast=1.200" in lines_c[0]
    assert "saturation=1.300" in lines_c[0]

    # None
    grade_none = GradeSpec(preset="none")
    lines_n = build_grade_filter("in", "out", grade_none)
    assert "null" in lines_n[0]


# ---------------------------------------------------------------------------
# End-to-End Rendering Tests (16:9 <-> 9:16 and Same-Aspect)
# ---------------------------------------------------------------------------


def test_render_16_9_to_9_16_crop(sample_16_9_video: Path, tmp_path: Path) -> None:
    out_path = tmp_path / "16_9_to_9_16_crop.mp4"
    spec = EditSpec(
        cuts=[CutSegment(start=0.5, end=2.0)],
        aspect_ratio="9:16",
        reframe=ReframeSpec(strategy="crop", crop_x_offset=0.0),
    )

    builder = FFmpegBuilder(
        input_path=sample_16_9_video,
        output_path=out_path,
        edit_spec=spec,
    )
    result = builder.run()

    assert result.is_file()
    assert result.stat().st_size > 0

    meta = probe_video(result)
    assert meta.width == 1080
    assert meta.height == 1920
    assert meta.orientation == "portrait"
    assert 1.3 <= meta.duration <= 1.7


def test_render_16_9_to_9_16_blur_bg(sample_16_9_video: Path, tmp_path: Path) -> None:
    out_path = tmp_path / "16_9_to_9_16_blur_bg.mp4"
    spec = EditSpec(
        cuts=[CutSegment(start=0.0, end=1.5)],
        aspect_ratio="9:16",
        reframe=ReframeSpec(strategy="blur-bg"),
    )

    builder = FFmpegBuilder(
        input_path=sample_16_9_video,
        output_path=out_path,
        edit_spec=spec,
    )
    result = builder.run()

    assert result.is_file()
    meta = probe_video(result)
    assert meta.width == 1080
    assert meta.height == 1920
    assert meta.orientation == "portrait"


def test_render_9_16_to_16_9_crop(sample_9_16_video: Path, tmp_path: Path) -> None:
    out_path = tmp_path / "9_16_to_16_9_crop.mp4"
    spec = EditSpec(
        cuts=[CutSegment(start=0.2, end=1.8)],
        aspect_ratio="16:9",
        reframe=ReframeSpec(strategy="crop"),
    )

    builder = FFmpegBuilder(
        input_path=sample_9_16_video,
        output_path=out_path,
        edit_spec=spec,
    )
    result = builder.run()

    assert result.is_file()
    meta = probe_video(result)
    assert meta.width == 1920
    assert meta.height == 1080
    assert meta.orientation == "landscape"


def test_render_9_16_to_16_9_blur_bg(sample_9_16_video: Path, tmp_path: Path) -> None:
    out_path = tmp_path / "9_16_to_16_9_blur_bg.mp4"
    spec = EditSpec(
        cuts=[CutSegment(start=0.0, end=1.2)],
        aspect_ratio="16:9",
        reframe=ReframeSpec(strategy="blur-bg"),
    )

    builder = FFmpegBuilder(
        input_path=sample_9_16_video,
        output_path=out_path,
        edit_spec=spec,
    )
    result = builder.run()

    assert result.is_file()
    meta = probe_video(result)
    assert meta.width == 1920
    assert meta.height == 1080
    assert meta.orientation == "landscape"


def test_render_same_aspect_16_9_to_16_9(sample_16_9_video: Path, tmp_path: Path) -> None:
    out_path = tmp_path / "same_aspect_16_9.mp4"
    spec = EditSpec(
        cuts=[CutSegment(start=0.5, end=1.8)],
        aspect_ratio="16:9",
    )

    builder = FFmpegBuilder(
        input_path=sample_16_9_video,
        output_path=out_path,
        edit_spec=spec,
    )
    result = builder.run()

    assert result.is_file()
    meta = probe_video(result)
    assert meta.width == 1920
    assert meta.height == 1080


def test_render_same_aspect_9_16_to_9_16(sample_9_16_video: Path, tmp_path: Path) -> None:
    out_path = tmp_path / "same_aspect_9_16.mp4"
    spec = EditSpec(
        cuts=[CutSegment(start=0.5, end=2.0)],
        aspect_ratio="9:16",
    )

    builder = FFmpegBuilder(
        input_path=sample_9_16_video,
        output_path=out_path,
        edit_spec=spec,
    )
    result = builder.run()

    assert result.is_file()
    meta = probe_video(result)
    assert meta.width == 1080
    assert meta.height == 1920


def test_render_multi_cuts_with_color_grade(sample_16_9_video: Path, tmp_path: Path) -> None:
    out_path = tmp_path / "multi_cuts_grade.mp4"
    spec = EditSpec(
        cuts=[
            CutSegment(start=0.2, end=1.0),  # 0.8s
            CutSegment(start=1.5, end=2.5),  # 1.0s
        ],
        aspect_ratio="9:16",
        grade=GradeSpec(preset="warm", saturation=1.25),
    )

    builder = FFmpegBuilder(
        input_path=sample_16_9_video,
        output_path=out_path,
        edit_spec=spec,
    )
    result = builder.run()

    assert result.is_file()
    meta = probe_video(result)
    assert meta.width == 1080
    assert meta.height == 1920
    # Expected duration is approx 1.8s
    assert 1.6 <= meta.duration <= 2.0


def test_render_no_audio_video_fallback(sample_no_audio_video: Path, tmp_path: Path) -> None:
    out_path = tmp_path / "no_audio_output.mp4"
    spec = EditSpec(
        cuts=[CutSegment(start=0.2, end=1.2)],
        aspect_ratio="9:16",
    )

    builder = FFmpegBuilder(
        input_path=sample_no_audio_video,
        output_path=out_path,
        edit_spec=spec,
    )
    result = builder.run()

    assert result.is_file()
    meta = probe_video(result)
    assert meta.width == 1080
    assert meta.height == 1920


def test_render_missing_input_file_raises_error(tmp_path: Path) -> None:
    spec = EditSpec(cuts=[CutSegment(start=0.0, end=5.0)])
    builder = FFmpegBuilder(
        input_path=tmp_path / "does_not_exist.mp4",
        output_path=tmp_path / "out.mp4",
        edit_spec=spec,
    )
    with pytest.raises(FFmpegBuilderError) as exc:
        builder.run()
    assert "does not exist" in str(exc.value)


# ---------------------------------------------------------------------------
# Task A9: Chained xfade + acrossfade transition tests
# ---------------------------------------------------------------------------


def test_build_cuts_filter_chained_xfade_acrossfade() -> None:
    cuts = [
        CutSegment(start=0.0, end=2.0),
        CutSegment(start=3.0, end=5.0),
        CutSegment(start=6.0, end=8.0),
    ]
    trans = TransitionSpec(type="fade", duration=0.5)
    lines, v_out, a_out = build_cuts_filter(cuts, transition=trans, has_audio=True)

    # 3 video trims, 3 audio trims, 2 xfade, 2 acrossfade
    assert len(lines) == 10
    assert v_out == "v_xfade"
    assert a_out == "a_xfade"

    # Check first transition offset: 2.0 - 0.5 = 1.5
    assert any("offset=1.500" in line for line in lines)
    # Check second transition offset: 1.5 + 2.0 - 0.5 = 3.0
    assert any("offset=3.000" in line for line in lines)
    # Check audio acrossfade
    assert any("acrossfade=d=0.500" in line for line in lines)


def test_render_3_segment_transitions_smooth_and_av_sync(
    sample_16_9_video: Path, tmp_path: Path
) -> None:
    out_path = tmp_path / "3_segment_fade_render.mp4"
    spec = EditSpec(
        cuts=[
            CutSegment(start=0.0, end=1.0),  # 1.0s
            CutSegment(start=1.1, end=2.0),  # 0.9s
            CutSegment(start=2.1, end=3.0),  # 0.9s
        ],
        aspect_ratio="9:16",
        reframe=ReframeSpec(strategy="crop"),
        transition=TransitionSpec(type="fade", duration=0.2),
    )

    builder = FFmpegBuilder(
        input_path=sample_16_9_video,
        output_path=out_path,
        edit_spec=spec,
    )
    result = builder.run()

    assert result.is_file()
    assert result.stat().st_size > 0

    meta = probe_video(result)
    assert meta.width == 1080
    assert meta.height == 1920
    assert meta.orientation == "portrait"

    # Total duration = (1.0 + 0.9 + 0.9) - (2 * 0.2) = 2.4s
    assert 2.2 <= meta.duration <= 2.6


def test_render_3_segment_transitions_wipeleft(sample_16_9_video: Path, tmp_path: Path) -> None:
    out_path = tmp_path / "3_segment_wipeleft_render.mp4"
    spec = EditSpec(
        cuts=[
            CutSegment(start=0.0, end=1.0),
            CutSegment(start=1.1, end=2.0),
            CutSegment(start=2.1, end=3.0),
        ],
        aspect_ratio="16:9",
        transition=TransitionSpec(type="wipeleft", duration=0.2),
    )

    builder = FFmpegBuilder(
        input_path=sample_16_9_video,
        output_path=out_path,
        edit_spec=spec,
    )
    result = builder.run()

    assert result.is_file()
    meta = probe_video(result)
    assert meta.width == 1920
    assert meta.height == 1080
    assert 2.2 <= meta.duration <= 2.6


def test_render_3_segment_transitions_no_audio(sample_no_audio_video: Path, tmp_path: Path) -> None:
    out_path = tmp_path / "3_segment_no_audio_render.mp4"
    spec = EditSpec(
        cuts=[
            CutSegment(start=0.0, end=0.7),
            CutSegment(start=0.8, end=1.4),
            CutSegment(start=1.5, end=2.0),
        ],
        aspect_ratio="9:16",
        transition=TransitionSpec(type="fade", duration=0.15),
    )

    builder = FFmpegBuilder(
        input_path=sample_no_audio_video,
        output_path=out_path,
        edit_spec=spec,
    )
    result = builder.run()

    assert result.is_file()
    meta = probe_video(result)
    assert meta.width == 1080
    assert meta.height == 1920
