# Frontend Spec

## Pages (Next.js App Router)
| Route | Purpose |
|-------|---------|
| `/` | Landing: hero, demo GIF, CTA |
| `/sign-in`, `/sign-up` | Clerk |
| `/dashboard` | Project grid, "New project" button, empty state |
| `/dashboard/new` | Upload dropzone + title |
| `/projects/[id]` | Player, status stepper, transcript, moments |
| `/projects/[id]/clips/[clipId]` | Clip editor |
| `/projects/[id]/library` | Clip cards (or a tab on project page) |

## Key Components
- `UploadDropzone` — drag/drop, validate type/size, XHR progress, cancel
- `ProjectCard` — thumbnail, title, status badge, date
- `StatusStepper` — Uploaded → Transcribing → Analyzing → Ready; error + Retry
- `VideoPlayer` — wraps `<video>`, exposes `seek`, `currentTime`
- `TranscriptPanel` — virtualized word list, search, click-to-seek, active word highlight
- `MomentCard` — title, hook, score ring, reason, "Preview" / "Create clip"
- `Timeline` — scrubber with moment markers; trim handles in editor mode
- `CaptionEditor` — editable segments, style preset picker
- `CropPreview` — 9:16 overlay on source frame + x-offset slider
- `ClipCard` — poster, status, Download, Re-render
- `EmptyState`, `ErrorState`, `Skeleton*`

## State & Data
- Server Components fetch initial data; client components use TanStack Query for polling (`refetchInterval: 3000` while status not terminal).
- Local editor state via `useReducer`; debounce PATCH (500ms).
- Forms: react-hook-form + zod (shared schemas).

## UX Requirements
- Polished dark-first UI, subtle motion, clear status feedback.
- Editor shortcuts: Space play/pause, `[` `]` set start/end, arrows nudge 0.1s.
- All async actions show loading + error toasts (sonner).
- Responsive: single column on mobile; editor is desktop-first but usable on tablet.

## Caption Style Presets
1. **Bold Highlight** — white bold, active word yellow, bottom third
2. **Minimal** — white, thin outline, small
3. **Boxed** — dark rounded box behind text

## Accessibility
Focus rings, ARIA labels on icon buttons, caption color contrast >= 4.5:1, `prefers-reduced-motion` respected.
