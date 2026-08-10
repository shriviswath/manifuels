# Database

Postgres on Supabase. Migrations are plain SQL, applied in numeric order through
**Supabase → SQL Editor**.

Every file is idempotent — `create table if not exists`, `add column if not
exists`, guarded `do $$` blocks. Running one twice is a no-op, so it is safe to
paste the whole set if you are unsure what has already been applied.

## Order

Or just run `apply_all.sql`, which is 001–003 concatenated.

| File | What it does | Status |
|---|---|---|
| `001_reconcile.sql` | Columns the v2.1 client needs, plus two repairs | Apply |
| `002_dip_readings.sql` | Physical dip readings and stock variation | Apply |
| `003_realtime.sql` | `REPLICA IDENTITY FULL` **and** publication membership | Apply |
| `004_grants.sql` | Restores the anon grants `stock_items` lost | Apply |
| `005_settings_config.sql` | `app_settings.config` — pack sizes, tank config, loose-oil source | Apply last |
| `006_rls_and_auth.sql.pending` | RLS, Supabase Auth, `station_id` | **Do not apply yet** — see below |

### Why `004` exists

`stock_items` started returning 401 to the anon key — the grant was revoked or
RLS re-enabled on that table alone, after the base schema ran. `004` re-asserts
the access model across every table and grants the sequences too.

Be clear about what that means: the anon key, which is published in `index.html`
at a public URL, can read and write everything. That is the model this schema
already uses; `004` restores it rather than choosing it. `006` is the fix.

### Why `005` exists

Pack sizes, tank capacity and the loose-oil source lived only in each device's
`localStorage`, and all three change how a shift is calculated — two phones with
different settings produced different numbers from identical meter readings.
They now travel in `app_settings.config`.

## The base schema is not in here

It was created by a SQL Editor snippet called *ManiFuels Multi-Tenant Schema*
and lives only in the Supabase dashboard. These migrations deliberately do not
recreate it — they assume it exists and add to it. If you ever rebuild from
scratch, export that snippet into `000_base.sql` first.

## Two things the base schema got wrong

**Two settings tables.** Both `settings` and `app_settings` exist, with
identical columns. The client uses `app_settings`, so that is the live one and
`settings` is dead weight left over from the original schema — which is also why
the old `manifuels_realtime.sql` was pointing realtime at a table nothing writes
to. `001` ends with a commented block to check which one holds your current
rates, copy them across if needed, and drop the other. Deliberately not
automated: that table is the only place your fuel rates live.

**`staff_attendance`.** It is `BIGSERIAL` with `UNIQUE(staff_id, date, shift)`,
but the client sent no `id` and upserted `onConflict: 'id'`, which can never
match. Re-marking a day violated the unique index. Fixed on the client (conflict
on the natural key) and `001` makes sure that index exists under a resolvable
name.

## Why realtime was silently doing nothing

`REPLICA IDENTITY FULL` is only half of it. A table also has to be a member of
the `supabase_realtime` publication, and neither of the old snippets ever did
that — so realtime has never actually delivered anything. `003` does both, and
skips missing tables instead of aborting the whole transaction.

If it reports `cannot publish <table> from SQL`, add those tables through
**Database → Replication** in the dashboard instead. Some projects restrict
publication changes.

## Why 006 is staged, not applied

It is a coordinated cutover, not a migration you can run on its own:

* It moves authentication to Supabase Auth. The client still authenticates
  against the `users` table, so applying the RLS policies first would break
  every request immediately.
* It introduces `station_id`. Today `user_id` is the username, and every query
  filters on it — which means the four owners each see only the rows they
  personally entered. There are four sets of books, not one station's. Fixing
  this changes every query in the client at the same time.

Rename it to `006_rls_and_auth.sql` and apply it in the same release as the
client change. Take a backup first (`Actions → Nightly database backup → Run
workflow`).

## Backups

The free plan has no automated backups. `.github/workflows/backup.yml` runs
`pg_dump` nightly at 02:00 IST and keeps 90 days of artifacts. It needs one
secret:

```
SUPABASE_DB_URL = postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres
```

Use the **session** pooler on port 5432. The transaction pooler on 6543 cannot
run `pg_dump`.

That workflow also keeps the project alive — a free Supabase project auto-pauses
after seven days with no API traffic, and a paused project means the app cannot
sync until someone resumes it from the dashboard.
