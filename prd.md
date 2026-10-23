# PRD — ClipForge AI

## 1. Summary
ClipForge AI is a web app that repurposes long-form video (podcasts, interviews, talks) into short, shareable vertical clips with captions, using AI to find the best moments.

## 2. Problem
Creators spend hours scrubbing long videos to find clip-worthy moments, then more hours cutting, reframing, and captioning them.

## 3. Target Users
- Podcasters / interviewers
- YouTubers and educators
- Social media managers

## 4. Goals
- Upload a video and get 3-8 suggested clips in under ~10 minutes for a 30-min video.
- Let the user review, trim, and edit captions before export.
- Export 9:16 MP4 with burned-in captions.
- Serve as a strong portfolio demo (clear UI, real pipeline).

## 5. MVP Features (in scope)
1. **Auth** — sign up / sign in (Clerk).
2. **Upload** — direct-to-storage upload, MP4/MOV/WebM, max 1 GB, max 60 min. Progress bar.
3. **Processing pipeline** — extract audio → transcribe (word timestamps) → detect moments → store. Live status per stage.
4. **Transcript view** — searchable, click a word to seek the video.
5. **Moment suggestions** — each has start/end, title, score (0-100), reason, hook text.
6. **Clip editor** — adjust start/end on a timeline, edit title, edit caption text, pick caption style (3 presets).
7. **Render** — vertical 9:16 (center crop; optional manual crop x-offset), burned-in captions, MP4 output.
8. **Clip library** — project page with clip cards (preview, status, download).
9. **Delete project** — removes DB rows and storage objects.

## 6. Out of Scope (strictly NOT in MVP)
- Auto-posting to social platforms
- Face tracking / speaker-aware auto-reframe
- Multi-user teams, comments, roles
- Payments / subscriptions
- Mobile apps
- Music, B-roll, stock footage, emojis/animations in captions
- Video import by URL (YouTube etc.)
- Languages other than English
- Full timeline video editor (only trim start/end)

## 7. User Flow
1. Sign in → Dashboard (project list).
2. "New project" → drop video → upload → project page.
3. Status stepper: Uploaded → Transcribing → Analyzing → Ready.
4. Review suggested clips → open editor → tweak → "Render".
5. Rendered clip appears in library → preview / download.

## 8. Functional Requirements
| ID | Requirement |
|----|-------------|
| FR-1 | User can only access own projects and clips. |
| FR-2 | Upload uses presigned multipart/PUT URL; server records `Project` before upload starts. |
| FR-3 | Pipeline runs in background worker; UI polls (or SSE) status every 3s. |
| FR-4 | Failed stage shows error and a "Retry" button that resumes from that stage. |
| FR-5 | Transcript stores word-level `start`, `end`, `text`. |
| FR-6 | Moment detection returns validated JSON; invalid output triggers 1 retry then fails stage. |
| FR-7 | Clip length between 15 and 90 seconds; enforced in editor and server. |
| FR-8 | Render output is H.264/AAC MP4, 1080x1920, 30fps. |
| FR-9 | Captions are word-synced (active word highlighted) in at least one preset. |
| FR-10 | Deleting a project deletes all stored files. |

## 9. Non-Functional Requirements
- **Performance:** transcription+analysis of 30-min video < 10 min; render of 60s clip < 90s.
- **Reliability:** jobs retry 3x with backoff; idempotent.
- **Security:** see AGENTS.md. Signed URLs for all media.
- **Accessibility:** keyboard navigable editor, captions readable (contrast).
- **Cost control:** per-user daily cap (e.g. 3 projects/day, 60 min each) in MVP.

## 10. Success Metrics
- Upload → first suggested clip < 10 min (p50).
- >= 60% of suggested clips kept by user in manual testing.
- Zero cross-user data access in tests.

## 11. Risks
| Risk | Mitigation |
|------|-----------|
| FFmpeg heavy on hosting | Run worker on a VM/container (Railway/Fly), not serverless |
| LLM returns bad timestamps | Snap to transcript word boundaries; validate |
| Large uploads fail | Multipart upload with resume |
| AI cost | Truncate/chunk transcripts; daily caps |

## 12. Milestones
See `implementation_plan.md`.
