# Architecture — ClipForge AI Platform

## High-Level System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Client Applications                      │
│     React 19 Editor Studio (Vite) / REST API Clients        │
└──────────────┬──────────────────────────────▲───────────────┘
               │ HTTP / JSON                  │ Proxies & Previews
               ▼                              │
┌─────────────────────────────────────────────┴───────────────┐
│               FastAPI Application Layer                     │
│                                                             │
│   • Video & Asset Management (/api/videos)                  │
│   • Multi-Track Timeline Engine & Ops (/api/timelines)      │
│   • Transcription & Highlight Endpoints                     │
│   • Background Job Telemetry & Cancellation (/api/jobs)     │
└───────┬──────────────────────┬──────────────────────┬───────┘
        │                      │                      │
        ▼                      ▼                      ▼
┌──────────────┐       ┌──────────────┐       ┌──────────────┐
│  Relational  │       │ Redis Broker │       │ File Storage │
│   Database   │       │   & Queue    │       │ (Local/Cloud)│
│ (PostgreSQL/ │       │              │       │              │
│   SQLite)    │       └───────┬──────┘       └──────────────┘
└──────────────┘               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                   Distributed Celery Workers                │
│                                                             │
│   • faster-whisper (word timestamp transcription)           │
│   • Gemini API / Local Ollama (viral highlight detection)   │
│   • Asset Task (360p proxies, thumbnail strips, waveform)   │
│   • Timeline Compiler (multi-track FFmpeg filtergraph)      │
│   • Render Task (pinned version render with cancel check)   │
└─────────────────────────────────────────────────────────────┘
```

---

## Data Model (SQLAlchemy 2.x + Alembic)

1. **Videos (`videos`)**:
   - `id`: String UUID primary key
   - `filename`, `file_path`, `duration`, `width`, `height`, `fps`
   - `orientation`: enum (`landscape`, `portrait`, `square`)
   - `status`: enum (`uploading`, `ready`, `failed`)
   - Cascade delete relationship to transcripts, clips, and timelines.

2. **Transcripts (`transcripts`)**:
   - `id`: String UUID primary key
   - `video_id`: Foreign key to `videos.id`
   - `language`: Detected language code (e.g. `en`)
   - `text`: Complete transcription text
   - `words`: JSON array of word objects `[{word, start, end, probability}]`

3. **Timelines (`timelines`)**:
   - `id`: String UUID primary key
   - `video_id`: Foreign key to `videos.id`
   - `version`: Monotonically increasing version integer (optimistic concurrency)
   - `current_seq`: Integer tracking sequence of the last applied operation
   - `data`: Complete Pydantic `Timeline` schema JSON containing tracks and items
   - Cascade relationships to `timeline_ops` and `timeline_versions`.

4. **Timeline Operations Log (`timeline_ops`)**:
   - `id`: String UUID primary key
   - `timeline_id`: Foreign key to `timelines.id`
   - `seq`: Strict sequential ordering integer
   - `group_id`: Action grouping UUID (allows multi-op agent actions to undo in one step)
   - `actor`: String (`user` or `agent`)
   - `op`: JSON representation of the applied forward operation
   - `inverse_op`: JSON representation of the exact mathematical inverse operation

5. **Timeline Snapshots (`timeline_versions`)**:
   - `id`: String UUID primary key
   - `timeline_id`: Foreign key to `timelines.id`
   - `version`: Version integer corresponding to state at snapshot
   - `snapshot`: Full timeline schema JSON state saved every N operations

6. **Clips (`clips`)**:
   - `id`, `video_id`, `timeline_id`, `title`, `start_time`, `end_time`
   - `edit_spec`: Legacy EditSpec configuration JSON
   - `status`: enum (`DRAFT`, `QUEUED`, `RENDERING`, `DONE`, `FAILED`)
   - `output_path`: Path to rendered clip

7. **Jobs (`jobs`)**:
   - `id`: String UUID primary key
   - `job_type`: String identifier (`TRANSCRIPTION`, `HIGHLIGHTS`, `RENDER`, `TIMELINE_RENDER`, `ASSET_GENERATION`)
   - `status`: enum (`PENDING`, `PROCESSING`, `COMPLETED`, `FAILED`, `CANCELLED`)
   - `progress`: Integer percentage (0–100)
   - `error_message`, `result_data`: Diagnostic payloads

---

## REST API Specification

### Videos & Assets
| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/videos` | Chunked upload with file validation and ffprobe telemetry |
| `GET` | `/api/videos` | List videos with pagination |
| `GET` | `/api/videos/{id}` | Video metadata details |
| `DELETE` | `/api/videos/{id}` | Delete video, database records, and generated asset files |
| `POST` | `/api/videos/{id}/assets` | Trigger proxy, thumbnail strip, and waveform generation |
| `GET` | `/api/videos/{id}/assets` | Query status and URLs for all generated video assets |
| `GET` | `/api/videos/{id}/proxy` | Stream 360p lightweight proxy video |
| `GET` | `/api/videos/{id}/waveform` | Retrieve 100-slice audio peak amplitudes JSON |
| `GET` | `/api/videos/{id}/thumbnails/strip` | Fetch horizontal timeline thumbnail strip image |
| `GET` | `/api/videos/{id}/thumbnails/{filename}` | Fetch individual thumbnail image |

### Timelines & Multi-Track Editing
| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/timelines` | Create a new timeline initialized from a source video |
| `GET` | `/api/timelines/{id}` | Retrieve current timeline schema and track state |
| `POST` | `/api/timelines/{id}/ops` | Batch-apply atomic operations with optimistic concurrency |
| `POST` | `/api/timelines/{id}/undo` | Undo the previous user or agent operation group |
| `POST` | `/api/timelines/{id}/redo` | Redo the most recently undone operation group |
| `GET` | `/api/timelines/{id}/history` | Retrieve chronological operation audit log |
| `POST` | `/api/timelines/{id}/restore/{version}` | Restore timeline to a pinned historical snapshot |
| `POST` | `/api/timelines/{id}/render` | Trigger background FFmpeg render (active or pinned version) |
| `POST` | `/api/timelines/{id}/cancel` | Cancel an in-flight timeline render job |
| `GET` | `/api/timelines/{id}/download` | Stream and download rendered output video |
| `GET` | `/api/timelines/{id}/frame?t={sec}` | Extract single preview frame directly from live filtergraph |

### AI, Clips & Jobs
| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/transcripts/{video_id}` | Enqueue faster-whisper word-level transcription task |
| `GET` | `/api/transcripts/{video_id}` | Retrieve word-level timestamps and transcription text |
| `POST` | `/api/highlights/{video_id}` | Extract viral candidate clips using Gemini or Ollama |
| `GET` | `/api/clips/{id}/timeline` | Convert or open a draft clip as an editable multi-track timeline |
| `GET` | `/api/jobs/{id}` | Check job status, progress percentage, and result data |
| `POST` | `/api/jobs/{id}/cancel` | Cooperatively cancel an active background job |
| `GET` | `/api/presets` | List color grades, transitions, font families, and animations |

---

## Pipeline Execution Details

1. **Upload & Probe**: Streamed chunk upload saves to disk. `ffprobe` analyzes container metadata, video/audio stream properties, and orientation matrix.
2. **Proxy & Waveform Generation**: `AssetService` extracts a 360p MP4 proxy with scaled bitrates, an audio PCM stream downsampled to compute RMS peaks, and video frames tiled into a sprite strip.
3. **Transcription**: Extracted mono 16 kHz WAV is fed to `faster-whisper`. Words with millisecond boundaries are indexed into the database.
4. **AI Moment Detection**: High-retention segments are scored via Gemini (with Ollama fallback), assessing narrative cohesion, strong hooks, and virality potential.
5. **Timeline Compilation**:
   - Multi-track item timeline is assembled into a single complex FFmpeg filtergraph.
   - Video track cuts are reframed (9:16 portrait with center crop or blur-background), graded, and stitched with `xfade`.
   - Audio tracks are synchronized with `adelay` and combined with `amix`.
   - Overlays are blended with `between(t,...)` time expressions.
   - Word timings are formatted into an ASS script and burned in via `ass` filtergraph node.
6. **Background Rendering & Cancellation**: Workers monitor stdout for time-slice progress updates (`out_time_us`), reporting percentage completion (10–95%) back to Redis/database. Cooperative cancellation checks immediately terminate FFmpeg subprocesses upon request.
