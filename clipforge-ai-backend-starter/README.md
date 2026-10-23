# ClipForge AI — Backend-First Starter

ClipForge AI turns long videos into short, shareable clips. This starter intentionally begins with the backend and includes architecture, API contracts, database schema, environment setup, implementation prompts, and a small runnable Next.js API foundation.

## MVP scope
1. Create and list video projects.
2. Track uploaded video metadata and processing status.
3. Ask Gemini to identify promising clip moments and return structured timestamps.
4. Render selected clips with FFmpeg in a background worker (later phase).
5. Store generated clip metadata and download URLs.

## Stack
- Next.js App Router + TypeScript (API backend and, later, frontend)
- Supabase Postgres + Storage
- Gemini API for video understanding and clip suggestions
- FFmpeg for actual video rendering (worker phase)
- Zod for request validation

## Important architecture decision
Do not run long FFmpeg jobs inside a normal serverless API request. The API should create a job and return a job ID; a worker processes it asynchronously. For the first local MVP, a worker can run as a separate Node process. Deploy the worker to a service that supports long-running processes and FFmpeg.

## Quick start
1. Install Node.js LTS.
2. Copy `.env.example` to `.env.local` and fill in keys.
3. Run `npm install`.
4. Run `npm run dev`.
5. Open `http://localhost:3000/api/health`.

The health endpoint works without external credentials. Other routes require Supabase configuration.

## Build order
See `docs/BUILD_PLAN.md`. Start with the backend in small, testable steps. Do not ask an AI coding agent to implement the entire project in one prompt.

## Security basics
- Never expose `SUPABASE_SERVICE_ROLE_KEY` or `GEMINI_API_KEY` to browser code.
- Validate all request bodies with Zod.
- Enforce ownership checks on every project/video/clip query.
- Use signed, short-lived URLs for private video assets.
- Apply upload size/type limits and rate limits before public launch.
- Do not trust AI-generated timestamps; validate them against actual video duration.
