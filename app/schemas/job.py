from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class JobBase(BaseModel):
    job_type: str
    status: str = "PENDING"
    progress: int = Field(default=0, ge=0, le=100)
    error_message: str | None = None
    result_data: dict[str, Any] | None = None
    video_id: str | None = None
    clip_id: str | None = None


class JobResponse(JobBase):
    id: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DummyJobRequest(BaseModel):
    steps: int = Field(default=5, ge=1, le=100)
    delay_seconds: float = Field(default=0.01, ge=0.0, le=1.0)
