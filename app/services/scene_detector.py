"""Service for detecting video scene cuts using PySceneDetect (Milestone I1)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from app.services.video_probe import probe_video

logger = logging.getLogger(__name__)


class SceneDetectorService:
    """Detects scene boundaries in videos using PySceneDetect with fallback."""

    @staticmethod
    def detect_scenes(
        video_path: Path | str,
        threshold: float = 27.0,
        min_scene_len_sec: float = 0.5,
    ) -> list[dict[str, Any]]:
        """Detect scene cut boundaries.

        Returns list of dicts with keys: index, start_time, end_time, duration.
        """
        p = Path(video_path).resolve()
        if not p.is_file():
            raise FileNotFoundError(f"Video file not found: {p}")

        meta = probe_video(p)
        total_duration = meta.duration or 0.0

        try:
            from scenedetect import ContentDetector, detect  # type: ignore[import-untyped]

            min_len = int(min_scene_len_sec * (meta.fps or 30))
            detector = ContentDetector(threshold=threshold, min_scene_len=min_len)
            scene_list = detect(str(p), detector)

            if not scene_list:
                # No cut detected: entire video is 1 scene
                return [
                    {
                        "index": 0,
                        "start_time": 0.0,
                        "end_time": round(total_duration, 3),
                        "duration": round(total_duration, 3),
                    }
                ]

            def _tc_to_sec(tc: Any) -> float:
                if hasattr(tc, "seconds"):
                    return float(tc.seconds)
                if hasattr(tc, "get_seconds"):
                    return float(tc.get_seconds())
                return float(tc)

            result: list[dict[str, Any]] = []
            for idx, (start_tc, end_tc) in enumerate(scene_list):
                s_sec = round(_tc_to_sec(start_tc), 3)
                e_sec = round(_tc_to_sec(end_tc), 3)
                # Ensure last scene extends to full duration if close
                if idx == len(scene_list) - 1 and total_duration > e_sec:
                    e_sec = round(total_duration, 3)

                dur = round(max(0.01, e_sec - s_sec), 3)
                result.append(
                    {
                        "index": idx,
                        "start_time": s_sec,
                        "end_time": e_sec,
                        "duration": dur,
                    }
                )

            return result

        except Exception as e:
            logger.warning("PySceneDetect error: %s. Using single-scene fallback.", e)
            return [
                {
                    "index": 0,
                    "start_time": 0.0,
                    "end_time": round(total_duration, 3),
                    "duration": round(total_duration, 3),
                }
            ]
