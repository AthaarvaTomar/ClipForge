# Vibe-coding prompts (run one at a time)

Give your coding agent the existing repository context and ask it to make small diffs. Review every change before proceeding.

## Prompt 1 — Inspect before coding
Read `README.md`, `docs/ARCHITECTURE.md`, `docs/API_CONTRACT.md`, `docs/BUILD_PLAN.md`, and the SQL migration. Summarize the current architecture and identify missing pieces. Do not modify files yet. Do not invent completed features.

## Prompt 2 — Secure server-side Supabase auth
Implement server-side Supabase authentication for Next.js App Router using the currently recommended Supabase SSR package and cookie-based sessions. Add the required server client helper. Every protected API route must derive the user ID from a verified session; never accept a user ID from JSON as authority. Do not use the service-role client until after authentication and ownership have been checked. Add a small `/api/me` endpoint and explain how to configure local env vars. Keep changes minimal and typecheck.

## Prompt 3 — Project CRUD
Implement `POST /api/projects`, `GET /api/projects`, and `GET /api/projects/[projectId]` according to `docs/API_CONTRACT.md`. Use Zod validation, consistent error JSON, and ownership checks. Do not add frontend UI. Add tests or a manual verification guide. Run typecheck and fix errors.

## Prompt 4 — Upload URLs
Implement `POST /api/projects/[projectId]/upload-url`. Validate filename, content type and size. Check ownership first. Use a private Supabase Storage bucket and a safe storage path built from verified user ID, project ID and a sanitized filename. Return only the fields defined in the API contract. Do not route the file bytes through the API server.

## Prompt 5 — Queue analysis job
Implement `POST /api/projects/[projectId]/analyze`. Confirm the project has an uploaded source video, create a `processing_jobs` row with `queued` status, update project status, and return HTTP 202. Do not call Gemini inside the request. Add idempotency or prevent duplicate active jobs.

## Prompt 6 — Gemini analysis module
Create a server-only module that accepts a private video asset reference and returns structured clip suggestions. Check current Gemini SDK documentation before choosing the video upload/input method. Request JSON with `title`, `rationale`, `startSeconds`, `endSeconds`, `score`, and `transcriptExcerpt`. Validate output with Zod. Clamp/reject timestamps outside the actual video duration. Never return secrets or private storage URLs to the browser.

## Prompt 7 — Local worker
Create a separate Node worker command that polls queued jobs, claims a job safely, marks it processing, executes analysis, stores suggestions, and marks it completed or failed. Add retry limits and ensure a crashed worker does not leave jobs stuck forever. Do not run FFmpeg or long AI calls inside an API route.

## Prompt 8 — FFmpeg clip renderer
Implement a rendering service for a selected suggestion. Use FFmpeg installed on the worker machine. Use `spawn` with an argument array, never concatenate user input into a shell command. Render a vertical 9:16 MP4 with a configurable caption style. Upload to private storage, store `generated_clips`, clean up temp files, and update job status.

## Prompt 9 — Quality and security review
Review all backend routes for authentication, ownership checks, validation, rate limiting, error leakage, upload limits, safe temporary-file handling, and accidental secret exposure. Add tests for unauthorized users, another user's project ID, invalid MIME, oversized upload, malformed Gemini JSON, invalid timestamps, FFmpeg failure, and retry behavior. Do not claim a test passed unless you ran it.

## Prompt 10 — Frontend integration contract
Without building the UI, document the exact request/response and error cases for each implemented endpoint. Add sample curl commands that work with the project's auth setup. Identify endpoints that are still placeholders.
