-- ManiFuels — 001_reconcile.sql
--
-- Your schema already exists; it was created by "ManiFuels Multi-Tenant Schema"
-- in the SQL Editor. This file does NOT recreate it. It only adds what the
-- v2.1 client needs and repairs two things that were quietly wrong.
--
-- Idempotent. Safe against live data.

-- ── 1. ledger_entries has no `notes`, but the client now writes a note on the
--    advance row it creates when a customer overpays.
alter table public.ledger_entries
  add column if not exists notes text default '';

-- ── 2. shift_records: the columns behind line-level COGS, testing volume,
--    meter carry-forward and loose-oil unit conversion.
alter table public.shift_records
  add column if not exists stock_sold      jsonb   not null default '[]'::jsonb,
  add column if not exists test_msd_l      numeric default 0,
  add column if not exists test_hsd_l      numeric default 0,
  add column if not exists meters          jsonb   not null default '{}'::jsonb,
  add column if not exists loose_oil_units numeric default 0;

-- ── 3. Link credit rows to the shift that created them, so deleting a shift
--    removes exactly the rows it created and nothing else.
alter table public.ledger_entries
  add column if not exists shift_id text;
create index if not exists ledger_shift_idx on public.ledger_entries (user_id, shift_id);

-- ── 4. activity_log has no user_id and rate_history has no user_id/date.
--    The client does not send them, so nothing to do — noted here so the next
--    person does not "helpfully" add them.

-- ── 5. staff_attendance is BIGSERIAL with no unique constraint on the natural
--    key. The client upserts on (staff_id, date, shift), so that index has to
--    exist or every attendance mark fails with "no unique constraint matching
--    the ON CONFLICT specification".
do $$
begin
  if not exists (
    select 1 from pg_indexes
    where schemaname='public' and tablename='staff_attendance'
      and indexdef like '%UNIQUE%staff_id%date%shift%'
  ) then
    create unique index staff_attendance_natural_key
      on public.staff_attendance (staff_id, date, shift);
  end if;
end $$;


-- ── 6. Two settings tables exist: `settings` (from the original schema) and
--    `app_settings` (added later). The client reads and writes `app_settings`,
--    so that is the live one. `settings` is dead weight.
--
--    Check which actually holds data before deleting anything:
--        select 'settings' t, * from settings
--        union all
--        select 'app_settings', * from app_settings;
--
--    If `settings` has the newer rates, copy them across first:
--        insert into app_settings (user_id, rates, opening_msd, opening_hsd, updated_at)
--        select user_id, rates, opening_msd, opening_hsd, updated_at from settings
--        on conflict (user_id) do update set
--          rates       = excluded.rates,
--          opening_msd = excluded.opening_msd,
--          opening_hsd = excluded.opening_hsd;
--
--    Then, once you are satisfied:
--        drop table settings;
--
--    Left as a comment deliberately — this is the only place your fuel rates
--    live and it is not something to automate blind.
