# Auth, RLS, and Login Audit DB Boundary

Status: accepted

## Decision

The API treats application-layer authorization as the active security boundary.
FastAPI verifies the app JWT, then repositories must scope user-owned data by the
verified `users.id`. Supabase RLS is not treated as active protection because this
repo has no `supabase/migrations/` policy source and the app JWT is not automatically
visible to `auth.uid()`.

If a future client talks directly to Supabase, add a separate design first: either
use Supabase Auth JWTs end to end, or inject request claims into each DB transaction
and write RLS policies against those claims.

## Login Audit Writes

Login audit writes are not part of the login transaction. The request path enqueues
a JSON event to Celery, and the worker bulk inserts into `login_audits`. If enqueue
fails, login still succeeds and the failure is logged/metriced.

Default retention is 90 days. Before sustained high-volume login traffic, add monthly
partitioning or a scheduled retention delete for `login_audits`; do not let the table
grow without an owner and retention job.

## Query Performance

Calendar range reads use dedicated indexes for:

- `user_calendar_events(user_id, start_at, end_at)`
- `notice_schedules(start_at, end_at) WHERE is_tbd = false AND start_at IS NOT NULL`

`fetch_source_freshness_async` must stay as a single query. Reintroducing per-source
latest-attempt lookups recreates an N+1 path on crawl stats.
