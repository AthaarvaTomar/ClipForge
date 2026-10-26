import json
import shutil
import subprocess
import threading
from collections.abc import Callable
from pathlib import Path

from app.schemas.edit_spec import CutSegment, EditSpec, GradeSpec, TransitionSpec

# Ensure static ffmpeg binaries are in PATH if available
try:
    import static_ffmpeg

    static_ffmpeg.add_paths()
except Exception:
    pass


class FFmpegBuilderError(Exception):
    """Raised when FFmpeg filter graph building or execution fails."""

    pass


ASPECT_RATIO_TARGETS: dict[str, tuple[int, int]] = {
    "9:16": (1080, 1920),
    "16:9": (1920, 1080),
    "1:1": (1080, 1080),
    "4:5": (1080, 1350),
}

GRADE_PRESETS: dict[str, str] = {
    "cinematic": (
        "eq=contrast=1.15:brightness=-0.02:saturation=1.1,"
        "colorbalance=rs=0.04:gs=0.0:bs=-0.04:rm=-0.02:gm=0.02:bm=0.05"
    ),
    "warm": (
        "colorbalance=rs=0.08:gs=0.02:bs=-0.08:rm=0.08:gm=0.02:bm=-0.08,eq=saturation=1.15"
    ),
    "cool": (
        "colorbalance=rs=-0.08:gs=0.0:bs=0.08:rm=-0.08:gm=0.0:bm=0.08,eq=saturation=1.05"
    ),
    "vibrant": "eq=contrast=1.2:saturation=1.3:brightness=0.02",
    "bw": "hue=s=0,eq=contrast=1.2:brightness=0.0",
}

XFADE_TRANSITION_MAP: dict[str, str] = {
    "fade": "fade",
    "crossfade": "fade",
    "wipeleft": "wipeleft",
    "wiperight": "wiperight",
    "slideup": "slideup",
    "slidedown": "slidedown",
    "circlecrop": "circlecrop",
    "dissolve": "dissolve",
    "fadeblack": "fadeblack",
}


def get_target_resolution(
    aspect_ratio: str, source_width: int, source_height: int
) -> tuple[int, int]:
    """Return target (width, height) for the given aspect ratio string.

    Ensures dimensions are even numbers for H.264 compatibility.
    """
    if aspect_ratio in ASPECT_RATIO_TARGETS:
        return ASPECT_RATIO_TARGETS[aspect_ratio]

    # Fallback to source aspect ratio if unrecognized
    w = source_width if source_width % 2 == 0 else source_width - 1
    h = source_height if source_height % 2 == 0 else source_height - 1
    return (max(2, w), max(2, h))


def check_has_audio(file_path: Path | str) -> bool:
    """Check if the media file contains an audio stream using ffprobe."""
    ffprobe_bin = shutil.which("ffprobe")
    if not ffprobe_bin:
        return True  # Default to assuming audio if ffprobe is absent

    cmd = [
        ffprobe_bin,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_streams",
        str(file_path),
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if res.returncode == 0:
            data = json.loads(res.stdout)
            streams = data.get("streams", [])
            return any(s.get("codec_type") == "audio" for s in streams)
    except Exception:
        pass
    return True


def build_cuts_filter(
    cuts: list[CutSegment],
    transition: TransitionSpec | None = None,
    has_audio: bool = True,
) -> tuple[list[str], str, str]:
    """Generate FFmpeg filtergraph segments for trimming, concatenating, or transitioning cuts.

    Returns (filter_lines, output_video_label, output_audio_label).
    """
    if not cuts:
        raise FFmpegBuilderError("At least one cut segment is required to build cuts filter")

    lines: list[str] = []
    n = len(cuts)

    for i, cut in enumerate(cuts):
        # Video trim
        lines.append(f"[0:v]trim=start={cut.start}:end={cut.end},setpts=PTS-STARTPTS[v_cut_{i}]")
        # Audio trim
        if has_audio:
            lines.append(f"[0:a]atrim=start={cut.start}:end={cut.end},asetpts=PTS-STARTPTS[a_cut_{i}]")
        else:
            duration = cut.end - cut.start
            lines.append(
                f"anullsrc=channel_layout=stereo:sample_rate=44100,"
                f"atrim=start=0:end={duration},asetpts=PTS-STARTPTS[a_cut_{i}]"
            )

    if n == 1:
        return lines, "v_cut_0", "a_cut_0"

    # Chained xfade + acrossfade transitions if requested and applicable
    trans_type = transition.type if transition else "none"
    trans_dur = transition.duration if transition else 0.0

    if trans_type != "none" and trans_dur > 0.0 and n >= 2:
        xfade_name = XFADE_TRANSITION_MAP.get(trans_type, "fade")
        min_segment_dur = min(cut.end - cut.start for cut in cuts)
        d = min(trans_dur, min_segment_dur * 0.5)

        if d >= 0.05:
            curr_v = "v_cut_0"
            curr_a = "a_cut_0"
            accumulated_duration = cuts[0].end - cuts[0].start

            for i in range(1, n):
                offset = max(0.0, accumulated_duration - d)
                next_v = f"v_cut_{i}"
                next_a = f"a_cut_{i}"

                out_v = f"vx_{i}" if i < n - 1 else "v_xfade"
                out_a = f"ax_{i}" if i < n - 1 else "a_xfade"

                lines.append(
                    f"[{curr_v}][{next_v}]xfade=transition={xfade_name}:"
                    f"duration={d:.3f}:offset={offset:.3f}[{out_v}]"
                )
                lines.append(f"[{curr_a}][{next_a}]acrossfade=d={d:.3f}[{out_a}]")

                curr_v = out_v
                curr_a = out_a
                accumulated_duration = accumulated_duration + (cuts[i].end - cuts[i].start) - d

            return lines, curr_v, curr_a

    # Multi-cut concatenation without transitions
    concat_inputs = "".join(f"[v_cut_{i}][a_cut_{i}]" for i in range(n))
    lines.append(f"{concat_inputs}concat=n={n}:v=1:a=1[v_cat][a_cat]")
    return lines, "v_cat", "a_cat"


def build_reframe_filter(
    in_label: str,
    out_label: str,
    source_width: int,
    source_height: int,
    target_width: int,
    target_height: int,
    strategy: str = "crop",
    crop_x_offset: float = 0.0,
) -> list[str]:
    """Generate reframing filters (crop or blur-bg) between source and target aspect ratios.

    Handles 16:9 -> 9:16, 9:16 -> 16:9, and same-aspect transformations.
    """
    lines: list[str] = []
    src_ar = source_width / max(1, source_height)
    tgt_ar = target_width / max(1, target_height)

    # If aspect ratios match closely (within 1.5%), direct scale & pad
    if abs(src_ar - tgt_ar) < 0.015:
        lines.append(
            f"[{in_label}]scale={target_width}:{target_height}:force_original_aspect_ratio=decrease,"
            f"pad={target_width}:{target_height}:(ow-iw)/2:(oh-ih)/2[{out_label}]"
        )
        return lines

    if strategy == "blur-bg":
        # Split into background and foreground
        lines.append(f"[{in_label}]split=2[bg_in_{in_label}][fg_in_{in_label}]")
        # Background: scale to cover, crop exact, blur
        lines.append(
            f"[bg_in_{in_label}]scale={target_width}:{target_height}:force_original_aspect_ratio=increase,"
            f"crop={target_width}:{target_height},boxblur=20:5[bg_{in_label}]"
        )
        # Foreground: scale to fit inside target box
        lines.append(
            f"[fg_in_{in_label}]scale={target_width}:{target_height}:force_original_aspect_ratio=decrease"
            f"[fg_{in_label}]"
        )
        # Overlay foreground centered on blurred background
        lines.append(
            f"[bg_{in_label}][fg_{in_label}]overlay=(W-w)/2:(H-h)/2[{out_label}]"
        )
        return lines

    # Default strategy: "crop" (scale to increase and crop to target)
    # Clamp crop_x_offset to [-1.0, 1.0]
    clamped_offset = max(-1.0, min(1.0, crop_x_offset))
    crop_x_expr = f"(in_w-{target_width})/2+({clamped_offset}*(in_w-{target_width})/2)"
    crop_y_expr = f"(in_h-{target_height})/2"

    lines.append(
        f"[{in_label}]scale={target_width}:{target_height}:force_original_aspect_ratio=increase,"
        f"crop={target_width}:{target_height}:x='{crop_x_expr}':y='{crop_y_expr}'[{out_label}]"
    )
    return lines


def build_grade_filter(
    in_label: str,
    out_label: str,
    grade: GradeSpec,
    lut_path: Path | str | None = None,
) -> list[str]:
    """Generate color grading filters from preset, custom parameters, or 3D LUT."""
    filter_steps: list[str] = []

    # 1. Preset filter if configured and not 'none'
    if grade.preset and grade.preset != "none" and grade.preset in GRADE_PRESETS:
        filter_steps.append(GRADE_PRESETS[grade.preset])

    # 2. Custom brightness/contrast/saturation adjustments if modified from defaults
    is_custom = (
        grade.brightness != 0.0 or grade.contrast != 1.0 or grade.saturation != 1.0
    )
    if is_custom:
        filter_steps.append(
            f"eq=brightness={grade.brightness:.3f}:"
            f"contrast={grade.contrast:.3f}:"
            f"saturation={grade.saturation:.3f}"
        )

    # 3. Optional 3D LUT
    if lut_path is not None:
        lut_p = Path(lut_path)
        if lut_p.exists():
            # Escape path for FFmpeg filter syntax
            escaped_lut = str(lut_p.resolve()).replace("\\", "/").replace(":", "\\:")
            filter_steps.append(f"lut3d=file='{escaped_lut}'")

    if not filter_steps:
        # Pass-through null filter
        return [f"[{in_label}]null[{out_label}]"]

    combined_filter = ",".join(filter_steps)
    return [f"[{in_label}]{combined_filter}[{out_label}]"]


class FFmpegBuilder:
    """Builder for constructing and executing FFmpeg filter graphs for video repurposing."""

    def __init__(
        self,
        input_path: Path | str,
        output_path: Path | str,
        edit_spec: EditSpec,
        source_width: int | None = None,
        source_height: int | None = None,
        has_audio: bool | None = None,
        lut_path: Path | str | None = None,
        subtitle_path: Path | str | None = None,
    ) -> None:
        self.input_path = Path(input_path)
        self.output_path = Path(output_path)
        self.edit_spec = edit_spec
        self.source_width = source_width
        self.source_height = source_height
        self.has_audio = has_audio
        self.lut_path = Path(lut_path) if lut_path else None
        self.subtitle_path = Path(subtitle_path) if subtitle_path else None

    def _ensure_metadata(self) -> None:
        """Resolve source dimensions and audio stream if not provided."""
        if not self.input_path.is_file():
            raise FFmpegBuilderError(f"Input video file does not exist: {self.input_path}")

        if self.source_width is None or self.source_height is None:
            from app.services.video_probe import probe_video

            meta = probe_video(self.input_path)
            self.source_width = meta.width
            self.source_height = meta.height

        if self.has_audio is None:
            self.has_audio = check_has_audio(self.input_path)

    def build_filter_graph(self) -> tuple[str, str, str]:
        """Construct the complete -filter_complex string and final audio/video labels.

        Pipeline order:
          1. Cuts & Trimming (Trim/Concat)
          2. Reframing (Aspect Ratio conversion via Crop or Blur-BG)
          3. Color Grading (Preset, Custom params, or 3D LUT)
          4. Subtitle overlay (if subtitle_path provided)
        """
        self._ensure_metadata()
        assert self.source_width is not None and self.source_height is not None

        target_w, target_h = get_target_resolution(
            self.edit_spec.aspect_ratio,
            self.source_width,
            self.source_height,
        )

        filters: list[str] = []

        # 1. Cuts (with optional chained xfade + acrossfade transitions)
        cut_filters, v_cut_out, a_cut_out = build_cuts_filter(
            self.edit_spec.cuts,
            transition=self.edit_spec.transition,
            has_audio=bool(self.has_audio),
        )
        filters.extend(cut_filters)

        # 2. Reframing
        reframe_out = "v_reframe"
        reframe_filters = build_reframe_filter(
            in_label=v_cut_out,
            out_label=reframe_out,
            source_width=self.source_width,
            source_height=self.source_height,
            target_width=target_w,
            target_height=target_h,
            strategy=self.edit_spec.reframe.strategy,
            crop_x_offset=self.edit_spec.reframe.crop_x_offset,
        )
        filters.extend(reframe_filters)

        # 3. Color Grading
        grade_out = "v_graded"
        grade_filters = build_grade_filter(
            in_label=reframe_out,
            out_label=grade_out,
            grade=self.edit_spec.grade,
            lut_path=self.lut_path,
        )
        filters.extend(grade_filters)

        final_v = grade_out

        # 4. Subtitle hook (for ASS builder in upcoming tasks)
        if self.subtitle_path is not None and self.subtitle_path.exists():
            sub_out = "v_subbed"
            escaped_sub = str(self.subtitle_path.resolve()).replace("\\", "/").replace(":", "\\:")
            filters.append(f"[{final_v}]ass='{escaped_sub}'[{sub_out}]")
            final_v = sub_out

        filter_complex = ";".join(filters)
        return filter_complex, final_v, a_cut_out

    @property
    def total_duration(self) -> float:
        """Estimate the expected total playback duration in seconds."""
        cuts = self.edit_spec.cuts
        if not cuts:
            return 0.0
        total = sum(cut.end - cut.start for cut in cuts)
        trans = self.edit_spec.transition
        if trans and trans.type != "none" and trans.duration > 0.0 and len(cuts) >= 2:
            min_seg = min(cut.end - cut.start for cut in cuts)
            d = min(trans.duration, min_seg * 0.5)
            if d >= 0.05:
                total -= (len(cuts) - 1) * d
        return max(0.1, total)

    def build_command(self, with_progress: bool = False) -> list[str]:
        """Assemble the complete FFmpeg CLI command list."""
        ffmpeg_bin = shutil.which("ffmpeg")
        if not ffmpeg_bin:
            raise FFmpegBuilderError("ffmpeg executable not found in PATH")

        filter_complex, final_v, final_a = self.build_filter_graph()

        cmd = [
            ffmpeg_bin,
            "-y",
        ]
        if with_progress:
            cmd.extend(["-progress", "pipe:1", "-nostats"])

        cmd.extend([
            "-i",
            str(self.input_path),
            "-filter_complex",
            filter_complex,
            "-map",
            f"[{final_v}]",
            "-map",
            f"[{final_a}]",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "22",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            str(self.output_path),
        ])
        return cmd

    def run(
        self,
        timeout: float = 300.0,
        on_progress: Callable[[float], None] | None = None,
    ) -> Path:
        """Execute FFmpeg render with optional progress callback and failure cleanup."""
        self.output_path.parent.mkdir(parents=True, exist_ok=True)



        if on_progress is None:
            cmd = self.build_command(with_progress=False)
            try:
                subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=timeout,
                )
            except subprocess.CalledProcessError as e:
                self.output_path.unlink(missing_ok=True)
                raise FFmpegBuilderError(
                    f"FFmpeg render process failed with code {e.returncode}: {e.stderr}"
                ) from e
            except Exception as e:
                self.output_path.unlink(missing_ok=True)
                if isinstance(e, subprocess.TimeoutExpired):
                    raise FFmpegBuilderError(
                        f"FFmpeg render process timed out after {timeout}s"
                    ) from e
                raise
        else:
            cmd = self.build_command(with_progress=True)
            total_dur = self.total_duration

            try:
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1,
                )

                stderr_lines: list[str] = []

                def drain_stderr() -> None:
                    if process.stderr:
                        for err_line in iter(process.stderr.readline, ""):
                            stderr_lines.append(err_line)

                t = threading.Thread(target=drain_stderr, daemon=True)
                t.start()

                if process.stdout:
                    for line in iter(process.stdout.readline, ""):
                        line = line.strip()
                        if line.startswith("out_time_us="):
                            try:
                                us = int(line.split("=")[1])
                                curr_sec = us / 1_000_000.0
                                pct = min(99.0, max(0.0, (curr_sec / total_dur) * 100.0))
                                on_progress(round(pct, 1))
                            except (ValueError, IndexError):
                                pass
                        elif line.startswith("progress=end"):
                            on_progress(100.0)

                t.join(timeout=5.0)
                retcode = process.wait(timeout=timeout)
                if retcode != 0:
                    err_msg = "".join(stderr_lines)
                    self.output_path.unlink(missing_ok=True)
                    raise FFmpegBuilderError(
                        f"FFmpeg render process failed with code {retcode}: {err_msg}"
                    )
                on_progress(100.0)
            except Exception as e:
                self.output_path.unlink(missing_ok=True)
                if isinstance(e, subprocess.TimeoutExpired):
                    raise FFmpegBuilderError(
                        f"FFmpeg render process timed out after {timeout}s"
                    ) from e
                if not isinstance(e, FFmpegBuilderError):
                    raise FFmpegBuilderError(f"FFmpeg render failed: {e}") from e
                raise

        if not self.output_path.exists() or self.output_path.stat().st_size == 0:
            self.output_path.unlink(missing_ok=True)
            raise FFmpegBuilderError(
                f"Rendered output file was not created or is empty: {self.output_path}"
            )

        return self.output_path


def extract_preview_frame(
    video_path: Path | str,
    timestamp: float = 0.5,
    output_file: Path | str | None = None,
) -> bytes:
    """Extract a single frame as JPEG from a video file at the given timestamp."""
    ffmpeg_bin = shutil.which("ffmpeg")
    if not ffmpeg_bin:
        raise FFmpegBuilderError("ffmpeg executable not found in PATH")

    vid = Path(video_path)
    if not vid.is_file():
        raise FFmpegBuilderError(f"Video file does not exist: {vid}")

    safe_time = max(0.0, timestamp)
    cmd = [
        ffmpeg_bin,
        "-y",
        "-ss",
        f"{safe_time:.3f}",
        "-i",
        str(vid),
        "-vframes",
        "1",
        "-q:v",
        "2",
        "-f",
        "image2",
        "pipe:1" if output_file is None else str(output_file),
    ]

    try:
        res = subprocess.run(cmd, capture_output=True, check=True)
    except subprocess.CalledProcessError as e:
        raise FFmpegBuilderError(
            f"Failed to extract frame: {e.stderr.decode('utf-8', errors='ignore')}"
        ) from e

    if output_file is not None:
        return Path(output_file).read_bytes()
    return res.stdout

