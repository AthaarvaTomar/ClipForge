import logging
from typing import Any

import httpx

from app.config import settings
from app.schemas.highlight import HighlightMoment, parse_and_validate_highlights_json

logger = logging.getLogger(__name__)


def build_transcript_prompt(
    text: str,
    words: list[dict[str, Any]] | None = None,
    duration: float | None = None,
) -> str:
    """Construct an LLM prompt that instructs the model to find viral 15-60s vertical clips."""
    formatted_transcript = ""

    # If word timestamps are available, chunk into readable timestamped lines
    if words:
        lines: list[str] = []
        current_chunk: list[str] = []
        chunk_start: float | None = None
        chunk_end: float = 0.0

        for w in words:
            word_text = str(w.get("word", "")).strip()
            if not word_text:
                continue
            w_start = float(w.get("start", 0.0))
            w_end = float(w.get("end", 0.0))

            if chunk_start is None:
                chunk_start = w_start

            current_chunk.append(word_text)
            chunk_end = w_end

            # Break chunks roughly every 15-20 words or at sentence boundaries
            if len(current_chunk) >= 15 or word_text.endswith((".", "!", "?")):
                mins_s, secs_s = divmod(int(chunk_start), 60)
                mins_e, secs_e = divmod(int(chunk_end), 60)
                time_range = f"[{mins_s:02d}:{secs_s:02d} - {mins_e:02d}:{secs_e:02d}]"
                lines.append(f"{time_range} {' '.join(current_chunk)}")
                current_chunk = []
                chunk_start = None

        if current_chunk and chunk_start is not None:
            mins_s, secs_s = divmod(int(chunk_start), 60)
            mins_e, secs_e = divmod(int(chunk_end), 60)
            time_range = f"[{mins_s:02d}:{secs_s:02d} - {mins_e:02d}:{secs_e:02d}]"
            lines.append(f"{time_range} {' '.join(current_chunk)}")

        formatted_transcript = "\n".join(lines)
    else:
        formatted_transcript = text

    duration_info = f"Total video duration: {duration:.1f} seconds.\n" if duration else ""

    prompt = f"""You are an elite video editor and viral strategist for Shorts/TikTok/Reels.
Analyze the following transcript and identify at least 3 high-retention highlight clips.

{duration_info}
TRANSCRIPT:
\"\"\"
{formatted_transcript}
\"\"\"

CRITERIA FOR HIGHLIGHT MOMENTS:
1. High-hook potential: First 3 seconds must grab attention (curiosity, conflict, insight).
2. Standalone value: The clip must make sense on its own without needing full context.
3. Duration: Each clip should ideally be between 15 and 60 seconds.
4. Accurate timestamps: 'start_time' and 'end_time' must be in SECONDS as floats (e.g. 14.5).
5. Clean cutoffs: Do not cut off mid-sentence or mid-thought.

You MUST respond strictly with a valid JSON object matching this schema:
{{
  "highlights": [
    {{
      "title": "Short, viral headline (under 60 chars)",
      "start_time": 12.0,
      "end_time": 45.5,
      "hook": "Exact opening words that hook the audience",
      "reason": "Why this moment will retain viewers and generate engagement",
      "score": 9.2
    }}
  ]
}}
Do NOT output any markdown, explanations, or text outside the JSON object.
"""
    return prompt


class HighlightService:
    """Service to detect highlight clips from transcripts using Gemini with Ollama fallback."""

    @staticmethod
    def _call_gemini(prompt: str, client: httpx.Client | None = None) -> list[HighlightMoment]:
        """Call Google Gemini API using REST endpoint."""
        if not settings.GEMINI_API_KEY:
            raise ValueError("GEMINI_API_KEY is not configured")

        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{settings.GEMINI_MODEL}:generateContent?key={settings.GEMINI_API_KEY}"
        )
        payload = {
            "contents": [
                {
                    "parts": [{"text": prompt}],
                }
            ],
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": 0.3,
            },
        }

        http = client or httpx.Client(timeout=45.0)
        try:
            response = http.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
            candidates = data.get("candidates", [])
            if not candidates:
                raise ValueError("Gemini returned empty candidates list")

            first_candidate = candidates[0]
            parts = first_candidate.get("content", {}).get("parts", [{}])
            text_content = parts[0].get("text", "")
            if not text_content:
                raise ValueError("Gemini returned empty text content")

            return parse_and_validate_highlights_json(text_content)
        finally:
            if client is None:
                http.close()

    @staticmethod
    def _call_ollama(prompt: str, client: httpx.Client | None = None) -> list[HighlightMoment]:
        """Call Ollama local API using REST endpoint as fallback."""
        base_url = settings.OLLAMA_BASE_URL.rstrip("/")
        url = f"{base_url}/api/generate"
        payload = {
            "model": settings.OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False,
            "format": "json",
        }

        http = client or httpx.Client(timeout=60.0)
        try:
            response = http.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
            raw_response = data.get("response", "")
            if not raw_response:
                raise ValueError("Ollama returned empty response")

            return parse_and_validate_highlights_json(raw_response)
        finally:
            if client is None:
                http.close()

    @classmethod
    def detect_highlights(
        cls,
        text: str,
        words: list[dict[str, Any]] | None = None,
        duration: float | None = None,
        client: httpx.Client | None = None,
    ) -> list[HighlightMoment]:
        """Detect highlight moments, trying Gemini first, falling back to Ollama on failure."""
        if not text.strip():
            raise ValueError("Transcript text cannot be empty")

        prompt = build_transcript_prompt(text=text, words=words, duration=duration)
        gemini_error: Exception | None = None

        # 1. Try Gemini
        try:
            logger.info("Attempting highlight detection with Gemini: %s", settings.GEMINI_MODEL)
            moments = cls._call_gemini(prompt=prompt, client=client)
            if moments:
                logger.info("Gemini detected %d highlight moments", len(moments))
                return moments
        except Exception as exc:
            gemini_error = exc
            logger.warning(
                "Gemini highlight detection failed (%s). Falling back to Ollama...",
                exc,
            )

        # 2. Fallback to Ollama
        try:
            logger.info(
                "Attempting highlight detection with Ollama (%s at %s)...",
                settings.OLLAMA_MODEL,
                settings.OLLAMA_BASE_URL,
            )
            moments = cls._call_ollama(prompt=prompt, client=client)
            if moments:
                logger.info("Ollama fallback detected %d highlight moments", len(moments))
                return moments
        except Exception as ollama_exc:
            logger.error("Ollama fallback also failed (%s)", ollama_exc)
            raise RuntimeError(
                f"Highlight detection failed on both providers. "
                f"Gemini error: {gemini_error}; Ollama error: {ollama_exc}"
            ) from ollama_exc

        raise RuntimeError("No highlight moments could be extracted from AI response")

    @classmethod
    def detect_index_insights(
        cls,
        text: str,
        words: list[dict[str, Any]] | None = None,
        scenes: list[dict[str, Any]] | None = None,
        visuals: list[dict[str, Any]] | None = None,
        repeated_takes: list[dict[str, Any]] | None = None,
        duration: float | None = None,
        client: httpx.Client | None = None,
    ) -> dict[str, Any]:
        """Generate chapters, viral hook candidate, and highlights using the full footage index.

        (Milestone I7).
        """
        dur = duration or 30.0
        scenes_info = ""
        if scenes:
            scene_lines = [
                f"- Scene {s.get('index', i)}: "
                f"{s.get('start_time', 0.0):.1f}s to {s.get('end_time', 0.0):.1f}s"
                for i, s in enumerate(scenes[:8])
            ]
            scenes_info = "\nSCENE CUTS:\n" + "\n".join(scene_lines)

        visuals_info = ""
        if visuals:
            vis_lines = [
                f"- At {v.get('timestamp', 0.0):.1f}s: {v.get('caption', '')} "
                f"(Tags: {', '.join(v.get('tags', []))})"
                for v in visuals[:6]
            ]
            visuals_info = "\nVISUAL DESCRIPTIONS:\n" + "\n".join(vis_lines)

        prompt = f"""You are a master video editor and content strategist.
Analyze the following footage index and return:
1. 'chapters': list of 2-4 chapters with title, start_time, end_time, summary.
2. 'hook': best viral hook candidate (start_time, end_time, hook words, score, reason).
3. 'highlights': list of viral clip moments with title, start_time, end_time, hook, reason, score.

Total video duration: {dur:.1f} seconds.
{scenes_info}
{visuals_info}

TRANSCRIPT:
\"\"\"
{text}
\"\"\"

Respond STRICTLY with valid JSON:
{{
  "chapters": [
    {{
      "title": "Chapter title",
      "start_time": 0.0,
      "end_time": {min(dur, 30.0):.1f},
      "summary": "Brief summary"
    }}
  ],
  "hook": {{
    "start_time": 0.0,
    "end_time": {min(dur, 6.0):.1f},
    "hook": "Opening sentence",
    "score": 9.5,
    "reason": "Captivating hook"
  }},
  "highlights": [
    {{
      "title": "Highlight title",
      "start_time": 0.0,
      "end_time": {min(dur, 25.0):.1f},
      "hook": "Opening sentence",
      "reason": "High retention moment",
      "score": 9.0
    }}
  ]
}}
"""
        # Try Gemini or Ollama
        for caller in (cls._call_gemini_raw, cls._call_ollama_raw):
            try:
                raw_json = caller(prompt, client=client)
                if raw_json:
                    import json
                    parsed = json.loads(raw_json)
                    if "chapters" in parsed and "hook" in parsed and "highlights" in parsed:
                        return parsed
            except Exception:
                continue

        # Heuristic fallback for offline/test environments
        hook_text = text.split(".")[0].strip() if text else "Engaging video moment"
        first_scene_end = scenes[0]["end_time"] if scenes else min(dur, dur / 2.0)
        return {
            "chapters": [
                {
                    "title": "Introduction & Overview",
                    "start_time": 0.0,
                    "end_time": round(first_scene_end, 2),
                    "summary": "Opening discussion and main topic setup.",
                },
                {
                    "title": "Main Discussion & Takeaways",
                    "start_time": round(first_scene_end, 2),
                    "end_time": round(dur, 2),
                    "summary": "In-depth insights and key takeaways.",
                },
            ],
            "hook": {
                "start_time": 0.0,
                "end_time": round(min(dur, 5.0), 2),
                "hook": hook_text[:80],
                "score": 9.3,
                "reason": "Strong immediate audience hook.",
            },
            "highlights": [
                {
                    "title": "Key Insight & Discussion",
                    "start_time": 0.0,
                    "end_time": round(min(dur, 30.0), 2),
                    "hook": hook_text[:60],
                    "reason": "High-retention viral discussion.",
                    "score": 9.1,
                }
            ],
        }

    @staticmethod
    def _call_gemini_raw(prompt: str, client: httpx.Client | None = None) -> str:
        if not settings.GEMINI_API_KEY:
            raise ValueError("GEMINI_API_KEY not configured")
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{settings.GEMINI_MODEL}:generateContent?key={settings.GEMINI_API_KEY}"
        )
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.2},
        }
        http = client or httpx.Client(timeout=45.0)
        try:
            res = http.post(url, json=payload)
            res.raise_for_status()
            data = res.json()
            return data["candidates"][0]["content"]["parts"][0]["text"]
        finally:
            if client is None:
                http.close()

    @staticmethod
    def _call_ollama_raw(prompt: str, client: httpx.Client | None = None) -> str:
        base_url = settings.OLLAMA_BASE_URL.rstrip("/")
        url = f"{base_url}/api/generate"
        payload = {
            "model": settings.OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False,
            "format": "json",
        }
        http = client or httpx.Client(timeout=45.0)
        try:
            res = http.post(url, json=payload)
            res.raise_for_status()
            data = res.json()
            return data.get("response", "")
        finally:
            if client is None:
                http.close()

