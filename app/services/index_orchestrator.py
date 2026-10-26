"""Orchestrator for the complete Footage Indexing pipeline (Milestone I6)."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.transcript import Transcript
from app.models.video import Video
from app.models.video_index import VideoIndex
from app.services.audio_extractor import extract_audio
from app.services.highlight_service import HighlightService
from app.services.scene_detector import SceneDetectorService
from app.services.silence_detector import SilenceFillerService
from app.services.take_detector import RepeatedTakeService
from app.services.transcription_service import transcribe_audio
from app.services.video_probe import probe_video
from app.services.visual_service import VisualUnderstandingService

logger = logging.getLogger(__name__)


class IndexOrchestratorService:
    """Executes all stages of footage indexing and persists the aggregated VideoIndex."""

    @classmethod
    def index_video(
        cls,
        db: Session,
        video_id: str,
        on_progress: Callable[[int, str], None] | None = None,
    ) -> VideoIndex:
        """Run complete indexing pipeline on video."""
        def update_stage(pct: int, msg: str) -> None:
            if on_progress:
                on_progress(pct, msg)

        # 1. Fetch Video
        video = db.scalar(select(Video).where(Video.id == video_id))
        if not video:
            raise ValueError(f"Video with ID '{video_id}' not found")

        v_path = Path(video.file_path)
        if not v_path.is_file():
            raise FileNotFoundError(f"Video file missing on disk: {v_path}")

        meta = probe_video(v_path)
        duration = meta.duration or (video.duration or 30.0)

        # Find or create VideoIndex record
        v_idx = db.scalar(select(VideoIndex).where(VideoIndex.video_id == video_id))
        if not v_idx:
            v_idx = VideoIndex(video_id=video_id, status="INDEXING")
            db.add(v_idx)
            db.commit()
            db.refresh(v_idx)
        else:
            v_idx.status = "INDEXING"
            v_idx.error_message = None
            db.commit()

        try:
            # ─── Stage 1: Transcription (0% -> 20%) ──────────────────────────────
            update_stage(5, "Checking or generating transcript")
            transcript_record = db.scalar(select(Transcript).where(Transcript.video_id == video_id))
            if not transcript_record:
                update_stage(10, "Extracting audio and transcribing with faster-whisper")
                wav_path = extract_audio(str(v_path))
                t_res = transcribe_audio(wav_path)
                transcript_record = Transcript(
                    video_id=video_id,
                    language=t_res.language,
                    text=t_res.text,
                    words=t_res.words,
                )
                db.add(transcript_record)
                db.commit()
                db.refresh(transcript_record)

            transcript_text = transcript_record.text or ""
            transcript_words = transcript_record.words or []

            # ─── Stage 2: Scene Detection (20% -> 35%) ───────────────────────────
            update_stage(20, "Detecting visual scene boundaries")
            scenes = SceneDetectorService.detect_scenes(v_path)
            update_stage(35, f"Detected {len(scenes)} scenes")

            # ─── Stage 3: Silences & Fillers (35% -> 50%) ─────────────────────────
            update_stage(40, "Detecting audio silences and filler words")
            silences = SilenceFillerService.detect_silences(v_path)
            fillers = SilenceFillerService.detect_fillers(transcript_words)
            update_stage(50, f"Found {len(silences)} silences, {len(fillers)} filler words")

            # ─── Stage 4: Repeated Takes (50% -> 65%) ────────────────────────────
            update_stage(55, "Analyzing repeated takes with RapidFuzz")
            repeated_takes = RepeatedTakeService.detect_repeated_takes(words=transcript_words)
            update_stage(65, f"Identified {len(repeated_takes)} repeated take groups")

            # ─── Stage 5: Visual Understanding (65% -> 80%) ──────────────────────
            update_stage(70, "Analyzing visual scene frames")
            visuals = VisualUnderstandingService.analyze_scenes(
                v_path, scenes=scenes, max_scenes=10
            )
            update_stage(80, f"Generated descriptions for {len(visuals)} scenes")

            # ─── Stage 6: Chapters, Hook, Highlights (80% -> 95%) ─────────────────
            update_stage(85, "Synthesizing chapters, viral hook and highlights")
            insights = HighlightService.detect_index_insights(
                text=transcript_text,
                words=transcript_words,
                scenes=scenes,
                visuals=visuals,
                repeated_takes=repeated_takes,
                duration=duration,
            )
            update_stage(95, "Persisting full footage index")

            # ─── Stage 7: Persist VideoIndex (100%) ────────────────────────────────
            v_idx.scenes = scenes
            v_idx.silences = silences
            v_idx.fillers = fillers
            v_idx.repeated_takes = repeated_takes
            v_idx.visuals = visuals
            v_idx.chapters = insights.get("chapters", [])
            v_idx.hook = insights.get("hook")
            v_idx.status = "READY"
            v_idx.error_message = None
            db.commit()
            db.refresh(v_idx)

            update_stage(100, "Footage indexing complete")
            return v_idx

        except Exception as e:
            logger.exception("Footage indexing failed for video %s: %s", video_id, e)
            v_idx.status = "FAILED"
            v_idx.error_message = str(e)
            db.commit()
            raise
