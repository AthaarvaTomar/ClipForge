"""Helper script to run real highlight detection on any existing video in the database.

Usage:
    .\\.venv\\Scripts\\python -m tests.generate_real_highlights [video_id]
"""

import sys
import uuid

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.clip import Clip
from app.models.transcript import Transcript
from app.models.video import Video
from app.services.highlight_service import HighlightService


def run_detection(video_id: str | None = None) -> None:
    db = SessionLocal()
    try:
        if not video_id:
            # Pick the first video with a transcript
            transcript = db.scalar(select(Transcript))
            if not transcript:
                print("No transcripts found in the database. Please transcribe a video first.")
                return
            video_id = transcript.video_id

        video = db.scalar(select(Video).where(Video.id == video_id))
        if not video:
            print(f"Video '{video_id}' not found.")
            return

        transcript = db.scalar(select(Transcript).where(Transcript.video_id == video_id))
        if not transcript or not transcript.text.strip():
            print(f"Transcript not found or empty for video '{video_id}'.")
            return

        v_name = video.filename or video.id
        print(f"Running highlight detection on video '{v_name}' (duration: {video.duration}s)...")
        moments = HighlightService.detect_highlights(
            text=transcript.text,
            words=transcript.words if transcript.words else None,
            duration=video.duration,
        )

        if not moments:
            print("No highlight moments were detected by the model.")
            return

        print(f"Detected {len(moments)} highlight moments. Saving real clips to DB...")
        for moment in moments:
            clip = Clip(
                id=str(uuid.uuid4()),
                video_id=video_id,
                title=moment.title,
                start_time=moment.start_time,
                end_time=moment.end_time,
                status="DRAFT",
                edit_spec={
                    "rationale": moment.reason,
                    "score": moment.score,
                    "target_aspect_ratio": "9:16",
                },
            )
            db.add(clip)
        db.commit()
        print(f"Successfully created {len(moments)} real clips for video '{video_id}'!")
    finally:
        db.close()


if __name__ == "__main__":
    target_id = sys.argv[1] if len(sys.argv) > 1 else None
    run_detection(target_id)
