# ClipForge AI — Frontend Studio

Modern, responsive dark-themed web client for the ClipForge AI video repurposing platform. Built with React 19, TypeScript, and Vite.

## Architecture

- **Framework**: React 19 with TypeScript and Vite
- **Styling**: Tailored Vanilla CSS design system with curated dark palette (`#0f1115`, `#171a21`, `#232833`, `#ff7a45`)
- **API Client**: Strongly-typed HTTP client wrapping `fetch` and `XMLHttpRequest` with upload progress tracking, structured error parsing, and optional `X-API-Key` forwarding (`src/api/client.ts`).
- **Pages**:
  - `NewProject.tsx`: Drag-and-drop video upload zone with format selection (9:16 vertical shorts), AI enhancement toggles, live XHR upload progress, and recent projects list.
  - `DebugPage.tsx`: Interactive API debugging console verifying backend connectivity, health, presets, and background job telemetry.

## Getting Started

### 1. Install Dependencies
```bash
npm install
```

### 2. Environment Configuration
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```
Ensure `VITE_API_URL` points to your running FastAPI backend (defaults to `http://localhost:8000`).

### 3. Run Development Server
```bash
npm run dev
```

### 4. Build for Production
```bash
npm run build
```
Type checks via `tsc -b` and bundles production assets into `dist/`.
