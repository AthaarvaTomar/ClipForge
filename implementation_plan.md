# Implementation Plan — ClipForge AI

Rule: execute ONE checkbox at a time. Copy the active item into `task.md`.

## Phase 0 — Setup
- [x] 0.1 Init pnpm monorepo: `apps/web`, `apps/worker`, `packages/db`, `packages/shared`
- [ ] 0.2 Next.js 15 + Tailwind + shadcn/ui in `apps/web`
- [ ] 0.3 ESLint, Prettier, TS strict, Vitest configured
- [ ] 0.4 `.env.example`, `docker-compose.yml` (Postgres + Redis for local dev)
- [ ] 0.5 GitHub Actions: lint + typecheck + test

## Phase 1 — Auth & Database
- [ ] 1.1 Prisma schema (see `docs/architecture.md`) + first migration
- [ ] 1.2 Clerk integration, middleware protecting `/dashboard` and `/api`
- [ ] 1.3 User sync (Clerk webhook or upsert on first request)
- [ ] 1.4 Dashboard shell layout (sidebar, header, empty state)

## Phase 2 — Upload
- [ ] 2.1 Storage client (R2/S3) + presigned PUT/multipart helpers
- [ ] 2.2 `POST /api/projects` (create + return upload URL), validation, rate limit
- [ ] 2.3 Upload dropzone UI with progress and cancel
- [ ] 2.4 `POST /api/projects/:id/upload-complete` → enqueue pipeline
- [ ] 2.5 Project list UI with status badges

## Phase 3 — Pipeline (worker)
- [ ] 3.1 BullMQ setup, job types, retry/backoff, graceful shutdown
- [ ] 3.2 Job: probe video (ffprobe: duration, resolution) + extract audio (mono 16k)
- [ ] 3.3 Job: transcribe (provider adapter) → store `TranscriptWord` rows
- [ ] 3.4 Job: moment detection (Gemini, chunked, zod-validated) → `Moment` rows
- [ ] 3.5 Status updates + `GET /api/projects/:id/status`
- [ ] 3.6 Retry-from-stage endpoint + UI button

## Phase 4 — Review UI
- [ ] 4.1 Project page: video player (signed URL) + stepper
- [ ] 4.2 Transcript panel: search, click-to-seek, active word highlight
- [ ] 4.3 Moment cards list (score, title, reason, "Create clip")
- [ ] 4.4 Timeline component with moment markers

## Phase 5 — Clip Editor
- [ ] 5.1 `Clip` CRUD API (create from moment, update, delete)
- [ ] 5.2 Editor page: trim handles (start/end), live preview loop
- [ ] 5.3 Caption editor (edit text per segment) + 3 style presets
- [ ] 5.4 Crop x-offset slider with 9:16 preview overlay

## Phase 6 — Render
- [ ] 6.1 ASS subtitle generator (word-synced highlight)
- [ ] 6.2 FFmpeg render job: cut + crop 9:16 + burn captions → upload output
- [ ] 6.3 `POST /api/clips/:id/render`, status polling, error handling
- [ ] 6.4 Clip library cards: preview, download, re-render

## Phase 7 — Polish & Ship
- [ ] 7.1 Delete project (DB + storage cleanup)
- [ ] 7.2 Daily usage caps
- [ ] 7.3 Loading/empty/error states everywhere
- [ ] 7.4 Seed demo project + demo video for portfolio
- [ ] 7.5 Deploy: web (Vercel), worker (Railway/Fly with FFmpeg Dockerfile), DB (Neon), Redis (Upstash)
- [ ] 7.6 README with architecture diagram, GIF demo, setup steps

## Phase 8 — Audit
- [ ] 8.1 Run full `audit.md` checklist, fix findings
