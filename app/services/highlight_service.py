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
