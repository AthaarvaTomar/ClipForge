"""Golden tests for Task R2: Timeline-to-FFmpeg Compiler.

Verifies:
1. Single track: video cuts, reframing (9:16 portrait), and grading.
2. Two-track overlay: main video + secondary video composited at a timeline offset with audio mix.
3. Captions: burned-in subtitles rendered from caption track items via ASS filter.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Generator
from pathlib import Path

import pytest

from app.schemas.edit_spec import CaptionSpec, GradeSpec
from app.schemas.timeline import Item, ItemTransition, Timeline, Track, TrackType
from app.services.timeline_compiler import TimelineCompiler
from app.services.video_probe import probe_video


@pytest.fixture(scope="module")
def sample_media(
    tmp_path_factory: pytest.TempPathFactory,
) -> Generator[tuple[Path, Path], None, None]:
    """Generate two distinct valid test video files with video and audio."""
    ffmpeg_bin = shutil.which("ffmpeg")
    assert ffmpeg_bin is not None

    tmp_dir = tmp_path_factory.mktemp("compiler_test_media")
    video_1 = tmp_dir / "video_1.mp4"
    video_2 = tmp_dir / "video_2.mp4"

    # Video 1: 1280x720 blue background with 440Hz sine wave (2.5s)
    cmd1 = [
        ffmpeg_bin,
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc=duration=2.5:size=1280x720:rate=30",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:duration=2.5:sample_rate=44100",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        str(video_1),
    ]
    subprocess.run(cmd1, capture_output=True, check=True)

    # Video 2: 640x360 red/green test pattern with 880Hz sine wave (1.5s)
    cmd2 = [
        ffmpeg_bin,
        "-y",
        "-f",
        "lavfi",
        "-i",
        "smptebars=duration=1.5:size=640x360:rate=30",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=880:duration=1.5:sample_rate=44100",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        str(video_2),
    ]
    subprocess.run(cmd2, capture_output=True, check=True)

    yield video_1, video_2


def test_golden_single_track(sample_media: tuple[Path, Path], tmp_path: Path) -> None:
    """Golden Test 1: Single Track with cuts, grade, and 9:16 reframe."""
    video_1, _ = sample_media
    out_file = tmp_path / "golden_single_track.mp4"

    # Timeline with 2 cuts on main video track
    item1 = Item(
        id="it_1",
        source="vid_1",
        src_in=100,
        src_out=1100,  # 1.0s
        start=0,
        volume=1.0,
        grade=GradeSpec(preset="warm"),
    )
    item2 = Item(
        id="it_2",
        source="vid_1",
        src_in=1300,
        src_out=2100,  # 0.8s
        start=1000,
        volume=1.0,
        grade=GradeSpec(preset="cinematic"),
        transition=ItemTransition(type="fade", duration_ms=200),
    )

    track = Track(
        id="trk_video_main",
        type=TrackType.VIDEO,
        items=[item1, item2],
    )

    timeline = Timeline(
        id="tl_golden_single",
        video_id="vid_1",
        version=1,
        tracks=[track],
        metadata={
            "aspect_ratio": "9:16",
            "reframe": {"strategy": "crop"},
        },
    )

    compiler = TimelineCompiler(
        timeline=timeline,
        source_resolver={"vid_1": video_1},
        output_path=out_file,
    )

    progress_ticks: list[float] = []
    rendered = compiler.run(on_progress=lambda p: progress_ticks.append(p))

    assert rendered.is_file()
    assert rendered.stat().st_size > 0
    assert len(progress_ticks) > 0
    assert progress_ticks[-1] == 100.0

    meta = probe_video(rendered)
    assert meta.width == 1080
    assert meta.height == 1920
    assert meta.orientation == "portrait"
    # Duration ~ 1.0 + 0.8 - 0.2 overlap = 1.6s
    assert 1.4 <= meta.duration <= 1.8


def test_golden_two_track_overlay(sample_media: tuple[Path, Path], tmp_path: Path) -> None:
    """Golden Test 2: Two-track overlay composited over main video with audio mix."""
    video_1, video_2 = sample_media
    out_file = tmp_path / "golden_two_track.mp4"

    # Main video track: 0 to 2000 ms
    main_item = Item(
        id="main_1",
        source="vid_1",
        src_in=0,
        src_out=2000,
        start=0,
        volume=1.0,
    )
    main_track = Track(
        id="trk_main",
        type=TrackType.VIDEO,
        items=[main_item],
    )

    # Overlay track: secondary video displayed from 500ms to 1500ms
    overlay_item = Item(
        id="ov_1",
        source="vid_2",
        src_in=0,
        src_out=1000,  # 1.0s long
        start=500,  # placed at 500ms on timeline
        volume=0.5,
        effects={"width": 480},
    )
    overlay_track = Track(
        id="trk_overlay",
        type=TrackType.OVERLAY,
        items=[overlay_item],
    )

    timeline = Timeline(
        id="tl_golden_overlay",
        video_id="vid_1",
        version=1,
        tracks=[main_track, overlay_track],
        metadata={"aspect_ratio": "9:16"},
    )

    compiler = TimelineCompiler(
        timeline=timeline,
        source_resolver={"vid_1": video_1, "vid_2": video_2},
        output_path=out_file,
    )

    rendered = compiler.run()
    assert rendered.is_file()
    assert rendered.stat().st_size > 0

    meta = probe_video(rendered)
    assert meta.width == 1080
    assert meta.height == 1920
    assert 1.8 <= meta.duration <= 2.2


def test_golden_captions(sample_media: tuple[Path, Path], tmp_path: Path) -> None:
    """Golden Test 3: Caption track with burned-in subtitles via ASS filter."""
    video_1, _ = sample_media
    out_file = tmp_path / "golden_captions.mp4"

    video_item = Item(
        id="v_1",
        source="vid_1",
        src_in=0,
        src_out=2000,
        start=0,
        volume=1.0,
    )
    video_track = Track(
        id="trk_video",
        type=TrackType.VIDEO,
        items=[video_item],
    )

    # Caption track with two subtitle items
    cap_style = CaptionSpec(
        enabled=True,
        style="bold-highlight",
        animation="highlight",
        primary_color="#FFFFFF",
        highlight_color="#FF7A45",
    )
    cap1 = Item(
        id="cap_1",
        source="text",
        src_in=0,
        src_out=800,
        start=200,
        text="Transform your videos",
        caption_style=cap_style,
    )
    cap2 = Item(
        id="cap_2",
        source="text",
        src_in=0,
        src_out=800,
        start=1100,
        text="into viral Shorts!",
        caption_style=cap_style,
    )
    caption_track = Track(
        id="trk_caption",
        type=TrackType.CAPTION,
        items=[cap1, cap2],
    )

    timeline = Timeline(
        id="tl_golden_captions",
        video_id="vid_1",
        version=1,
        tracks=[video_track, caption_track],
        metadata={
            "aspect_ratio": "9:16",
            "title": "ClipForge AI",
        },
    )

    compiler = TimelineCompiler(
        timeline=timeline,
        source_resolver={"vid_1": video_1},
        output_path=out_file,
    )

    rendered = compiler.run()
    assert rendered.is_file()
    assert rendered.stat().st_size > 0

    meta = probe_video(rendered)
    assert meta.width == 1080
    assert meta.height == 1920
    assert 1.8 <= meta.duration <= 2.2
