# AGENTS.md — ClipForge AI Backend

Root rules for the AI coding agent (Gemini in Antigravity). Read this first every session.

## Project
ClipForge AI turns long videos into short, captioned, vertical clips. Upload → transcribe → AI finds moments → user reviews → render clips (9:16 + burned-in captions).
Roadmap: `implementation_plan.md`. Current work: `task.md`. Review: `audit.md`.

## Working Rules
1. Work ONLY on the checkbox(es) listed in `task.md`. Do not start other items.
2. Before coding, state a 3-5 line plan. After coding, run lint + typecheck + tests and report results.
3. Prefer small diffs. No drive-by refactors. No new dependency without asking or necessity for the task.
4. When finishing a task: tick it in `implementation_plan.md`, clear `task.md`, note anything odd in `audit.md`.
5. If a requirement is ambiguous, ask one question instead of guessing.

## Stack
- **Backend:** Python 3.11+ / FastAPI, Uvicorn, Pydantic v2
- **Worker & Queue:** Celery + Redis
- **Database:** SQLAlchemy 2.x + Alembic (SQLite in dev, PostgreSQL in prod)
- **AI:** Transcription = faster-whisper with word timestamps. Moment detection = Gemini API with Ollama fallback
- **Video:** FFmpeg / ffprobe, ASS subtitle generation

## Commands
```bash
# Environment & Running
uvicorn app.main:app --reload --port 8000
celery -A app.tasks.celery_app worker --loglevel=info

# Testing & Quality
pytest
ruff check .
mypy app
```

## Code Style
- Python strict types, PEP 8, Pydantic models for validation.
- Endpoints return standard status and error shapes.
- Jobs are idempotent and report progress percentage.

## Definition of Done
Endpoint/service works end-to-end locally; tests pass; no console/unhandled errors; task checkbox ticked.
