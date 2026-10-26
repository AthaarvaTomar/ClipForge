import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

# Ensure static-ffmpeg binaries are in PATH if available
try:
    import static_ffmpeg

    static_ffmpeg.add_paths()
except Exception:
    pass


@dataclass
class VideoMetadata:
    """Extracted video metadata."""

    duration: float
    width: int
    height: int
    fps: float
    orientation: str  # "landscape", "portrait", "square"


class VideoProbeError(Exception):
    """Raised when video probe fails."""

    pass


def probe_video(file_path: Path | str) -> VideoMetadata:
    """Run ffprobe on the given video file to extract duration, resolution, fps, and orientation."""
    path = Path(file_path)
    if not path.is_file():
        raise VideoProbeError(f"Video file not found: {path}")

    ffprobe_bin = shutil.which("ffprobe")
    if not ffprobe_bin:
        raise VideoProbeError("ffprobe executable not found in system or virtualenv PATH")

    cmd = [
        ffprobe_bin,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
    except subprocess.CalledProcessError as e:
        raise VideoProbeError(f"ffprobe execution failed: {e.stderr}") from e
    except subprocess.TimeoutExpired as e:
        raise VideoProbeError("ffprobe execution timed out") from e

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise VideoProbeError(f"Failed to parse ffprobe JSON output: {e}") from e

    streams = data.get("streams", [])
    video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    if not video_stream:
        raise VideoProbeError("No video stream found in the uploaded file")

    width = int(video_stream.get("width", 0))
    height = int(video_stream.get("height", 0))

    # Check for rotation tags (e.g. smartphone recordings)
    rotation = 0
    # Check side_data_list first
    side_data_list = video_stream.get("side_data_list", [])
    for side in side_data_list:
        if "rotation" in side:
            rotation = int(side["rotation"])
            break
    # Check tags as fallback
    if rotation == 0:
        tags = video_stream.get("tags", {})
        rotation = int(tags.get("rotate", 0))

    # If rotated 90 or 270 degrees, effective width and height are swapped
    if abs(rotation) in (90, 270):
        effective_width = height
        effective_height = width
    else:
        effective_width = width
        effective_height = height

    # Determine orientation
    if effective_width > effective_height:
        orientation = "landscape"
    elif effective_height > effective_width:
        orientation = "portrait"
    else:
        orientation = "square"

    # Determine duration: check stream first, then format
    duration_str = video_stream.get("duration") or data.get("format", {}).get("duration", "0")
    try:
        duration = float(duration_str)
    except (ValueError, TypeError):
        duration = 0.0

    # Determine fps
    fps_str = video_stream.get("r_frame_rate", "30/1")
    try:
        if "/" in fps_str:
            num, den = fps_str.split("/")
            fps = float(num) / float(den) if float(den) != 0 else 30.0
        else:
            fps = float(fps_str)
    except Exception:
        fps = 30.0

    return VideoMetadata(
        duration=round(duration, 2),
        width=effective_width,
        height=effective_height,
        fps=round(fps, 2),
        orientation=orientation,
    )
