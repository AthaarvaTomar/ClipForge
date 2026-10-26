"""Service for detecting audio silences and transcript filler words (Milestone I2)."""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from app.services.ffmpeg_builder import FFmpegBuilderError

logger = logging.getLogger(__name__)

COMMON_FILLER_WORDS = {
    "um",
    "uh",
    "er",
    "ah",
    "like",
    "you know",
    "hmm",
    "uh-huh",
    "mhm",
}


class SilenceFillerService:
    """Detects audio silences using FFmpeg and filler words from word-level transcripts."""

    @staticmethod
    def detect_silences(
        video_path: Path | str,
        noise_threshold_db: float = -30.0,
        min_duration_sec: float = 0.4,
        timeout: float = 60.0,
    ) -> list[dict[str, Any]]:
        """Run FFmpeg silencedetect to identify dead audio gaps.

        Returns: [{'start_time': 2.5, 'end_time': 4.1, 'duration': 1.6}, ...]
        """
        p = Path(video_path).resolve()
        if not p.is_file():
            raise FileNotFoundError(f"Video file not found: {p}")

        ffmpeg_bin = shutil.which("ffmpeg")
        if not ffmpeg_bin:
            raise FFmpegBuilderError("ffmpeg executable not found in PATH")

        cmd = [
            ffmpeg_bin,
            "-i",
            str(p),
            "-af",
            f"silencedetect=noise={noise_threshold_db:.1f}dB:d={min_duration_sec:.2f}",
            "-f",
            "null",
            "-",
        ]

        try:
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            stderr = res.stderr
        except subprocess.TimeoutExpired:
            logger.warning("FFmpeg silencedetect timed out after %ss for %s", timeout, p)
            return []
        except Exception as e:
            logger.warning("Error running silencedetect: %s", e)
            return []

        # Parse FFmpeg output
        # [silencedetect @ 0x...] silence_start: 3.42
        # [silencedetect @ 0x...] silence_end: 5.12 | silence_duration: 1.70
        silences: list[dict[str, Any]] = []
        current_start: float | None = None

        start_regex = re.compile(r"silence_start:\s*([0-9.]+)")
        end_pattern = r"silence_end:\s*([0-9.]+)(?:\s*\|\s*silence_duration:\s*([0-9.]+))?"
        end_regex = re.compile(end_pattern)

        for line in stderr.splitlines():
            s_match = start_regex.search(line)
            if s_match:
                current_start = float(s_match.group(1))
                continue

            e_match = end_regex.search(line)
            if e_match and current_start is not None:
                end_time = float(e_match.group(1))
                if e_match.group(2):
                    dur = float(e_match.group(2))
                else:
                    dur = max(0.0, end_time - current_start)

                silences.append(
                    {
                        "start_time": round(current_start, 3),
                        "end_time": round(end_time, 3),
                        "duration": round(dur, 3),
                    }
                )
                current_start = None

        return silences

    @staticmethod
    def detect_fillers(
        words: list[dict[str, Any]],
        custom_fillers: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Identify filler words in transcript word timestamps.

        Returns: [{'word': 'um', 'start_time': 1.2, 'end_time': 1.5, 'confidence': 0.98}, ...]
        """
        filler_set = (custom_fillers or COMMON_FILLER_WORDS)
        detected: list[dict[str, Any]] = []

        for w in words:
            raw_word = str(w.get("word", "")).strip().lower()
            clean_word = re.sub(r"[^\w\s-]", "", raw_word).strip()
            if not clean_word:
                continue

            if clean_word in filler_set:
                start_s = float(w.get("start", 0.0))
                end_s = float(w.get("end", start_s + 0.3))
                prob = float(w.get("probability", w.get("confidence", 1.0)))

                detected.append(
                    {
                        "word": clean_word,
                        "start_time": round(start_s, 3),
                        "end_time": round(end_s, 3),
                        "confidence": round(prob, 2),
                    }
                )

        return detected
