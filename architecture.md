# Architecture — Backend

## Overview
```
Browser ──► Next.js (apps/web) ──► Postgres
   │            │  └─► Redis (BullMQ queue)
   │            └─► R2/S3 (presigned URLs)
   └── PUT video ─► R2/S3
Worker (apps/worker) ◄── Redis
   ├─ ffmpeg / ffprobe
   ├─ Transcription API (Deepgram/Groq)
   └─ Gemini API
   └─► writes results to Postgres + R2/S3
```

## Data Model (Prisma)
```prisma
enum ProjectStatus { CREATED UPLOADED TRANSCRIBING ANALYZING READY FAILED }
enum ClipStatus { DRAFT QUEUED RENDERING DONE FAILED }

model User {
  id        String   @id            // Clerk user id
  email     String   @unique
  createdAt DateTime @default(now())
  projects  Project[]
}

model Project {
  id          String        @id @default(cuid())
  userId      String
  user        User          @relation(fields: [userId], references: [id], onDelete: Cascade)
  title       String
  status      ProjectStatus @default(CREATED)
  failedStage String?
  error       String?
  videoKey    String        // storage key
  audioKey    String?
  durationSec Float?
  width       Int?
  height      Int?
  createdAt   DateTime      @default(now())
  words       TranscriptWord[]
  moments     Moment[]
  clips       Clip[]
  @@index([userId, createdAt])
}

model TranscriptWord {
  id        Int     @id @default(autoincrement())
  projectId String
  project   Project @relation(fields: [projectId], references: [id], onDelete: Cascade)
  idx       Int
  text      String
  start     Float
  end       Float
  @@unique([projectId, idx])
}

model Moment {
  id        String  @id @default(cuid())
  projectId String
  project   Project @relation(fields: [projectId], references: [id], onDelete: Cascade)
  start     Float
  end       Float
  title     String
  hook      String
  reason    String
  score     Int
  clips     Clip[]
  @@index([projectId])
}

model Clip {
  id          String     @id @default(cuid())
  projectId   String
  project     Project    @relation(fields: [projectId], references: [id], onDelete: Cascade)
  momentId    String?
  moment      Moment?    @relation(fields: [momentId], references: [id], onDelete: SetNull)
  title       String
  start       Float
  end         Float
  cropX       Float      @default(0.5)   // 0..1 horizontal center
  captionStyle String    @default("bold-highlight")
  captions    Json       // [{start,end,text,words:[...]}] edited segments
  status      ClipStatus @default(DRAFT)
  outputKey   String?
  error       String?
  createdAt   DateTime   @default(now())
  @@index([projectId, status])
}
```

## API (REST, JSON, all require auth)
| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/projects` | body `{title, fileName, mimeType, sizeBytes}` → `{project, uploadUrl}` |
| POST | `/api/projects/:id/upload-complete` | mark UPLOADED, enqueue pipeline |
| GET | `/api/projects` | list own projects |
| GET | `/api/projects/:id` | project + status |
| GET | `/api/projects/:id/status` | lightweight polling |
| POST | `/api/projects/:id/retry` | resume from `failedStage` |
| DELETE | `/api/projects/:id` | delete rows + storage |
| GET | `/api/projects/:id/transcript` | words (paginated/chunked) |
| GET | `/api/projects/:id/moments` | suggested moments |
| POST | `/api/projects/:id/clips` | create clip (optionally from `momentId`) |
| PATCH | `/api/clips/:id` | update trim/captions/style/crop |
| POST | `/api/clips/:id/render` | enqueue render |
| GET | `/api/clips/:id` | clip + signed `outputUrl` when DONE |
| DELETE | `/api/clips/:id` | delete clip + output file |

Error shape: `{ "error": { "code": "NOT_FOUND", "message": "..." } }`

## Pipeline Stages (worker queues)
1. **probe-extract**: ffprobe → duration/size; `ffmpeg -i in -vn -ac 1 -ar 16000 audio.mp3` → upload audio.
2. **transcribe**: provider adapter `transcribe(audioUrl) → Word[]`; bulk insert (replace existing for idempotency).
3. **detect-moments**: chunk transcript (~8-10 min windows with overlap); prompt Gemini; validate; snap to word boundaries; dedupe overlaps; keep top 8.
4. **render-clip**: download source segment, generate ASS, run FFmpeg, upload MP4, set DONE.

## Moment Detection Prompt (spec — send to Gemini with `responseMimeType: "application/json"` and a response schema)
System: "You are an editor finding short-form clip moments. Return ONLY JSON matching the schema."
Criteria: strong hook in first 3s, self-contained, emotional/surprising/useful, 15-90s, clean start/end at sentence boundaries.
Output schema (zod):
```ts
z.object({ moments: z.array(z.object({
  start: z.number(), end: z.number(),
  title: z.string().max(80), hook: z.string().max(140),
  reason: z.string().max(240), score: z.number().int().min(0).max(100)
}))})
```

## FFmpeg Render (reference)
```
ffmpeg -ss {start} -to {end} -i source.mp4 \
  -vf "crop=ih*9/16:ih:(iw-ih*9/16)*{cropX}:0,scale=1080:1920,subtitles=captions.ass" \
  -r 30 -c:v libx264 -preset veryfast -crf 21 -c:a aac -b:a 128k -movflags +faststart out.mp4
```

## Env Vars
```
DATABASE_URL=
REDIS_URL=
CLERK_SECRET_KEY=
NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=
S3_ENDPOINT=
S3_REGION=auto
S3_BUCKET=
S3_ACCESS_KEY_ID=
S3_SECRET_ACCESS_KEY=
DEEPGRAM_API_KEY=        # or GROQ_API_KEY
GEMINI_API_KEY=
GEMINI_MODEL=gemini-2.5-flash   # change to the latest Flash model
```

## Folder Structure
```
clipforge/
├─ apps/
│  ├─ web/src/{app,components,lib,server/services}
│  └─ worker/src/{jobs,queues,lib}
├─ packages/{db,shared}
├─ docs/
├─ AGENTS.md  prd.md  implementation_plan.md  task.md  audit.md
└─ docker-compose.yml
```
