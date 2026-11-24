from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Monkey patch av.open to ignore removed `metadata_errors` in PyAV >= 14
import av

_orig_av_open = av.open


def _safe_av_open(*args: Any, **kwargs: Any) -> Any:
    kwargs.pop("metadata_errors", None)
    return _orig_av_open(*args, **kwargs)


av.open = _safe_av_open

from faster_whisper import WhisperModel  # noqa: E402


@dataclass
class WordDetail:
    """Word with precise timestamp and confidence."""

    word: str
    start: float
    end: float
    probability: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "word": self.word,
            "start": round(self.start, 2),
            "end": round(self.end, 2),
            "probability": round(self.probability, 3),
        }


@dataclass
class TranscriptionResult:
    """Full transcription with word-level breakdown."""

    language: str
    text: str
    words: list[dict[str, Any]]


class TranscriptionError(Exception):
    """Raised when transcription fails."""


def compute_transcription_progress(segment_end: float, duration: float) -> int:
    """Compute progress percentage (0-99) from segment end time and total audio duration.

    Guarantees progress never exceeds 99 until the transcript is saved.
    """
    if duration <= 0:
        return 0
    return min(99, max(0, int((segment_end / duration) * 100)))


_model_cache: dict[str, WhisperModel] = {}


def get_whisper_model(
    model_size: str = "tiny",
    device: str = "cpu",
    compute_type: str = "int8",
) -> WhisperModel:
    """Get or load a cached WhisperModel."""
    key = f"{model_size}_{device}_{compute_type}"
    if key not in _model_cache:
        _model_cache[key] = WhisperModel(
            model_size_or_path=model_size,
            device=device,
            compute_type=compute_type,
        )
    return _model_cache[key]


def transcribe_audio(
    audio_path: Path | str,
    model_size: str = "tiny",
    language: str | None = None,
    duration: float | None = None,
    on_progress: Callable[[int], None] | None = None,
) -> TranscriptionResult:
    """Transcribe an audio file using faster-whisper with word-level timestamps."""
    path = Path(audio_path)
    if not path.is_file():
        raise TranscriptionError(f"Audio file not found: {path}")

    try:
        model = get_whisper_model(model_size=model_size)
        segments, info = model.transcribe(
            str(path),
            language=language,
            word_timestamps=True,
            beam_size=5,
        )

        total_duration = (
            duration
            if (duration is not None and duration > 0)
            else getattr(info, "duration", 0.0)
        )

        full_text_parts: list[str] = []
        words_list: list[dict[str, Any]] = []

        for segment in segments:
            full_text_parts.append(segment.text.strip())
            if segment.words:
                for w in segment.words:
                    word_obj = WordDetail(
                        word=w.word.strip(),
                        start=w.start,
                        end=w.end,
                        probability=w.probability,
                    )
                    words_list.append(word_obj.to_dict())

            if on_progress and total_duration > 0:
                prog = compute_transcription_progress(segment.end, total_duration)
                on_progress(prog)

        full_text = " ".join(full_text_parts).strip()
        detected_language = info.language or "en"

        return TranscriptionResult(
            language=detected_language,
            text=full_text,
            words=words_list,
        )
    except Exception as e:
        raise TranscriptionError(f"Transcription failed: {e}") from e
