from datetime import datetime

from pydantic import BaseModel, ConfigDict


class WordTimestamp(BaseModel):
    word: str
    start: float
    end: float
    probability: float


class TranscriptResponse(BaseModel):
    id: str
    video_id: str
    language: str
    text: str
    words: list[WordTimestamp]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
