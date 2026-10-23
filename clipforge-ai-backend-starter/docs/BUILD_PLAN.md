# Backend-first build plan

## Phase 0 — Project setup
- [ ] Install Node.js LTS.
- [ ] Create a Supabase project.
- [ ] Copy `.env.example` to `.env.local`.
- [ ] Run `npm install`, `npm run dev`, then verify `/api/health`.
- [ ] Apply `supabase/migrations/001_initial_schema.sql`.
- [ ] Create a private Supabase Storage bucket named `source-videos` and a private bucket named `generated-clips`.

## Phase 1 — Secure project CRUD
- [ ] Add Supabase server-side auth/session verification.
- [ ] Implement `POST /api/projects`.
- [ ] Implement `GET /api/projects`.
- [ ] Implement `GET /api/projects/[projectId]`.
- [ ] Add ownership checks and Zod schemas.
- [ ] Add tests for unauthorized access and invalid payloads.

## Phase 2 — Upload pipeline
- [ ] Implement signed upload URL endpoint.
- [ ] Browser uploads directly to private storage.
- [ ] Save original filename, MIME type, size and storage path.
- [ ] Enforce size/type limits and prevent path traversal.

## Phase 3 — AI analysis job
- [ ] Implement job creation endpoint.
- [ ] Add local worker process; do not do lengthy analysis in API request.
- [ ] Send video to Gemini using its current supported video input method.
- [ ] Ask for JSON-only clip suggestions.
- [ ] Validate JSON with Zod; reject invalid timestamps.
- [ ] Save suggestions and update project status.

## Phase 4 — Rendering
- [ ] Implement render job endpoint.
- [ ] Worker downloads source to a temporary directory.
- [ ] Run FFmpeg with argument arrays (not shell-concatenated user input).
- [ ] Generate 9:16 clips and optional captions.
- [ ] Upload generated file and save metadata.
- [ ] Clean up temporary files even on failure.

## Phase 5 — Reliability
- [ ] Retries with a maximum attempt count.
- [ ] Clear processing status and user-readable error messages.
- [ ] Rate limiting and request-size limits.
- [ ] Structured logs without secrets or private video URLs.
- [ ] Test a small video and a large video.
- [ ] Deploy API and worker separately if the host cannot run long jobs.

## Definition of done for MVP
A user can create a project, upload a video, get at least three valid clip suggestions, render one selected clip, and download the actual MP4. The app shows errors instead of silently failing.
