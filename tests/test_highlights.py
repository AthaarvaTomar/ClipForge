from collections.abc import Generator
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.core.database import SessionLocal
from app.main import app
from app.models.transcript import Transcript
from app.models.video import Video
from app.schemas.highlight import (
    HighlightMoment,
    extract_json_from_llm_text,
    parse_and_validate_highlights_json,
)
from app.services.highlight_service import HighlightService
from app.tasks.celery_app import celery_app


@pytest.fixture(autouse=True)
def configure_celery_eager() -> Generator[None, None, None]:
    original_eager = celery_app.conf.task_always_eager
    original_backend = celery_app.conf.result_backend
    celery_app.conf.task_always_eager = True
    celery_app.conf.result_backend = "cache+memory://"
    yield
    celery_app.conf.task_always_eager = original_eager
    celery_app.conf.result_backend = original_backend


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


SAMPLE_TRANSCRIPT_TEXT = (
    "Welcome back to the podcast. Today I want to reveal the secret to building wealth. "
    "Most people believe you need a high salary to become financially free, but that is wrong. "
    "The real secret is asymmetric risk: finding opportunities where your downside is capped at "
    "zero, but your upside is unlimited. "
    "For example, when I started my first digital business at twenty-two, I only invested $50. "
    "Two years later, that fifty-dollar website generated over one million dollars in profit. "
    "The lesson is never trade your time directly for money; build scalable assets that compound. "
    "If you want to master this mindset, remember these three rules. "
    "First, eliminate low-value recurring expenses. "
    "Second, learn one high-income skill like copywriting or programming. "
    "Third, reinvest eighty percent of your profits into cash-flowing assets."
)

SAMPLE_WORDS: list[dict[str, Any]] = [
    {"word": "Welcome", "start": 0.0, "end": 0.4, "probability": 0.98},
    {"word": "back", "start": 0.45, "end": 0.7, "probability": 0.99},
    {"word": "to", "start": 0.75, "end": 0.9, "probability": 0.99},
    {"word": "the", "start": 0.95, "end": 1.1, "probability": 0.99},
    {"word": "podcast.", "start": 1.15, "end": 1.6, "probability": 0.97},
    {"word": "Today", "start": 1.8, "end": 2.1, "probability": 0.98},
    {"word": "I", "start": 2.15, "end": 2.3, "probability": 0.99},
    {"word": "want", "start": 2.35, "end": 2.5, "probability": 0.99},
    {"word": "to", "start": 2.55, "end": 2.7, "probability": 0.99},
    {"word": "reveal", "start": 2.75, "end": 3.1, "probability": 0.98},
    {"word": "the", "start": 3.15, "end": 3.3, "probability": 0.99},
    {"word": "single", "start": 3.35, "end": 3.7, "probability": 0.99},
    {"word": "greatest", "start": 3.75, "end": 4.1, "probability": 0.99},
    {"word": "secret", "start": 4.15, "end": 4.5, "probability": 0.99},
    {"word": "to", "start": 4.55, "end": 4.7, "probability": 0.99},
    {"word": "building", "start": 4.75, "end": 5.1, "probability": 0.99},
    {"word": "wealth.", "start": 5.15, "end": 5.6, "probability": 0.99},
    {"word": "Most", "start": 5.8, "end": 6.1, "probability": 0.98},
    {"word": "people", "start": 6.15, "end": 6.4, "probability": 0.99},
    {"word": "believe", "start": 6.45, "end": 6.8, "probability": 0.99},
    {"word": "you", "start": 6.85, "end": 7.0, "probability": 0.99},
    {"word": "need", "start": 7.05, "end": 7.2, "probability": 0.99},
    {"word": "a", "start": 7.25, "end": 7.35, "probability": 0.99},
    {"word": "high-paying", "start": 7.4, "end": 7.9, "probability": 0.98},
    {"word": "salary", "start": 7.95, "end": 8.4, "probability": 0.99},
    {"word": "to", "start": 8.45, "end": 8.6, "probability": 0.99},
    {"word": "become", "start": 8.65, "end": 9.0, "probability": 0.99},
    {"word": "financially", "start": 9.05, "end": 9.6, "probability": 0.99},
    {"word": "free,", "start": 9.65, "end": 10.0, "probability": 0.99},
    {"word": "but", "start": 10.1, "end": 10.3, "probability": 0.99},
    {"word": "that", "start": 10.35, "end": 10.5, "probability": 0.99},
    {"word": "is", "start": 10.55, "end": 10.7, "probability": 0.99},
    {"word": "completely", "start": 10.75, "end": 11.2, "probability": 0.99},
    {"word": "wrong.", "start": 11.25, "end": 11.7, "probability": 0.99},
    {"word": "The", "start": 12.0, "end": 12.2, "probability": 0.99},
    {"word": "real", "start": 12.25, "end": 12.5, "probability": 0.99},
    {"word": "secret", "start": 12.55, "end": 12.9, "probability": 0.99},
    {"word": "is", "start": 12.95, "end": 13.1, "probability": 0.99},
    {"word": "asymmetric", "start": 13.15, "end": 13.7, "probability": 0.98},
    {"word": "risk:", "start": 13.75, "end": 14.1, "probability": 0.99},
    {"word": "finding", "start": 14.2, "end": 14.5, "probability": 0.99},
    {"word": "opportunities", "start": 14.55, "end": 15.2, "probability": 0.99},
    {"word": "where", "start": 15.25, "end": 15.4, "probability": 0.99},
    {"word": "your", "start": 15.45, "end": 15.6, "probability": 0.99},
    {"word": "downside", "start": 15.65, "end": 16.1, "probability": 0.99},
    {"word": "is", "start": 16.15, "end": 16.3, "probability": 0.99},
    {"word": "capped", "start": 16.35, "end": 16.7, "probability": 0.99},
    {"word": "at", "start": 16.75, "end": 16.9, "probability": 0.99},
    {"word": "zero.", "start": 16.95, "end": 17.4, "probability": 0.99},
]


def test_extract_and_validate_highlights_json() -> None:
    # 1. Valid with markdown fences
    markdown_output = """```json
    {
      "highlights": [
        {
          "title": "The Secret to Wealth",
          "start_time": 1.8,
          "end_time": 11.7,
          "hook": "Today I want to reveal the greatest secret",
          "reason": "Strong curiosity hook",
          "score": 9.5
        },
        {
          "title": "Asymmetric Risk Explained",
          "start_time": 12.0,
          "end_time": 35.0,
          "hook": "The real secret is asymmetric risk",
          "reason": "Mindset shift with high rewatch value",
          "score": 9.0
        },
        {
          "title": "Turn $50 into Millions",
          "start_time": 36.0,
          "end_time": 58.0,
          "hook": "I only invested fifty dollars",
          "reason": "Concrete proof and inspirational case study",
          "score": 8.8
        }
      ]
    }
    ```"""
    moments = parse_and_validate_highlights_json(markdown_output)
    assert len(moments) == 3
    assert moments[0].title == "The Secret to Wealth"
    assert moments[0].start_time == 1.8
    assert moments[0].end_time == 11.7
    assert moments[0].score == 9.5

    # 2. Extract json cleans arbitrary text before/after
    noisy_output = (
        "Here are your clips:\n"
        '{"highlights": [{"title": "A", "start_time": 0.0, "end_time": 15.0}]}\n'
        "Enjoy!"
    )
    expected_clean = '{"highlights": [{"title": "A", "start_time": 0.0, "end_time": 15.0}]}'
    assert extract_json_from_llm_text(noisy_output) == expected_clean

    # 3. Invalid timestamps raise error
    with pytest.raises(ValueError, match="strictly greater"):
        HighlightMoment(title="Invalid", start_time=10.0, end_time=5.0)


def test_highlight_service_gemini_success() -> None:
    fake_gemini_resp = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "text": """{
                                "highlights": [
                                    {
                                        "title": "Clip 1",
                                        "start_time": 0.0,
                                        "end_time": 20.0,
                                        "hook": "Hook 1",
                                        "reason": "R1",
                                        "score": 9.0
                                    },
                                    {
                                        "title": "Clip 2",
                                        "start_time": 22.0,
                                        "end_time": 45.0,
                                        "hook": "Hook 2",
                                        "reason": "R2",
                                        "score": 8.5
                                    },
                                    {
                                        "title": "Clip 3",
                                        "start_time": 46.0,
                                        "end_time": 60.0,
                                        "hook": "Hook 3",
                                        "reason": "R3",
                                        "score": 8.0
                                    }
                                ]
                            }"""
                        }
                    ]
                }
            }
        ]
    }

    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.json.return_value = fake_gemini_resp
    mock_response.raise_for_status = MagicMock()
    mock_client.post.return_value = mock_response

    with patch.object(settings, "GEMINI_API_KEY", "test-key"):
        moments = HighlightService.detect_highlights(
            text="Some transcript text",
            client=mock_client,
        )

    assert len(moments) == 3
    assert moments[0].title == "Clip 1"
    assert moments[1].title == "Clip 2"
    assert moments[2].title == "Clip 3"


def test_highlight_service_fallback_to_ollama() -> None:
    fake_ollama_resp = {
        "response": """{
            "highlights": [
                {
                    "title": "Ollama Clip 1",
                    "start_time": 0.0,
                    "end_time": 20.0,
                    "hook": "Hook 1",
                    "reason": "R1",
                    "score": 9.0
                },
                {
                    "title": "Ollama Clip 2",
                    "start_time": 21.0,
                    "end_time": 42.0,
                    "hook": "Hook 2",
                    "reason": "R2",
                    "score": 8.7
                },
                {
                    "title": "Ollama Clip 3",
                    "start_time": 44.0,
                    "end_time": 60.0,
                    "hook": "Hook 3",
                    "reason": "R3",
                    "score": 8.2
                }
            ]
        }"""
    }

    mock_client = MagicMock()

    # First call (Gemini) raises an error, second call (Ollama) succeeds
    gemini_resp = MagicMock()
    gemini_resp.raise_for_status.side_effect = Exception("Gemini 503 Service Unavailable")

    ollama_resp = MagicMock()
    ollama_resp.json.return_value = fake_ollama_resp
    ollama_resp.raise_for_status = MagicMock()

    mock_client.post.side_effect = [gemini_resp, ollama_resp]

    with patch.object(settings, "GEMINI_API_KEY", "test-key"):
        moments = HighlightService.detect_highlights(
            text="Some transcript text",
            client=mock_client,
        )

    assert len(moments) == 3
    assert moments[0].title == "Ollama Clip 1"
    assert moments[1].title == "Ollama Clip 2"
    assert moments[2].title == "Ollama Clip 3"


def test_detect_highlights_task_and_endpoints(client: TestClient) -> None:
    # 1. Create Video and Transcript in database
    db = SessionLocal()
    video = Video(
        filename="test_podcast.mp4",
        file_path="./data/uploads/test_podcast.mp4",
        duration=120.0,
        width=1920,
        height=1080,
        fps=30.0,
        orientation="landscape",
        status="transcribed",
    )
    db.add(video)
    db.commit()
    db.refresh(video)

    transcript = Transcript(
        video_id=video.id,
        language="en",
        text=SAMPLE_TRANSCRIPT_TEXT,
        words=SAMPLE_WORDS,
    )
    db.add(transcript)
    db.commit()
    db.refresh(transcript)
    video_id = video.id
    db.close()

    mock_moments = [
        HighlightMoment(
            title="The Wealth Secret",
            start_time=1.8,
            end_time=11.7,
            hook="Today I want to reveal the secret",
            reason="Curiosity hook",
            score=9.5,
        ),
        HighlightMoment(
            title="Asymmetric Risk Explained",
            start_time=12.0,
            end_time=35.0,
            hook="The real secret is asymmetric risk",
            reason="High insight density",
            score=9.2,
        ),
        HighlightMoment(
            title="50 Dollars to 1 Million",
            start_time=36.0,
            end_time=58.0,
            hook="I invested only fifty dollars",
            reason="Inspiring case study",
            score=8.9,
        ),
    ]

    with patch.object(HighlightService, "detect_highlights", return_value=mock_moments):
        # 2. Trigger highlight detection via POST /api/highlights/{video_id}
        resp = client.post(f"/api/highlights/{video_id}")
        assert resp.status_code == 202
        job_data = resp.json()
        job_id = job_data["id"]

        # 3. Check job completed
        job_status = client.get(f"/api/jobs/{job_id}")
        assert job_status.status_code == 200
        assert job_status.json()["status"] == "COMPLETED"
        assert job_status.json()["progress"] == 100
        assert job_status.json()["result_data"]["clips_count"] == 3

        # 4. Fetch draft clips via GET /api/highlights/{video_id}
        clips_resp = client.get(f"/api/highlights/{video_id}")
        assert clips_resp.status_code == 200
        clips_data = clips_resp.json()
        assert clips_data["video_id"] == video_id
        assert clips_data["total"] >= 3

        clips = clips_data["clips"]
        assert len(clips) >= 3
        for clip in clips:
            assert clip["status"] == "DRAFT"
            assert clip["start_time"] < clip["end_time"]
            assert clip["title"]
            assert "cuts" in clip["edit_spec"]

    # 5. Verify error cases
    assert client.post("/api/highlights/non-existent-id").status_code == 404
    assert client.get("/api/highlights/non-existent-id").status_code == 404

    # Cleanup DB
    db_clean = SessionLocal()
    vid_to_del = db_clean.get(Video, video_id)
    if vid_to_del:
        db_clean.delete(vid_to_del)
        db_clean.commit()
    db_clean.close()


def test_live_gemini_highlight_detection() -> None:
    """Live verification of Gemini API key, ensuring test transcript yields 3+ valid draft clips."""
    if not settings.GEMINI_API_KEY:
        pytest.skip("GEMINI_API_KEY is not configured")

    moments = HighlightService.detect_highlights(
        text=SAMPLE_TRANSCRIPT_TEXT,
        words=SAMPLE_WORDS,
        duration=120.0,
    )

    assert len(moments) >= 3, f"Expected 3+ highlight moments, got {len(moments)}"
    for moment in moments:
        assert isinstance(moment.title, str) and len(moment.title) > 0
        assert moment.start_time >= 0.0
        assert moment.end_time > moment.start_time
        assert isinstance(moment.score, float)
