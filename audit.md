# Audit — ClipForge AI

Run after each phase. Prompt for the AI:
> "Read prd.md, implementation_plan.md, and the code. For the phase just completed, go through this checklist. Report findings as: Severity (High/Med/Low), File, Issue, Fix. Do not change code until I approve."

## 1. Plan vs Code
- [ ] Every ticked item in `implementation_plan.md` exists in code
- [ ] No feature outside PRD MVP scope has been added
- [ ] Orphaned files / unused exports / dead routes
- [ ] Env vars used in code all exist in `.env.example`

## 2. Security
- [ ] Every API route authenticates and checks ownership
- [ ] Presigned URLs short-lived; storage bucket not public
- [ ] Upload mime/size validated on the server
- [ ] No secrets in repo or client bundle
- [ ] Rate limits on upload-init and generate/render
- [ ] FFmpeg args built safely (no shell string interpolation of user input)
- [ ] AI output validated with zod; timestamps clamped

## 3. Backend Correctness
- [ ] Jobs idempotent (re-run does not duplicate transcript/moments)
- [ ] Retry/backoff configured; failures set status + error message
- [ ] Temp files cleaned from worker disk
- [ ] DB indexes on `userId`, `projectId`, `status`
- [ ] Cascade deletes correct; storage cleanup on delete

## 4. Frontend
- [ ] Loading, empty, error states on every page
- [ ] No hydration warnings or console errors
- [ ] Keyboard access for editor controls
- [ ] Responsive at 375px and 1280px
- [ ] No client-side secrets or unsigned media URLs

## 5. Quality
- [ ] Lint, typecheck, tests green
- [ ] Core flows tested: ownership checks, moment JSON parsing, ASS generation, status transitions
- [ ] README accurate

## Findings Log
| Date | Phase | Severity | Issue | Status |
|------|-------|----------|-------|--------|
