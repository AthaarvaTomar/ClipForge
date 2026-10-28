# Implementation Plan — ClipForge AI Backend

## Phase 1: Core Backend MVP

- [x] **A1 Scaffold**: folders, requirements.txt, config.py, .env.example, docker-compose.yml (Redis), /health. Done when: uvicorn app.main:app runs and /health returns ok.
- [x] **A2 DB**: models (videos, transcripts, clips, jobs), session, Alembic migration. Done when: tables exist, insert/read works.
- [x] **A3 Upload + ffprobe**: POST/GET/DELETE /api/videos, streamed upload, validation, orientation detection. Done when: sample file returns correct duration, resolution, orientation.
- [x] **A4 Celery + jobs**: worker, job progress helper, GET /api/jobs/{id}. Done when: dummy task goes 0 to 100 in the API.
- [x] **A5 Transcription**: wav extraction, faster-whisper with word timestamps, task, transcript endpoints. Done when: transcript with words is saved and returned.
- [x] **A6 Highlights**: Gemini + Ollama fallback, JSON validation, draft clips. Done when: test transcript yields 3+ valid draft clips.
- [x] **A7 EditSpec + clips CRUD**: Pydantic validation, POST/PATCH/GET /api/clips. Done when: invalid specs return 422 with clear messages.
- [x] **A8 FFmpeg builder**: cuts, reframe (crop / blur-bg, both directions), grade presets/custom/LUT. Done when: tests pass for 16:9 to 9:16, 9:16 to 16:9, same-aspect.
- [x] **A9 Transitions**: chained xfade + acrossfade, cumulative offsets, no-audio sources handled. Done when: 3-segment render has smooth transitions, A/V in sync.
- [x] **A10 ASS builder**: title + captions, 5 animations, timestamp remap after cuts. Done when: .ass plays correctly in VLC/ffplay.
- [x] **A11 Render**: ffmpeg runner with progress, cleanup on failure, render/download/preview-frame endpoints. Done when: upload to playable mp4 works end to end.

- [x] **A12 Presets**: JSON files + GET /api/presets. Done when: endpoint lists grades, transitions, animations, fonts.
- [x] **A13 Hardening**: error format, optional API key, CORS, logging, render concurrency limit, timeouts. Done when: killing ffmpeg mid-render marks job failed with a message.

- [x] **A14 Tests**: builder, ass_builder, EditSpec, one 5 s integration test. Done when: pytest is green.
- [x] **A15 README**: setup, run commands (API + worker), curl examples. Done when: a fresh machine can follow it.

## Phase 3: Timeline Core (Backend)

- [x] **T1 Timeline schema**: Pydantic models Timeline (id, video_id, version, tracks), Track (type: video, audio, overlay, caption), Item (source ref, src_in, src_out, start, effects, volume, grade, transition). Validate: in < out, within source duration, no overlap on one track. Done when: invalid timelines return 422 with clear messages and a sample timeline round-trips through JSON.
- [x] **T2 DB**: tables timelines, timeline_ops (seq, group_id, op, inverse_op, actor user|agent, created_at), timeline_versions (snapshot every N ops). Alembic migration. Done when: tables exist and insert/read works.
- [x] **T3 Operation engine**: pure function apply(timeline, op) -> (new_timeline, inverse_op). Ops: add_track, remove_track, add_item, remove_item, split, trim, move, ripple_delete, set_volume, set_grade, set_transition, add_caption, update_caption. Done when: unit tests cover every op and applying the inverse restores the original timeline exactly.
- [x] **T4 Op log, undo/redo, groups**: ops applied together share a group_id so an agent action is one undo step. Redo stack. Optimistic concurrency with a version field (409 on mismatch). Done when: apply, undo and redo work through the engine and the log matches the state.
- [x] **T5 Timeline API**: POST /api/timelines (create from video), GET /api/timelines/{id}, POST /api/timelines/{id}/ops (batch), POST .../undo, POST .../redo, GET .../history, POST .../restore/{version}. Done when: a curl walkthrough covers create, edit, undo, redo and restore.
- [x] **T6 Performance**: benchmark script. Done when: 500 ops apply in under 1 s in the engine and under 2 s through one batch API call, and other requests stay responsive meanwhile.
- [x] **T7 Clips to timelines**: convert existing draft clips and EditSpec into timelines. Done when: every draft clip opens as a valid timeline.

## Phase 4: Render from the Timeline

- [x] **R1 Proxies and UI assets**: Celery task after upload that creates a 360p proxy, thumbnail strip and waveform peaks JSON. Done when: endpoints return the proxy URL, thumbnails and waveform for a video.
- [x] **R2 Timeline-to-FFmpeg compiler**: multi-track video and overlay compositing, audio mix, reusing the reframe, grade, transition and ASS caption code (A8–A10). Done when: golden tests pass for single track, two-track overlay and captions.
- [x] **R3 Render task**: render a pinned timeline version, with progress and cancel. Done when: a rendered file matches the timeline and plays end to end.
- [x] **R4 Preview frame**: GET /api/timelines/{id}/frame?t= renders a frame from the timeline, not the source file. Done when: changing a grade changes the returned frame.

## Phase 5: Footage Indexing

- [x] **I1 Scenes**: PySceneDetect scene boundaries saved per video. Done when: a test video returns correct scene cuts.
- [x] **I2 Silence and fillers**: FFmpeg silencedetect plus filler words ("um", "uh") from the transcript. Done when: silences and fillers return as time ranges.
- [x] **I3 Repeated takes**: fuzzy-match adjacent transcript sentences (rapidfuzz), group near-duplicates and mark the best take. Done when: a recording with 3 takes yields one group with a chosen take.
- [x] **I4 Visual understanding**: sample one frame per scene, then Gemini vision (Ollama LLaVA fallback) returns a caption and tags. Done when: each scene has a description.
- [x] **I5 Speaker diarization**: WhisperX or pyannote (optional, skip for demo).
- [x] **I6 Index orchestrator**: Celery pipeline (transcribe, scenes, silences, takes, visuals) with per-stage progress, chunked for long files. Done when: GET /api/videos/{id}/index returns everything.
- [x] **I7 Chapters, hook, highlights**: upgrade A6 to use the full index. Done when: output includes chapters, a hook candidate and ranked highlights.

## Phase 6: AI Edit Planner

- [x] **P1 Tool schema**: generate Gemini function-calling declarations from the T3 op models. Done when: the model can only emit valid op shapes.
- [x] **P2 Context builder**: compact index summary and current timeline summary within a token budget. Done when: a 3-hour index fits in one request.
- [x] **P3 Plan endpoint**: POST /api/timelines/{id}/plan {prompt} runs as a job and returns {rationale, ops[]}. Done when: "remove all silences" returns valid ops.
- [x] **P4 Validate and repair**: apply ops to a copy, reject invalid ones, retry once with error feedback. Done when: bad plans are repaired or rejected with clear message.
- [x] **P5 Apply plan**: POST .../plan/{plan_id}/apply applies all ops as one undo group with actor agent. Done when: one undo reverts the whole agent action.
- [x] **P6 Demo prompts**: "tighten first 15s", "remove repeated takes", "add B-roll", "make 3 Shorts". Done when: each prompt works on the sample recording.
- [x] **P7 Live events**: WebSocket /ws/timelines/{id} pushing op-applied events and job progress. Done when: a second browser tab sees edits live.

## Phase 7: Editor UI (React, match mockup)

- [x] **E1 Routing and layout**: React Router with Projects, Project, Editor and Shorts pages. Done when: all pages navigate and render.
- [x] **E2 Timeline store**: Zustand store with optimistic ops reconciled against server version, undo/redo. Done when: edits are instant, 409 resyncs cleanly.
- [x] **E3 Timeline component**: tracks, ruler, zoom, playhead, drag, trim, split with snapping, thumbnails and waveforms. Done when: long timelines scroll smoothly.
- [x] **E4 Preview player**: plays proxy by sequencing timeline items with client-side captions. Done when: playback follows timeline cuts.
- [x] **E5 Inspector**: edit selected item grade, transition, caption style from /api/presets. Done when: changes send ops and show in preview.
- [x] **E6 Agent panel**: prompt box, plan preview, Apply and Discard, highlight changed items. Done when: demo prompt visibly changes timeline.
- [x] **E7 History panel**: versions, restore, undo groups labelled user or agent. Done when: restoring works and can be undone.
- [x] **E8 Export dialog**: render job with progress and download. Done when: export plays in browser.
- [x] **E9 Shorts view**: list generated Shorts timelines with preview and export. Done when: "make 3 Shorts" produces three openable timelines.

## Phase 8: B-roll and Audio

- [x] **M1 Asset library**: upload images/video, plus Pexels/Pixabay search with attribution. Done when: keyword search returns downloadable clips.
- [x] **M2 Overlay compositing**: B-roll/image on overlay track with position, scale, fades. Done when: render shows overlay at right time.
- [x] **M3 Planner B-roll**: pick keywords from transcript, insert overlay ops. Done when: "add B-roll" fills chosen segments.
- [x] **M4 Audio layers**: loudness normalisation, denoise, music ducking under speech. Done when: music dips while speech plays.

## Phase 9: Scale, Measure, Demo

- [x] **S1 Storage abstraction**: local disk by default, MinIO optional. Done when: switching by env var works.
- [x] **S2 Resumable upload**: tus protocol. Done when: interrupted upload resumes.
- [x] **S3 Worker scaling**: separate Celery queues, docker compose scale. Done when: two workers render in parallel.
- [x] **S4 Metrics**: timing table, /api/metrics for wait/render time, benchmark script. Done when: README lists benchmark numbers.
- [x] **S5 Demo run**: rehearse demo script and fix blockers. Done when: full demo runs without manual fixes.
