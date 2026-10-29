# ClipForge AI

**AI-powered video editing platform for transforming long-form videos into engaging, captioned vertical shorts.**

ClipForge AI helps creators repurpose long videos into short-form content for YouTube Shorts, Instagram Reels, and TikTok. It combines AI-powered highlight detection, automatic transcription, and a multi-track video editing engine in a unified editing workspace.

## Key Features

- **Video Processing:** Chunked uploads, format validation, video proxies, thumbnail strips, and audio waveform generation.
- **AI Highlight Detection:** Uses Google Gemini, with a local Ollama fallback, to identify promising clips and rank them by potential engagement.
- **Automatic Transcription:** Word-level transcripts with timestamps powered by Faster-Whisper.
- **Multi-Track Timeline Editor:** Supports trimming, splitting, moving clips, transitions, volume controls, captions, and grouped undo/redo.
- **Vertical Video Conversion:** Reframes horizontal videos into 9:16 format using smart cropping or blurred backgrounds.
- **Animated Captions:** Generates word-highlighted subtitles and embeds them into exported videos.
- **Background Rendering:** Uses asynchronous jobs with progress tracking, cancellation, and export management.
- **Timeline Previews:** Generates individual frame previews without rendering the entire video.

## Technology Stack

| Component | Technologies |
|---|---|
| Frontend | React 19, TypeScript, Vite |
| Backend | Python, FastAPI |
| AI & Transcription | Google Gemini, Ollama, Faster-Whisper |
| Video Processing | FFmpeg, FFprobe |
| Background Jobs | Celery, Redis |
| Database | SQLAlchemy, relational database |
| Validation & Quality | Pydantic, Pytest, Ruff, Mypy |

## Architecture

ClipForge AI uses a decoupled frontend and backend architecture. The React studio communicates with the FastAPI backend, while Celery workers handle transcription, AI analysis, asset generation, and video rendering asynchronously. Redis manages background job queues, and the timeline engine maintains versioned editing state with reversible operations.

## Project Status

Core application functionality has been implemented. Testing and validation are the remaining focus before the project is considered fully verified.

## Proprietary License

**© 2026 ClipForge AI. All rights reserved.**

This software is proprietary and remains under the exclusive ownership and license of its copyright holder. No permission is granted to copy, modify, redistribute, sublicense, publish, or commercially use this software without prior written authorization from the copyright holder.

This project is not released under an open-source license. All rights are reserved except where expressly authorized in writing.
