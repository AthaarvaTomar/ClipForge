# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

React 19, React Router, Zustand, plain CSS with CSS variables. Backend: FastAPI, Celery, Redis, SQLAlchemy.

## Users

Solo creators and students turning long video recordings into short-form vertical clips (Shorts / Reels / TikToks).

## Product Purpose

ClipForge turns long recordings into short, captioned vertical clips via natural language AI planning. The creator describes an edit in plain English, the AI generates discrete multi-track timeline operations, and the result is a fully editable multi-track timeline with undo/redo and version history, not an opaque black-box MP4 render. The AI performs the heavy lifting and initial edit pass, allowing creators to refine cuts, transitions, grades, and captions by hand.

## Positioning

Unlike black-box video generators or basic clipping scripts, ClipForge exposes every AI decision as an inspectable, reversible operation on a real multi-track timeline engine (video, overlay B-roll, captions, audio, and music), complete with optimistic client-side execution, single-group undo/redo, and live WebSocket synchronization.

## Operating Context

- Desktop-first browser editor (min width 1100px; displays a screen size notice on smaller viewports).
- Operate mode: prioritizes high density, scannability, precision, low latency, and zero gratuitous decoration.
- Creator reviews AI edit proposals, inspects clips, navigates waveform audio and frame dividers, tunes captions and grades, and triggers high-fidelity rendering.

## Capabilities and Constraints

- AI Edit Planner supporting natural language instructions: "tighten first 15s", "remove repeated takes", "remove all silences", "add B-roll", "make 3 Shorts".
- Real multi-track timeline with video, overlay, caption, audio, and music tracks.
- Operation engine with mathematical inverses, version optimistic concurrency, and undo/redo stacks.
- Proxy playback with client-side captions and server-side FFmpeg timeline rendering.
- Exact design tokens: dark surfaces, Geist/Geist Mono typography, 6px/8px radii, no gradients or drop shadows.

## Brand Commitments

- Name: ClipForge AI
- Mode: Operate
- Accent color: #3F6BF0 (primary buttons, selection, agent highlights) with soft text #9DB4FF
- Surface palette: bg #0E0F11, panel #151619, raised #1B1D21, preview #0A0B0D, subtle band #121316
- Borders: #23252A (default), #2B2E35 (controls)
- Text: #ECEDEF, muted #8B9098
- Playhead: #F2555A
- Status dots: green #3DCB8A, amber #E0A93B, grey #6B7078

## Product Principles

1. **The brief wins**: exact token fidelity, strict Operate mode, no unrequested aesthetic drift.
2. **Deterministic & Reversible**: Every AI action is a distinct timeline operation that can be audited, individually fine-tuned, or reverted with a single undo.
3. **High Information Density & Speed**: Instant feedback, optimistic state, keyboard accessibility (Ctrl+Z, Ctrl+Shift+Z, C for razor), clean Geist Mono timestamps.
