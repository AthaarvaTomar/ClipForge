# Architecture

## Main flow
1. Authenticated user creates a project.
2. API creates a private upload destination and records metadata.
3. Video uploads to Supabase Storage; the browser does not send large files through a Next.js API route.
4. User requests analysis. API queues an `analyze_video` job and returns `jobId`.
5. Worker obtains the private asset, sends it to Gemini using a supported video input flow, and requests structured clip suggestions.
6. Worker validates timestamps against the actual video duration and saves suggestions.
7. User chooses a suggestion and requests rendering.
8. Worker uses FFmpeg to trim/crop/add captions, uploads output, and stores `generated_clips` metadata.
9. API returns project/job status and signed download links.

## Responsibilities
- API: auth, validation, ownership checks, database writes, job creation/status, signed URLs.
- Supabase: database, auth, private object storage.
- Gemini: candidate moments and text/transcript understanding.
- Worker: expensive video analysis orchestration and FFmpeg processing.
- Frontend: upload progress, preview, select moments, display jobs and download clips.

## Do not do these
- Do not expose service-role or Gemini keys to the browser.
- Do not process large videos in a request/response handler.
- Do not trust AI timestamps without checking duration and ordering.
- Do not make storage buckets public by default.
- Do not implement a custom code execution/video processing sandbox in the browser.
