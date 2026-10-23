# Current Task

> Feed ONLY this file (plus AGENTS.md) to the AI each session. Keep it to ~2 hours of work.

## Active Item
- Plan ref: 1.1 Prisma schema (done except migration)

## Goal
Set up Prisma schema in `packages/db`, export a singleton PrismaClient, validate schema, and generate Prisma client.

## Steps
- [x] Paste the schema from docs/architecture.md into packages/db/prisma/schema.prisma
- [x] Export a singleton PrismaClient from packages/db/src/index.ts
- [x] Run `prisma validate` and `prisma generate`
- [ ] Run `prisma migrate dev --name init` (deferred until live DB configured)

## Constraints
- No seed data, no other packages touched.
- Work strictly inside `packages/db`.

## Done When
- `prisma validate` succeeds
- `prisma generate` succeeds
- `pnpm --filter @clipforge/db typecheck` passes

## Notes / Blockers
- run init migration once DATABASE_URL is real
