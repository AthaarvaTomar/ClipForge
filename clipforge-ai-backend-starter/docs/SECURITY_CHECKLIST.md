# Security checklist

- [ ] Server-only secrets are not prefixed with `NEXT_PUBLIC_`.
- [ ] Protected routes verify a Supabase session.
- [ ] User ID is derived from verified auth, not client input.
- [ ] Project ownership is checked before accessing storage or records.
- [ ] Service-role operations happen only after auth/ownership checks.
- [ ] Storage buckets remain private.
- [ ] Signed URLs have short expiry and are never logged.
- [ ] Uploads enforce size, MIME type, and filename constraints.
- [ ] AI output is schema-validated and timestamps checked against duration.
- [ ] FFmpeg is called with safe argument arrays; no shell interpolation.
- [ ] Worker uses temporary directories and always cleans them up.
- [ ] API routes have rate limits before public launch.
- [ ] Error responses do not leak keys, stack traces, or private URLs.
- [ ] Logs exclude access tokens and signed URLs.
- [ ] Tests cover cross-user access attempts.
