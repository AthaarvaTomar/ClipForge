"""Business logic and services package."""

from app.services.ass_builder import (
    ASSBuilder,
    ASSBuilderError,
    RemappedWord,
    hex_to_ass_color,
    remap_words_to_cuts,
)
from app.services.audio_extractor import AudioExtractionError, extract_audio
from app.services.ffmpeg_builder import (
    FFmpegBuilder,
    FFmpegBuilderError,
    build_cuts_filter,
    build_grade_filter,
    build_reframe_filter,
    extract_preview_frame,
    get_target_resolution,
)
from app.services.highlight_service import HighlightService
from app.services.job_service import JobService
from app.services.preset_service import PresetService
from app.services.timeline_engine import TimelineOperationError, apply
from app.services.timeline_service import (
    TimelineNotFoundError,
    TimelineService,
    TimelineVersionConflictError,
)
from app.services.transcription_service import (
    TranscriptionError,
    TranscriptionResult,
    transcribe_audio,
)
from app.services.video_probe import VideoMetadata, VideoProbeError, probe_video

__all__ = [
    "ASSBuilder",
    "ASSBuilderError",
    "AudioExtractionError",
    "FFmpegBuilder",
    "FFmpegBuilderError",
    "HighlightService",
    "JobService",
    "PresetService",
    "RemappedWord",
    "TimelineNotFoundError",
    "TimelineOperationError",
    "TimelineService",
    "TimelineVersionConflictError",
    "TranscriptionError",
    "TranscriptionResult",
    "VideoMetadata",
    "VideoProbeError",
    "apply",
    "build_cuts_filter",
    "build_grade_filter",
    "build_reframe_filter",
    "extract_audio",
    "extract_preview_frame",
    "get_target_resolution",
    "hex_to_ass_color",
    "probe_video",
    "remap_words_to_cuts",
    "transcribe_audio",
]
