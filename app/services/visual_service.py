"""Service for visual scene understanding using Gemini Vision and Ollama fallback (Milestone I4)."""

from __future__ import annotations

import base64
import json
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any

import httpx

from app.config import settings
from app.services.ffmpeg_builder import FFmpegBuilderError

logger = logging.getLogger(__name__)


def extract_frame_bytes(video_path: Path | str, timestamp: float, timeout: float = 20.0) -> bytes:
    """Extract a single frame as JPEG bytes at timestamp."""
    ffmpeg_bin = shutil.which("ffmpeg")
    if not ffmpeg_bin:
        raise FFmpegBuilderError("ffmpeg executable not found in PATH")

    safe_t = max(0.0, timestamp)
    cmd = [
        ffmpeg_bin,
        "-y",
        "-ss",
        f"{safe_t:.3f}",
        "-i",
        str(Path(video_path).resolve()),
        "-vframes",
        "1",
        "-q:v",
        "2",
        "-f",
        "image2",
        "pipe:1",
    ]
    res = subprocess.run(cmd, capture_output=True, check=True, timeout=timeout)
    return res.stdout


class VisualUnderstandingService:
    """Samples frames from video scenes and generates visual descriptions and tags."""

    @staticmethod
    def describe_scene_frame(
        image_bytes: bytes,
        scene_index: int,
        timestamp: float,
        http_client: httpx.Client | None = None,
    ) -> dict[str, Any]:
        """Describe a single scene frame using Gemini Vision or Ollama fallback."""
        b64_img = base64.b64encode(image_bytes).decode("utf-8")
        prompt = (
            "Analyze this video frame. Describe the visual scene in 1-2 concise sentences. "
            "Output strictly valid JSON with keys 'caption' (string) and 'tags' (list of tags). "
            "Example: {\"caption\": \"A person speaking in a studio.\", \"tags\": [\"speaker\"]}"
        )

        # 1. Try Gemini Vision REST API
        if settings.GEMINI_API_KEY:
            try:
                url = (
                    f"https://generativelanguage.googleapis.com/v1beta/models/"
                    f"{settings.GEMINI_MODEL}:generateContent?key={settings.GEMINI_API_KEY}"
                )
                payload = {
                    "contents": [
                        {
                            "parts": [
                                {"text": prompt},
                                {
                                    "inlineData": {
                                        "mimeType": "image/jpeg",
                                        "data": b64_img,
                                    }
                                },
                            ]
                        }
                    ],
                    "generationConfig": {
                        "responseMimeType": "application/json",
                        "temperature": 0.2,
                    },
                }

                client = http_client or httpx.Client(timeout=30.0)
                try:
                    res = client.post(url, json=payload)
                    res.raise_for_status()
                    data = res.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [{}])
                        text = parts[0].get("text", "")
                        parsed = json.loads(text)
                        return {
                            "scene_index": scene_index,
                            "timestamp": round(timestamp, 3),
                            "caption": str(parsed.get("caption", f"Scene at {timestamp:.1f}s")),
                            "tags": list(parsed.get("tags", ["scene", "video"])),
                        }
                finally:
                    if http_client is None:
                        client.close()
            except Exception as e:
                logger.warning("Gemini Vision call failed for scene %s: %s", scene_index, e)

        # 2. Try Ollama Vision fallback (e.g. llava)
        if settings.OLLAMA_BASE_URL:
            try:
                base_url = settings.OLLAMA_BASE_URL.rstrip("/")
                url = f"{base_url}/api/generate"
                ollama_payload: dict[str, Any] = {
                    "model": "llava",
                    "prompt": prompt,
                    "stream": False,
                    "format": "json",
                    "images": [b64_img],
                }
                client = http_client or httpx.Client(timeout=30.0)
                try:
                    res = client.post(url, json=ollama_payload)
                    if res.status_code == 200:
                        data = res.json()
                        resp_text = data.get("response", "")
                        parsed = json.loads(resp_text)
                        return {
                            "scene_index": scene_index,
                            "timestamp": round(timestamp, 3),
                            "caption": str(parsed.get("caption", f"Scene at {timestamp:.1f}s")),
                            "tags": list(parsed.get("tags", ["scene", "video"])),
                        }
                finally:
                    if http_client is None:
                        client.close()
            except Exception as e:
                logger.warning("Ollama Vision call failed for scene %s: %s", scene_index, e)

        # 3. Deterministic Heuristic Fallback
        return {
            "scene_index": scene_index,
            "timestamp": round(timestamp, 3),
            "caption": f"Visual scene {scene_index + 1} captured at timestamp {timestamp:.1f}s.",
            "tags": ["scene", "footage", "clip", f"scene_{scene_index + 1}"],
        }

    @classmethod
    def analyze_scenes(
        cls,
        video_path: Path | str,
        scenes: list[dict[str, Any]],
        http_client: httpx.Client | None = None,
        max_scenes: int = 15,
    ) -> list[dict[str, Any]]:
        """Sample one frame per scene and describe visual content."""
        results: list[dict[str, Any]] = []

        # Cap analyzed scenes to max_scenes for efficiency
        target_scenes = scenes[:max_scenes]

        for sc in target_scenes:
            sc_idx = int(sc.get("index", 0))
            s_time = float(sc.get("start_time", 0.0))
            e_time = float(sc.get("end_time", s_time + 1.0))
            mid_t = (s_time + e_time) / 2.0

            try:
                frame_bytes = extract_frame_bytes(video_path, mid_t)
                desc = cls.describe_scene_frame(
                    image_bytes=frame_bytes,
                    scene_index=sc_idx,
                    timestamp=mid_t,
                    http_client=http_client,
                )
                results.append(desc)
            except Exception as e:
                logger.warning("Failed to extract or describe frame at %ss: %s", mid_t, e)
                results.append(
                    {
                        "scene_index": sc_idx,
                        "timestamp": round(mid_t, 3),
                        "caption": f"Scene {sc_idx + 1} at {mid_t:.1f}s",
                        "tags": ["scene", "video"],
                    }
                )

        return results
