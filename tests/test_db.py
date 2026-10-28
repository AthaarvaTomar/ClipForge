from collections.abc import Generator

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal, engine
from app.models import Clip, Job, Transcript, Video


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def test_tables_exist() -> None:
    inspector = inspect(engine)
    table_names = inspector.get_table_names()
    assert "videos" in table_names
    assert "transcripts" in table_names
    assert "clips" in table_names
    assert "jobs" in table_names


def test_crud_operations(db_session: Session) -> None:
    # 1. Create a Video
    video = Video(
        filename="sample_podcast.mp4",
        file_path="/tmp/sample_podcast.mp4",
        duration=120.5,
        width=1920,
        height=1080,
        fps=30.0,
        orientation="landscape",
        status="uploaded",
    )
    db_session.add(video)
    db_session.commit()
    db_session.refresh(video)

    assert video.id is not None
    assert video.filename == "sample_podcast.mp4"
    assert video.created_at is not None

    # 2. Add Transcript to Video
    words_data = [
        {"word": "Hello", "start": 0.0, "end": 0.5, "probability": 0.98},
        {"word": "world", "start": 0.6, "end": 1.0, "probability": 0.95},
    ]
    transcript = Transcript(
        video_id=video.id,
        language="en",
        text="Hello world",
        words=words_data,
    )
    db_session.add(transcript)
    db_session.commit()
    db_session.refresh(transcript)

    assert transcript.id is not None
    assert transcript.video_id == video.id
    assert isinstance(transcript.words, list)
    assert len(transcript.words) == 2

    # 3. Add Clip to Video
    clip = Clip(
        video_id=video.id,
        title="Epic Intro Hook",
        start_time=0.0,
        end_time=30.0,
        edit_spec={
            "aspect_ratio": "9:16",
            "caption_style": "bold-highlight",
            "cuts": [{"start": 0.0, "end": 30.0}],
        },
        status="DRAFT",
    )
    db_session.add(clip)
    db_session.commit()
    db_session.refresh(clip)

    assert clip.id is not None
    assert clip.title == "Epic Intro Hook"
    assert clip.edit_spec["aspect_ratio"] == "9:16"

    # 4. Add Job linked to Video and Clip
    job = Job(
        job_type="render",
        status="PROCESSING",
        progress=50,
        video_id=video.id,
        clip_id=clip.id,
        result_data={"output_format": "mp4"},
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)

    assert job.id is not None
    assert job.progress == 50
    assert job.status == "PROCESSING"

    # 5. Read back via query
    read_video = db_session.execute(select(Video).where(Video.id == video.id)).scalar_one()
    assert len(read_video.transcripts) == 1
    assert len(read_video.clips) == 1
    assert len(read_video.jobs) == 1
    assert read_video.transcripts[0].text == "Hello world"

    # Cleanup
    db_session.delete(video)
    db_session.commit()

    # Verify cascade delete
    remaining_clips = (
        db_session.execute(select(Clip).where(Clip.video_id == video.id)).scalars().all()
    )
    assert len(remaining_clips) == 0
