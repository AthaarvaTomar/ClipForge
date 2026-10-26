import shutil
import subprocess
from pathlib import Path

# Ensure static ffmpeg binaries are in PATH if available
try:
    import static_ffmpeg

    static_ffmpeg.add_paths()
except Exception:
    pass


class AudioExtractionError(Exception):
    """Raised when audio extraction fails."""


def extract_audio(
    video_path: Path | str,
    output_wav_path: Path | str | None = None,
) -> Path:
    """Extract a 16kHz mono WAV audio file from a video for transcription."""
    in_path = Path(video_path)
    if not in_path.is_file():
        raise AudioExtractionError(f"Video file not found: {in_path}")

    if output_wav_path is None:
        out_path = in_path.with_suffix(".wav")
    else:
        out_path = Path(output_wav_path)

    out_path.parent.mkdir(parents=True, exist_ok=True)

    ffmpeg_bin = shutil.which("ffmpeg")
    if not ffmpeg_bin:
        raise AudioExtractionError("ffmpeg executable not found in PATH")

    cmd = [
        ffmpeg_bin,
        "-y",
        "-i",
        str(in_path),
        "-vn",
        "-acodec",
        "pcm_s16le",
        "-ar",
        "16000",
        "-ac",
        "1",
        str(out_path),
    ]

    try:
        subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            timeout=120,
        )
    except subprocess.CalledProcessError as e:
        raise AudioExtractionError(f"FFmpeg audio extraction failed: {e.stderr}") from e
    except subprocess.TimeoutExpired as e:
        raise AudioExtractionError("FFmpeg audio extraction timed out") from e

    if not out_path.exists() or out_path.stat().st_size == 0:
        raise AudioExtractionError(f"Audio extraction output is missing or empty: {out_path}")

    return out_path
