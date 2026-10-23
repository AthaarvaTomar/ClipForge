# Environment setup

Create `.env.local` from `.env.example`.

## Supabase
1. Create a project in the Supabase dashboard.
2. Copy the project URL and anon/publishable key.
3. Copy the service-role key only for trusted server-side operations. Never put it in frontend code or commit it.
4. Apply the SQL in `supabase/migrations/001_initial_schema.sql`.
5. Create private Storage buckets: `source-videos` and `generated-clips`.
6. Configure Supabase Auth providers and allowed local redirect URL (`http://localhost:3000`).

## Gemini
1. Create an API key in Google AI Studio.
2. Put it in `GEMINI_API_KEY`; never expose it to browser code.
3. Verify current Gemini video input/file API limits before implementing uploads. Video limits and SDK APIs can change.

## Local verification
```bash
npm install
npm run dev
```
Open `http://localhost:3000/api/health`.

Then run:
```bash
npm run typecheck
npm run build
```
