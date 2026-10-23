# API contract (planned MVP)

All project endpoints require a valid Supabase-authenticated user. The server must verify the bearer token/session and derive `userId` from the verified identity. Never accept `userId` from the request body as authority.

## GET /api/health
Response `200`
```json
{ "ok": true, "service": "clipforge-ai-api", "timestamp": "ISO-8601" }
```

## POST /api/projects
Request
```json
{ "title": "Podcast highlights" }
```
Response `201`
```json
{ "project": { "id": "uuid", "title": "Podcast highlights", "status": "draft" } }
```

## GET /api/projects
Response `200`
```json
{ "projects": [] }
```

## GET /api/projects/:projectId
Response `200`
```json
{ "project": {}, "suggestions": [], "clips": [], "jobs": [] }
```

## POST /api/projects/:projectId/upload-url
Request
```json
{ "filename": "episode.mp4", "contentType": "video/mp4", "sizeBytes": 123456 }
```
Response
```json
{ "uploadUrl": "signed upload URL", "storagePath": "user/project/source.mp4" }
```
Validate file extension/MIME and size. Store in a private bucket. The exact signed-upload implementation depends on the selected Supabase Storage upload method.

## POST /api/projects/:projectId/analyze
Response `202`
```json
{ "job": { "id": "uuid", "status": "queued", "type": "analyze_video" } }
```

## GET /api/jobs/:jobId
Response
```json
{ "job": { "id": "uuid", "status": "queued|processing|completed|failed", "error": null } }
```

## POST /api/projects/:projectId/clips/:suggestionId/render
Request
```json
{ "aspectRatio": "9:16", "captionStyle": "clean" }
```
Response `202`
```json
{ "job": { "id": "uuid", "status": "queued", "type": "render_clip" } }
```

## Error format
```json
{ "error": { "message": "Human-readable message" } }
```
Use 400 for invalid input, 401 for unauthenticated, 403 for forbidden, 404 for missing resources, 413 for oversized uploads, 429 for rate limits, and 500 for unexpected server errors.
