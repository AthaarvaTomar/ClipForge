# AGENTS.md — ClipForge AI

Root rules for the AI coding agent (Gemini in Antigravity). Read this first every session.

## Project
ClipForge AI turns long videos into short, captioned, vertical clips. Upload → transcribe → AI finds moments → user reviews → render clips (9:16 + burned-in captions).
Source of truth: `prd.md`. Roadmap: `implementation_plan.md`. Current work: `task.md`. Review: `audit.md`. Deep specs: `docs/architecture.md`, `docs/frontend.md`.

## Working Rules
1. Work ONLY on the checkbox(es) listed in `task.md`. Do not start other items.
2. Never add features listed as out of scope in `prd.md`.
3. Before coding, state a 3-5 line plan. After coding, run lint + typecheck + tests and report results.
4. Prefer small diffs. No drive-by refactors. No new dependency without asking.
5. When finishing a task: tick it in `implementation_plan.md`, clear `task.md`, note anything odd in `audit.md`.
6. If a requirement is ambiguous, ask one question instead of guessing.

## Stack
- **Monorepo (pnpm workspaces):** `apps/web` (Next.js 15 App Router, TypeScript, Tailwind, shadcn/ui), `apps/worker` (Node + BullMQ), `packages/db` (Prisma), `packages/shared` (zod schemas, types)
- **DB:** PostgreSQL (Neon) via Prisma
- **Queue:** Redis + BullMQ
- **Storage:** S3-compatible (Cloudflare R2) with presigned URLs
- **Auth:** Clerk
- **AI:** Transcription = Deepgram or Groq Whisper (must return word-level timestamps). Moment detection = Gemini API via `@google/genai` (JSON-schema structured output; model set by `GEMINI_MODEL` env var)
- **Video:** FFmpeg (cut, crop to 9:16, burn captions via ASS subtitles)

## Commands
```
pnpm install
pnpm dev            # web + worker
pnpm --filter web dev
pnpm --filter worker dev
pnpm db:migrate     # prisma migrate dev
pnpm db:studio
pnpm lint && pnpm typecheck && pnpm test
```

## Code Style
- TypeScript strict. No `any`; use `unknown` + zod parse.
- Validate every API input and every AI JSON output with zod (`packages/shared`).
- Server Components by default; `"use client"` only when needed.
- API route handlers: thin. Business logic in `apps/web/src/server/services/*`.
- Worker jobs must be idempotent and safe to retry.
- Names: files `kebab-case`, components `PascalCase`, DB models singular PascalCase.
- Errors: never swallow. Log with context (`projectId`, `jobId`). Return typed error shapes `{ error: { code, message } }`.
- UI: Tailwind only, shadcn/ui primitives, dark mode supported, mobile-friendly.

## Security
- Never commit secrets. Use `.env.local`; keep `.env.example` updated.
- Every route checks auth and ownership (`userId` match) before reading/writing.
- Uploads: validate mime type + size server-side; presigned URLs expire in 15 min.
- Never trust AI output: clamp timestamps to video duration, validate schema.
- Rate-limit upload-init and "generate" endpoints.

## Definition of Done
Typecheck, lint, tests pass; feature works end-to-end locally; no console errors; env vars documented; checkbox ticked.
