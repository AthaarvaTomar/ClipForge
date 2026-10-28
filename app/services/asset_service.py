"""UI asset generation for uploaded videos (Task R1).

Produces, per video, under ``settings.PROXY_DIR/<video_id>/``:

* ``proxy.mp4``       360p H.264 proxy for fast browser playback
* ``thumbs/NNNN.jpg`` evenly spaced thumbnails
* ``strip.jpg``       all thumbnails tiled horizontally in one image
* ``waveform.json``   normalised audio peaks
"""

from __future__ import annotations

import array
import json
import math
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.config import settings
from app.services.ffmpeg_builder import check_has_audio

PROXY_HEIGHT = 360
THUMB_WIDTH = 160
MAX_THUMBS = 120
MIN_THUMB_INTERVAL = 1.0
WAVEFORM_SAMPLE_RATE = 4000
MAX_PEAKS_PER_SECOND = 20.0
MAX_PEAKS = 60000


class AssetGenerationError(Exception):
    """Raised when a proxy, thumbnail or waveform could not be generated."""


def asset_dir(video_id: str) -> Path:
    return Path(settings.PROXY_DIR) / video_id


def proxy_path(video_id: str) -> Path:
    return asset_dir(video_id) / "proxy.mp4"


def thumbs_dir(video_id: str) -> Path:
    return asset_dir(video_id) / "thumbs"


def strip_path(video_id: str) -> Path:
    return asset_dir(video_id) / "strip.jpg"


def waveform_path(video_id: str) -> Path:
    return asset_dir(video_id) / "waveform.json"


def manifest_path(video_id: str) -> Path:
    return asset_dir(video_id) / "assets.json"


def _ffmpeg() -> str:
    ffmpeg_bin = shutil.which("ffmpeg")
    if not ffmpeg_bin:
        raise AssetGenerationError("ffmpeg executable not found in PATH")
    return ffmpeg_bin


def _run(cmd: list[str], timeout: float) -> None:
    try:
        subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=timeout)
    except subprocess.CalledProcessError as e:
        raise AssetGenerationError(f"ffmpeg failed ({e.returncode}): {e.stderr[-800:]}") from e
    except subprocess.TimeoutExpired as e:
        raise AssetGenerationError(f"ffmpeg timed out after {timeout}s") from e


def thumbnail_interval(duration: float) -> float:
    """Seconds between thumbnails: at least 1 s, at most MAX_THUMBS thumbnails overall."""
    return max(MIN_THUMB_INTERVAL, duration / MAX_THUMBS) if duration > 0 else MIN_THUMB_INTERVAL


def generate_proxy(source: Path, out: Path, timeout: float) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.stem + ".part.mp4")
    cmd = [
        _ffmpeg(), "-y", "-i", str(source),
        "-map", "0:v:0", "-map", "0:a:0?",
        "-vf", f"scale=-2:{PROXY_HEIGHT}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "28", "-pix_fmt", "yuv420p",
        "-g", "30", "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart",
        str(tmp),
    ]  # fmt: skip
    try:
        _run(cmd, timeout)
        tmp.replace(out)
    finally:
        tmp.unlink(missing_ok=True)
    return out


def generate_thumbnails(
    source: Path, video_id: str, duration: float, timeout: float
) -> dict[str, Any]:
    """Create individual thumbnails plus one tiled strip. Returns thumbnail metadata."""
    t_dir = thumbs_dir(video_id)
    if t_dir.exists():
        shutil.rmtree(t_dir)
    t_dir.mkdir(parents=True, exist_ok=True)

    interval = thumbnail_interval(duration)
    vf = f"fps=1/{interval:.4f},scale={THUMB_WIDTH}:-2"
    _run(
        [_ffmpeg(), "-y", "-i", str(source), "-an", "-vf", vf, "-q:v", "5",
         str(t_dir / "%04d.jpg")],
        timeout,
    )  # fmt: skip
    names = sorted(p.name for p in t_dir.glob("*.jpg"))
    if not names:
        # Very short videos can yield zero frames at fps=1/interval; grab the first frame.
        _run(
            [_ffmpeg(), "-y", "-i", str(source), "-an", "-frames:v", "1",
             "-vf", f"scale={THUMB_WIDTH}:-2", "-q:v", "5", str(t_dir / "0001.jpg")],
            timeout,
        )  # fmt: skip
        names = sorted(p.name for p in t_dir.glob("*.jpg"))
    if not names:
        raise AssetGenerationError("No thumbnails could be generated")

    _run(
        [_ffmpeg(), "-y", "-framerate", "1", "-i", str(t_dir / "%04d.jpg"),
         "-vf", f"tile={len(names)}x1", "-frames:v", "1", "-q:v", "5",
         str(strip_path(video_id))],
        timeout,
    )  # fmt: skip
    return {"count": len(names), "interval": round(interval, 4), "width": THUMB_WIDTH}


def compute_peaks(chunks: Callable[[], bytes], samples_per_peak: int) -> list[float]:
    """Reduce a stream of s16le mono samples to normalised peak values (0..1)."""
    peaks: list[float] = []
    carry = array.array("h")
    while True:
        raw = chunks()
        if not raw:
            break
        raw = raw[: len(raw) - (len(raw) % 2)]
        samples = array.array("h")
        samples.frombytes(raw)
        if carry:
            samples = carry + samples
            carry = array.array("h")
        usable = len(samples) - (len(samples) % samples_per_peak)
        for i in range(0, usable, samples_per_peak):
            window = samples[i : i + samples_per_peak]
            peaks.append(max(max(window), -min(window)) / 32768.0)
        if usable < len(samples):
            carry = samples[usable:]
    if carry:
        peaks.append(max(max(carry), -min(carry)) / 32768.0)
    return [round(min(1.0, p), 3) for p in peaks]


def generate_waveform(
    source: Path, video_id: str, duration: float, timeout: float
) -> dict[str, Any]:
    """Compute audio peaks JSON. Videos without audio get an empty peak list."""
    has_audio = check_has_audio(source)
    pps = MAX_PEAKS_PER_SECOND
    if duration > 0:
        pps = max(0.5, min(MAX_PEAKS_PER_SECOND, MAX_PEAKS / duration))
    samples_per_peak = max(1, int(WAVEFORM_SAMPLE_RATE / pps))
    pps = WAVEFORM_SAMPLE_RATE / samples_per_peak

    peaks: list[float] = []
    if has_audio:
        cmd = [
            _ffmpeg(), "-v", "error", "-i", str(source), "-vn", "-ac", "1",
            "-ar", str(WAVEFORM_SAMPLE_RATE), "-f", "s16le", "pipe:1",
        ]  # fmt: skip
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        assert proc.stdout is not None and proc.stderr is not None
        try:
            peaks = compute_peaks(lambda: proc.stdout.read(1 << 20), samples_per_peak)  # type: ignore[union-attr]
            retcode = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired as e:
            proc.kill()
            raise AssetGenerationError(f"waveform extraction timed out after {timeout}s") from e
        finally:
            if proc.poll() is None:
                proc.kill()
        if retcode != 0:
            err = proc.stderr.read().decode("utf-8", errors="ignore")[-500:]
            raise AssetGenerationError(f"waveform extraction failed: {err}")

    data = {
        "video_id": video_id,
        "has_audio": has_audio,
        "duration": round(duration, 3),
        "peaks_per_second": round(pps, 4),
        "peaks": peaks,
    }
    waveform_path(video_id).write_text(json.dumps(data), encoding="utf-8")
    return data


def assets_ready(video_id: str) -> bool:
    return (
        proxy_path(video_id).is_file()
        and strip_path(video_id).is_file()
        and waveform_path(video_id).is_file()
        and manifest_path(video_id).is_file()
    )


def read_manifest(video_id: str) -> dict[str, Any] | None:
    path = manifest_path(video_id)
    if not path.is_file():
        return None
    try:
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data


def generate_assets(
    video_id: str,
    source: Path,
    duration: float | None,
    force: bool = False,
    on_progress: Callable[[int], None] | None = None,
) -> dict[str, Any]:
    """Generate all UI assets for a video. Idempotent unless ``force`` is set."""
    if not force and assets_ready(video_id):
        manifest = read_manifest(video_id)
        if manifest is not None:
            if on_progress:
                on_progress(100)
            return manifest

    if not source.is_file():
        raise AssetGenerationError(f"Source video file not found: {source}")

    timeout = settings.FFMPEG_TIMEOUT_SECONDS
    dur = float(duration or 0.0)
    asset_dir(video_id).mkdir(parents=True, exist_ok=True)
    manifest_path(video_id).unlink(missing_ok=True)

    def report(pct: int) -> None:
        if on_progress:
            on_progress(pct)

    report(5)
    generate_proxy(source, proxy_path(video_id), timeout)
    report(40)
    thumbs = generate_thumbnails(source, video_id, dur, timeout)
    report(70)
    wave = generate_waveform(source, video_id, dur, timeout)
    report(95)

    manifest = {
        "video_id": video_id,
        "duration": round(dur, 3),
        "proxy_height": PROXY_HEIGHT,
        "thumbnails": thumbs,
        "waveform": {
            "peaks_per_second": wave["peaks_per_second"],
            "count": len(wave["peaks"]),
            "has_audio": wave["has_audio"],
        },
        "generated_with": math.floor(0),
    }
    manifest.pop("generated_with")
    manifest_path(video_id).write_text(json.dumps(manifest), encoding="utf-8")
    report(100)
    return manifest


def delete_assets(video_id: str) -> None:
    shutil.rmtree(asset_dir(video_id), ignore_errors=True)
