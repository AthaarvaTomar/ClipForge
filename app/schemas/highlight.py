import json
import re
from typing import Any

from pydantic import BaseModel, Field, model_validator


class HighlightMoment(BaseModel):
    """Schema representing an AI-detected highlight moment."""

    title: str = Field(..., max_length=255, description="Engaging clip title or headline")
    start_time: float = Field(..., ge=0.0, description="Start timestamp in seconds")
    end_time: float = Field(..., ge=0.0, description="End timestamp in seconds")
    hook: str = Field(default="", description="Catchy opening hook or quote")
    reason: str = Field(default="", description="Why this segment works well as a vertical clip")
    score: float = Field(default=8.0, ge=0.0, le=10.0, description="Engagement score (0-10)")

    @model_validator(mode="after")
    def validate_timestamps(self) -> "HighlightMoment":
        if self.end_time <= self.start_time:
            msg = (
                f"end_time ({self.end_time}) must be strictly greater "
                f"than start_time ({self.start_time})"
            )
            raise ValueError(msg)
        return self


class HighlightResponse(BaseModel):
    """Schema for highlight detection response containing multiple moments."""

    highlights: list[HighlightMoment] = Field(
        ...,
        description="List of detected highlight moments",
    )


def extract_json_from_llm_text(text: str) -> str:
    """Extract valid JSON string from LLM output, handling fences and noise."""
    cleaned = text.strip()

    # Match ```json ... ``` or ``` ... ```
    fence_pattern = r"```(?:json)?\s*([\s\S]*?)\s*```"
    fence_match = re.search(fence_pattern, cleaned, re.IGNORECASE)
    if fence_match:
        cleaned = fence_match.group(1).strip()

    # If starts with [ or {, locate the matching bracket
    if not (cleaned.startswith("{") or cleaned.startswith("[")):
        first_bracket = -1
        for idx, char in enumerate(cleaned):
            if char in ("{", "["):
                first_bracket = idx
                break
        if first_bracket != -1:
            cleaned = cleaned[first_bracket:]

    # Remove any trailing junk after last closing bracket
    last_bracket = -1
    for idx in range(len(cleaned) - 1, -1, -1):
        if cleaned[idx] in ("}", "]"):
            last_bracket = idx
            break
    if last_bracket != -1:
        cleaned = cleaned[: last_bracket + 1]

    return cleaned


def parse_and_validate_highlights_json(raw_text: str) -> list[HighlightMoment]:
    """Parse raw LLM response text into validated HighlightMoment list."""
    json_str = extract_json_from_llm_text(raw_text)
    try:
        data: Any = json.loads(json_str)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Failed to decode JSON from LLM output: {exc}") from exc

    if isinstance(data, dict):
        # Could be {"highlights": [...]} or {"clips": [...]} or {"moments": [...]}
        raw_list = (
            data.get("highlights") or data.get("clips") or data.get("moments") or data.get("data")
        )
        if raw_list is None:
            # If the dict is itself a single moment, wrap it
            if "start_time" in data and "end_time" in data:
                raw_list = [data]
            else:
                raise ValueError(
                    f"Expected 'highlights' key in LLM JSON output, got keys: {list(data.keys())}"
                )
    elif isinstance(data, list):
        raw_list = data
    else:
        raise ValueError(f"Unexpected JSON data type from LLM: {type(data)}")

    validated_moments: list[HighlightMoment] = []
    for item in raw_list:
        if isinstance(item, dict):
            # Normalize field names if LLM varied slightly
            title = str(item.get("title") or item.get("headline") or "Untitled Clip")
            start_time = float(item.get("start_time") or item.get("start") or 0.0)
            end_time = float(item.get("end_time") or item.get("end") or 0.0)
            hook = str(item.get("hook") or item.get("opening") or "")
            reason = str(item.get("reason") or item.get("explanation") or "")
            score = float(item.get("score") or item.get("virality") or 8.0)

            validated_moments.append(
                HighlightMoment(
                    title=title,
                    start_time=start_time,
                    end_time=end_time,
                    hook=hook,
                    reason=reason,
                    score=score,
                )
            )

    return validated_moments
