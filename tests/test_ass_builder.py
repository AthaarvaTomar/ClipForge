"""Tests for the ASS subtitle builder service (Task A10)."""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Generator
from pathlib import Path

import pytest

from app.schemas.edit_spec import CaptionSpec, CutSegment, EditSpec, TransitionSpec
from app.services.ass_builder import (
    ASSBuilder,
    RemappedWord,
    chunk_words_into_lines,
    format_ass_timestamp,
    hex_to_ass_color,
    remap_words_to_cuts,
)
from app.services.ffmpeg_builder import FFmpegBuilder
from app.services.video_probe import probe_video


@pytest.fixture(scope="module")
def sample_video(tmp_path_factory: pytest.TempPathFactory) -> Generator[Path, None, None]:
    """Generate a clean 3-second 1280x720 16:9 test video with stereo test tone."""
    ffmpeg_bin = shutil.which("ffmpeg")
    assert ffmpeg_bin is not None

    tmp_dir = tmp_path_factory.mktemp("ass_test_video")
    out_video = tmp_dir / "sample_video.mp4"

    cmd = [
        ffmpeg_bin,
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc=duration=3.0:size=1280x720:rate=30",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:duration=3.0:sample_rate=44100",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        str(out_video),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode == 0, f"FFmpeg failed: {res.stderr}"
    yield out_video


# ---------------------------------------------------------------------------
# Unit Tests
# ---------------------------------------------------------------------------


def test_hex_to_ass_color() -> None:
    # Standard white: #FFFFFF -> B=FF, G=FF, R=FF
    assert hex_to_ass_color("#FFFFFF") == "&H00FFFFFF&"
    # Pure red: #FF0000 -> B=00, G=00, R=FF
    assert hex_to_ass_color("#FF0000") == "&H000000FF&"
    # Pure blue: #0000FF -> B=FF, G=00, R=00
    assert hex_to_ass_color("#0000FF") == "&H00FF0000&"
    # Highlight cyan: #00FFCC -> R=00, G=FF, B=CC -> &H00CCFF00&
    assert hex_to_ass_color("#00FFCC") == "&H00CCFF00&"
    # Short hex: #FFF
    assert hex_to_ass_color("#FFF") == "&H00FFFFFF&"
    # Custom alpha (128 = &H80)
    assert hex_to_ass_color("#FFFFFF", alpha=128) == "&H80FFFFFF&"


def test_format_ass_timestamp() -> None:
    assert format_ass_timestamp(0.0) == "0:00:00.00"
    assert format_ass_timestamp(1.25) == "0:00:01.25"
    assert format_ass_timestamp(65.43) == "0:01:05.43"
    assert format_ass_timestamp(3661.05) == "1:01:01.05"


def test_remap_words_to_cuts_single_cut() -> None:
    words = [
        {"word": "Before", "start": 1.0, "end": 1.8},
        {"word": "Hello", "start": 2.1, "end": 2.6},
        {"word": "World", "start": 2.8, "end": 3.4},
        {"word": "After", "start": 5.5, "end": 6.0},
    ]
    cuts = [CutSegment(start=2.0, end=4.0)]

    remapped = remap_words_to_cuts(words, cuts)
    assert len(remapped) == 2
    assert remapped[0].word == "Hello"
    # 2.1 - 2.0 = 0.1
    assert pytest.approx(remapped[0].start, 0.01) == 0.1
    assert pytest.approx(remapped[0].end, 0.01) == 0.6
    assert remapped[1].word == "World"
    # 2.8 - 2.0 = 0.8
    assert pytest.approx(remapped[1].start, 0.01) == 0.8
    assert pytest.approx(remapped[1].end, 0.01) == 1.4


def test_remap_words_to_cuts_multi_cut_with_transition() -> None:
    words = [
        {"word": "First", "start": 1.0, "end": 1.5},
        {"word": "Second", "start": 5.0, "end": 5.6},
    ]
    cuts = [
        CutSegment(start=0.5, end=2.0),  # Length 1.5s (offset 0.0 -> [0.0, 1.5])
        CutSegment(start=4.5, end=6.5),  # Length 2.0s
    ]
    # Transition with 0.2s duration: cut 1 start offset = 1.5 - 0.2 = 1.3s
    trans = TransitionSpec(type="fade", duration=0.2)
    remapped = remap_words_to_cuts(words, cuts, transition=trans)

    assert len(remapped) == 2
    # First: in Cut 0. offset 0 + (1.0 - 0.5) = 0.5s
    assert remapped[0].word == "First"
    assert pytest.approx(remapped[0].start, 0.01) == 0.5
    assert pytest.approx(remapped[0].end, 0.01) == 1.0

    # Second: in Cut 1. offset 1.3 + (5.0 - 4.5) = 1.8s
    assert remapped[1].word == "Second"
    assert pytest.approx(remapped[1].start, 0.01) == 1.8
    assert pytest.approx(remapped[1].end, 0.01) == 2.4


def test_chunk_words_into_lines() -> None:
    words = [
        RemappedWord(word="This", start=0.0, end=0.3),
        RemappedWord(word="is", start=0.35, end=0.5),
        RemappedWord(word="amazing.", start=0.55, end=1.0),
        RemappedWord(word="Next", start=1.2, end=1.5),
        RemappedWord(word="sentence", start=1.55, end=2.0),
    ]
    chunks = chunk_words_into_lines(words, max_words_per_line=3)
    assert len(chunks) == 2
    assert [w.word for w in chunks[0]] == ["This", "is", "amazing."]
    assert [w.word for w in chunks[1]] == ["Next", "sentence"]


# ---------------------------------------------------------------------------
# Animation Tests (all 5 animations)
# ---------------------------------------------------------------------------


def test_ass_builder_animation_highlight() -> None:
    builder = ASSBuilder(CaptionSpec(animation="highlight", highlight_color="#00FFCC"))
    words = [
        RemappedWord(word="Start", start=0.5, end=1.0),
        RemappedWord(word="now", start=1.0, end=1.5),
    ]
    ass_content = builder.build_ass(words)

    assert "[Script Info]" in ass_content
    assert "[V4+ Styles]" in ass_content
    assert "[Events]" in ass_content
    # Check highlight tags
    assert r"{\c&H00CCFF00&\b1}Start{\c&H00FFFFFF&\b0}" in ass_content
    assert r"{\c&H00CCFF00&\b1}now{\c&H00FFFFFF&\b0}" in ass_content


def test_ass_builder_animation_pop() -> None:
    builder = ASSBuilder(CaptionSpec(animation="pop"))
    words = [RemappedWord(word="Viral", start=0.0, end=0.8)]
    ass_content = builder.build_ass(words)

    # Pop tag should include \t scale animations
    assert r"\fscx120\fscy120" in ass_content
    assert r"\fscx100\fscy100" in ass_content


def test_ass_builder_animation_fade() -> None:
    builder = ASSBuilder(CaptionSpec(animation="fade"))
    words = [
        RemappedWord(word="Smooth", start=0.0, end=0.5),
        RemappedWord(word="fade", start=0.5, end=1.0),
    ]
    ass_content = builder.build_ass(words)

    assert r"{\fad(150,150)}Smooth fade" in ass_content


def test_ass_builder_animation_bounce() -> None:
    builder = ASSBuilder(CaptionSpec(animation="bounce"))
    words = [RemappedWord(word="Bounce", start=0.0, end=0.8)]
    ass_content = builder.build_ass(words)

    # Bounce contains squash and stretch transforms
    assert r"\fscy125\fscx90" in ass_content
    assert r"\fscy95\fscx105" in ass_content


def test_ass_builder_animation_none() -> None:
    builder = ASSBuilder(CaptionSpec(animation="none"))
    words = [
        RemappedWord(word="Clean", start=0.0, end=0.5),
        RemappedWord(word="subtitle", start=0.5, end=1.0),
    ]
    ass_content = builder.build_ass(words)

    assert "Dialogue: 0,0:00:00.00,0:00:01.00,Default,,0,0,0,,Clean subtitle" in ass_content
    assert r"\c" not in ass_content


def test_ass_builder_title_card() -> None:
    builder = ASSBuilder()
    ass_content = builder.build_ass(
        words=[],
        title="Stop Scrolling Right Now!",
        title_duration=2.0,
    )
    assert "Style: Title" in ass_content
    assert (
        "Dialogue: 1,0:00:00.00,0:00:02.00,Title,,0,0,0,,{\\fad(200,300)}Stop Scrolling Right Now!"
        in ass_content
    )


# ---------------------------------------------------------------------------
# End-to-End ASS Burn-in Render Test with FFmpeg
# ---------------------------------------------------------------------------


def test_ffmpeg_burn_in_ass_plays_correctly(sample_video: Path, tmp_path: Path) -> None:
    ass_file = tmp_path / "test_subtitles.ass"
    out_video = tmp_path / "subtitled_output.mp4"

    raw_words = [
        {"word": "Antigravity", "start": 0.2, "end": 0.8},
        {"word": "is", "start": 0.85, "end": 1.2},
        {"word": "amazing!", "start": 1.25, "end": 2.2},
    ]

    builder = ASSBuilder(
        caption_spec=CaptionSpec(
            enabled=True,
            animation="highlight",
            primary_color="#FFFFFF",
            highlight_color="#00FFCC",
            font_size=40,
            position="bottom",
        ),
        target_width=1080,
        target_height=1920,
    )

    cuts = [CutSegment(start=0.0, end=2.5)]
    builder.write_ass_file(
        output_file=ass_file,
        words=raw_words,
        cuts=cuts,
        title="Check This Out!",
    )

    assert ass_file.is_file()
    assert ass_file.stat().st_size > 0

    # Build and execute video with subtitles burned in
    spec = EditSpec(
        cuts=cuts,
        aspect_ratio="9:16",
    )

    ffmpeg_runner = FFmpegBuilder(
        input_path=sample_video,
        output_path=out_video,
        edit_spec=spec,
        subtitle_path=ass_file,
    )

    result = ffmpeg_runner.run()
    assert result.is_file()
    assert result.stat().st_size > 0

    meta = probe_video(result)
    assert meta.width == 1080
    assert meta.height == 1920
    assert 2.3 <= meta.duration <= 2.7
