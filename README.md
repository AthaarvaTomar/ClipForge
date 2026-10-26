# ClipForge AI

<div align="center">

**Enterprise-grade AI platform that transforms long-form videos into viral, captioned, vertical shorts.**

[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115%2B-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Celery](https://img.shields.io/badge/Celery-5.4%2B-37814A?logo=celery&logoColor=white)](https://docs.celeryq.dev/)
[![Redis](https://img.shields.io/badge/Redis-7.0%2B-DC382D?logo=redis&logoColor=white)](https://redis.io/)
[![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)](https://react.dev/)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.9-3178C6?logo=typescript&logoColor=white)](https://www.typescriptlang.org/)
[![FFmpeg](https://img.shields.io/badge/FFmpeg-Enabled-007808?logo=ffmpeg&logoColor=white)](https://ffmpeg.org/)
[![Tests](https://img.shields.io/badge/Tests-146%20Passed-brightgreen)](tests/)
[![Code Style](https://img.shields.io/badge/Code%20Style-Ruff%20%7C%20Mypy-black)](pyproject.toml)

</div>

---

## Overview

**ClipForge AI** is a video repurposing engine and editing workspace designed to turn hour-long horizontal videos into engaging, high-retention 9:16 vertical clips (YouTube Shorts, Instagram Reels, TikTok). 

It features an asynchronous processing architecture with Celery and Redis, an atomic non-destructive multi-track Timeline Engine, a timeline-to-FFmpeg filtergraph compiler, and an intuitive dark-themed React studio.

---

## Key Features

### 1. Ingestion & Asset Generation
- **Streamed Video Uploads**: Chunked, memory-efficient uploads with strict format validation and orientation detection via `ffprobe`.
- **UI Asset Pipeline**: Automatically renders 360p video proxies, thumbnail mosaic strips, individual timeline frames, and 100-slice audio peak JSON waveforms for instant timeline scrubbing.

### 2. AI Intelligence & Transcription
- **Word-Level Transcription**: Powered by `faster-whisper` for timestamped word transcripts.
- **Viral Moment Detection**: Analyzes transcripts using Google Gemini (with local Ollama fallback) to extract 15–60 second clips ranked by virality score, retention hooks, and reasoning.

### 3. Multi-Track Timeline Engine
- **Non-Destructive Operations**: Functional engine supporting 13 atomic operations (`add_track`, `remove_track`, `add_item`, `remove_item`, `split`, `trim`, `move`, `ripple_delete`, `set_volume`, `set_grade`, `set_transition`, `add_caption`, `update_caption`).
- **Mathematical Inverses**: Every operation produces its exact mathematical inverse, enabling multi-step grouped undo/redo and auditability.
- **Optimistic Concurrency**: Version tracking with HTTP 409 conflict detection and automatic periodic snapshotting (`TIMELINE_SNAPSHOT_INTERVAL`).
- **Sub-Second Performance**: Applies 500 timeline operations in under 0.45s using structural sharing.

### 4. Timeline-to-FFmpeg Compiler & Renderer
- **Multi-Track Compositing**: Sequences video items, handles chained transitions (`xfade` and `acrossfade` with duration compensation), and overlays B-roll with `between(t,...)` precision.
- **Visual Enhancements**: Dynamic 16:9 to 9:16 reframing (smart center crop or blurred background fill) and color grading presets (`warm`, `cool`, `bw`, `vintage`).
- **Animated Subtitles**: Generates ASS subtitle scripts with word-level highlight animations and burns them directly into video exports.
- **Asynchronous Rendering**: Background Celery jobs with real-time progress callbacks (10–95%), cooperative cancellation checks, and automatic asset cleanup.
- **Timeline Frame Preview**: Extracts single JPEG frames at any arbitrary playhead time directly from the visual timeline filtergraph without full rendering.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                       Client Studio                         │
│             (React 19 + TypeScript + Vite)                  │
└──────────────┬──────────────────────────────▲───────────────┘
               │ HTTP API Requests             │ Assets & Previews
               ▼                               │
┌──────────────────────────────────────────────┴──────────────┐
│                    FastAPI Backend                          │
│                                                             │
│   /api/videos      /api/transcripts     /api/timelines      │
│   /api/clips       /api/highlights      /api/jobs           │
└───────┬──────────────────────┬──────────────────────┬───────┘
        │                      │                      │
        ▼                      ▼                      ▼
┌──────────────┐       ┌──────────────┐       ┌──────────────┐
│   Database   │       │ Redis Broker │       │ Disk Storage │
│ (SQLAlchemy) │       │   & Queue    │       │  & Proxies   │
└──────────────┘       └───────┬──────┘       └──────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                   Celery Worker Nodes                       │
│                                                             │
│   • faster-whisper (word timestamps)                        │
│   • Gemini / Ollama (viral highlight ranking)               │
│   • Asset Task (360p proxy, thumbnails, waveform)           │
│   • Timeline Compiler (FFmpeg filtergraph & ASS engine)     │
│   • Render Task (progress reporting & cancellation)         │
└─────────────────────────────────────────────────────────────┘
```

---

## Project Structure

```
clipforge-ai/
├── alembic/                  # Database migration scripts (Alembic)
├── app/
│   ├── api/v1/endpoints/     # REST route controllers (videos, timelines, clips, jobs...)
│   ├── core/                 # DB session engine, logging, security, error handling
│   ├── models/               # SQLAlchemy 2.x relational ORM models
│   ├── schemas/              # Pydantic v2 schemas and validation models
│   ├── services/             # Core business logic:
│   │   ├── asset_service.py      # Proxies, thumbnail strips, audio waveform JSON
│   │   ├── timeline_compiler.py  # Multi-track FFmpeg filtergraph builder
│   │   ├── timeline_engine.py    # Pure functional operation engine & undo/redo
│   │   ├── timeline_service.py   # State persistence, versioning & snapshots
│   │   ├── ffmpeg_builder.py     # Reframing, grading, transitions & ASS subtitles
│   │   ├── highlight_service.py  # Gemini & Ollama moment extraction
│   │   └── transcription_service.py # faster-whisper transcription
│   └── tasks/                # Celery background tasks (transcription, rendering...)
├── frontend/                 # React 19 + TypeScript + Vite frontend
│   ├── src/api/              # Typed API client with XHR progress & error wrappers
│   ├── src/pages/            # Editor studio pages (NewProject, Debug Console...)
│   └── src/index.css         # Dark theme design system & tokens
├── scripts/                  # Performance benchmarks and walkthrough scripts
├── tests/                    # Comprehensive Pytest test suite (146 tests)
├── docker-compose.yml        # Redis container configuration
├── pyproject.toml            # Ruff linter & Mypy strict configuration
└── requirements.txt          # Python production & test dependencies
```

---

## Quickstart Guide

### Prerequisites
- **Python**: 3.11+
- **Node.js**: 20+ and `npm`
- **FFmpeg**: `ffmpeg` and `ffprobe` installed and accessible on your `PATH` (or via `static-ffmpeg`)
- **Docker**: For running Redis (or a local Redis server)

---

### 1. Start Redis
```bash
docker compose up -d
```

### 2. Backend Setup
```bash
# Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .\.venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env

# Run database migrations
alembic upgrade head
```

### 3. Launch Services
Run the API server:
```bash
uvicorn app.main:app --reload --port 8000
```

In a separate terminal, launch the Celery background worker:
```bash
# On Linux/macOS:
celery -A app.tasks.celery_app worker --loglevel=info

# On Windows (gevent or solo execution pool recommended):
celery -A app.tasks.celery_app worker --loglevel=info -P solo
```

### 4. Frontend Setup
```bash
cd frontend
npm install
npm run dev
```

Visit `http://localhost:5173` to access the ClipForge Studio interface, or navigate to `http://localhost:8000/docs` for the interactive Swagger API documentation.

---

## API Reference

A complete, interactive OpenAPI schema is available at `/docs` when the server is running. Key routes include:

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/videos` | Upload video file and extract ffprobe metadata |
| `GET` | `/api/videos/{id}/proxy` | Stream 360p lightweight proxy video |
| `GET` | `/api/videos/{id}/waveform` | Retrieve audio waveform peaks JSON |
| `GET` | `/api/videos/{id}/thumbnails/strip` | Retrieve horizontal thumbnail strip image |
| `POST` | `/api/transcripts/{video_id}` | Enqueue transcription background job |
| `POST` | `/api/highlights/{video_id}` | Detect highlight clips with Gemini/Ollama |
| `POST` | `/api/timelines` | Create a new timeline from video |
| `POST` | `/api/timelines/{id}/ops` | Batch-apply timeline operations with optimistic concurrency |
| `POST` | `/api/timelines/{id}/undo` | Undo the last user or agent action group |
| `POST` | `/api/timelines/{id}/redo` | Redo the previously undone action |
| `POST` | `/api/timelines/{id}/render` | Enqueue background timeline render (supports pinned versions) |
| `POST` | `/api/timelines/{id}/cancel` | Cancel an in-flight rendering job |
| `GET` | `/api/timelines/{id}/download` | Download rendered MP4 clip |
| `GET` | `/api/timelines/{id}/frame?t={sec}` | Extract live timeline preview frame |
| `GET` | `/api/jobs/{id}` | Inspect background job status and progress percentage |

---

## Testing & Quality Assurance

ClipForge enforces strict typing and code style standards:

```bash
# Run complete test suite (146 tests)
pytest

# Fast linting and style check
ruff check .

# Strict typechecking
mypy app tests scripts

# Performance benchmarking
python scripts/benchmark_timeline.py
```

---

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.
