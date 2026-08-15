-- ═══════════════════════════════════════════════════════════════════
-- ManiFuels — apply_all.sql   (v2.5)
--
-- Migrations 001–009 in order. Your base schema already exists and is NOT
-- recreated here.
--
-- Idempotent and safe against live data. Runs as one transaction: if any part
-- fails, nothing changes.
--
-- ⚠ 008 re-keys every row to one station id. It MUST go out together with the
--   client release that sets MF_STATION. Take a backup first.
--
-- Paste the whole file into: Supabase → SQL Editor → New query → Run
-- ═══════════════════════════════════════════════════════════════════

-- ▼▼▼ 001_reconcile.sql ▼▼▼

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

-- ▼▼▼ 002_dip_readings.sql ▼▼▼

-- ManiFuels — 002_dip_readings.sql
-- Physical tank dips. Book stock comes from the same meters the shift entry
-- uses, so it can never disagree with itself. A dip is an independent
-- measurement — the only thing in the system that can catch evaporation,
-- a leaking line, or theft.

create table if not exists public.dip_readings (
  id          bigint primary key,
  user_id     text not null default 'shriviswath',
  date        date not null,
  slot        text not null,                 -- morning | night | opening | closing
  type        text not null,                 -- MSD | HSD
  dip_cm      numeric,                       -- the stick reading as taken
  observed_l  numeric not null default 0,    -- litres in the tank, from the chart
  book_l      numeric not null default 0,    -- opening + loads − sales − testing
  variation_l numeric not null default 0,    -- observed − book; negative = loss
  notes       text default '',
  created_by  text,
  saved_at    timestamptz default now()
);

create unique index if not exists dip_readings_unique_slot
  on public.dip_readings (user_id, date, slot, type);
create index if not exists dip_readings_date_idx
  on public.dip_readings (user_id, type, date desc);

-- Match the access model of every other table in this schema (see 006 for RLS).
alter table public.dip_readings disable row level security;
grant all on public.dip_readings to anon, authenticated;

-- ▼▼▼ 003_realtime.sql ▼▼▼

-- ManiFuels — 003_realtime.sql
--
-- Two things are needed for realtime, and the old scripts only ever did one:
--   • REPLICA IDENTITY FULL, so updates and deletes carry the old row
--   • membership of the supabase_realtime publication  ← this was never done
--
-- Skips tables that are not present instead of aborting. The SQL editor runs a
-- script as one transaction, so a single missing table used to roll back every
-- ALTER above it with no obvious error.

do $$
declare t text;
begin
  foreach t in array array[
    'shift_records','stock_items','ledger_entries','oil_invoices','fuel_loads',
    'app_settings','pack_sizes','users','customer_profiles','pack_register',
    'activity_log','rate_history','staff','staff_attendance','staff_payments',
    'owner_drawings','dip_readings'
  ] loop
    if to_regclass('public.'||t) is null then
      raise notice 'skipping %, not present', t;
      continue;
    end if;
    execute format('alter table public.%I replica identity full', t);
    begin
      execute format('alter publication supabase_realtime add table public.%I', t);
    exception
      when duplicate_object then null;   -- already published
      when insufficient_privilege then
        raise notice 'cannot publish % from SQL — add it under Database > Replication', t;
    end;
  end loop;
end $$;

-- ▼▼▼ 004_grants.sql ▼▼▼

-- ManiFuels — 004_grants.sql
--
-- stock_items started returning 401 Unauthorized to the anon key. The base
-- schema granted it, so something later revoked the grant or re-enabled RLS on
-- that table alone. This re-asserts the access model the whole schema uses.
--
-- This is a stopgap, not the answer. The answer is RLS with real auth, staged
-- as 005_rls_and_auth.sql.pending. Until then the anon key can read and write
-- everything, which is exactly the exposure that migration closes.

do $$
declare t text;
begin
  foreach t in array array[
    'shift_records','stock_items','ledger_entries','oil_invoices','fuel_loads',
    'app_settings','settings','pack_sizes','users','customer_profiles',
    'pack_register','activity_log','rate_history','staff','staff_attendance',
    'staff_payments','owner_drawings','dip_readings'
  ] loop
    if to_regclass('public.'||t) is null then
      raise notice 'skipping %, not present', t;
      continue;
    end if;
    execute format('alter table public.%I disable row level security', t);
    execute format('grant all on public.%I to anon, authenticated', t);
  end loop;
end $$;

-- BIGSERIAL tables need their sequences granted too, or an insert fails with
-- "permission denied for sequence".
do $$
declare s text;
begin
  for s in
    select sequencename from pg_sequences where schemaname='public'
  loop
    execute format('grant usage, select on sequence public.%I to anon, authenticated', s);
  end loop;
end $$;

-- Verify afterwards:
--   select tablename, rowsecurity from pg_tables
--   where schemaname='public' order by 1;          -- rowsecurity should be false

-- ▼▼▼ 005_settings_config.sql ▼▼▼

-- ManiFuels — 005_settings_config.sql
--
-- Pack sizes, tank capacities and the loose-oil source were stored only in
-- each device's localStorage. All three change how a shift is calculated, so
-- two phones with different settings produced different numbers from identical
-- meter readings — silently.
--
-- They now ride in app_settings.config rather than needing three new tables.

alter table public.app_settings
  add column if not exists config jsonb not null default '{}'::jsonb;

-- Shape:
--   {
--     "packSizes":   [{"size":40,"rate":40,"enabled":true}, ...],
--     "tankCfg":     {"capMSD":15000,"capHSD":20000,"tol":0},
--     "looseOilCfg": {"stockId":"502","litresPerUnit":5}
--   }

-- ▼▼▼ 006_staff_salary_history.sql ▼▼▼

-- ManiFuels — 006_staff_salary_history.sql
--
-- Staff details are now editable in place: phone numbers change, people get
-- promoted, salaries go up. Editing the row keeps attendance and payment
-- history attached to the same person instead of creating a second record.
--
-- A raise is a dated event, not just a new number — without the date, an old
-- payslip cannot be explained. Each revision is stored as
--   { "date": "2026-08-11", "from": 14000, "to": 16000, "by": "kalimuthu" }

alter table public.staff
  add column if not exists salary_history jsonb not null default '[]'::jsonb;

-- ▼▼▼ 007_settings_carryover.sql ▼▼▼

-- ManiFuels — 007_settings_carryover.sql
--
-- Two settings tables exist. The client uses `app_settings`; `settings` is
-- left over from the original schema. When the app moved across, the opening
-- tank volumes did not come with it:
--
--   settings      opening_msd 3023.91   opening_hsd 6405.2   (03 May 2026)
--   app_settings  opening_msd 0         opening_hsd 0
--
-- Zero openings are why the tank gauges read empty. This copies the volumes
-- across, leaves the rates alone (app_settings has the current ones), and then
-- retires the dead table.
--
-- Run AFTER taking a backup: Actions → Nightly database backup → Run workflow.

-- 1 ── carry the opening volumes over, only where they are still unset
update public.app_settings a
set opening_msd = s.opening_msd,
    opening_hsd = s.opening_hsd,
    updated_at  = now()
from public.settings s
where a.user_id = s.user_id
  and coalesce(a.opening_msd,0) = 0
  and coalesce(a.opening_hsd,0) = 0
  and (coalesce(s.opening_msd,0) <> 0 or coalesce(s.opening_hsd,0) <> 0);

-- 2 ── check before dropping. Expect the real volumes, not zeros.
--   select user_id, rates, opening_msd, opening_hsd from public.app_settings;

-- 3 ── retire the dead table. Uncomment once step 2 looks right.
--   drop table public.settings;

-- ▼▼▼ 008_one_station.sql ▼▼▼

-- ManiFuels — 008_one_station.sql
--
-- Every table is filtered on user_id, and the client set user_id to the
-- USERNAME. So each of the four owners had a separate stock list, separate
-- rates, separate opening volumes, separate shifts — four sets of books for
-- one bunk. It showed up plainly in the data: every stock_items row belonged
-- to 'shriviswath', so Kumutha logged in to an empty stock list.
--
-- This re-keys every row to a single station id. Who did what is not lost:
-- created_by / updated_by and the activity log still record the person.
--
-- Pair this with the client release that sets MF_STATION='manifuels'. Applying
-- one without the other hides the data until both are in place.
--
-- TAKE A BACKUP FIRST: Actions → Nightly database backup → Run workflow.

do $$
declare t text;
begin
  -- app_settings and customer_profiles are handled separately: their primary
  -- keys involve user_id, so a blind update can collide.
  foreach t in array array[
    'shift_records','stock_items','ledger_entries','oil_invoices','fuel_loads',
    'pack_register','pack_sizes','staff','staff_attendance','staff_payments',
    'owner_drawings','dip_readings'
  ] loop
    if to_regclass('public.'||t) is null then
      raise notice 'skipping %, not present', t;
      continue;
    end if;
    execute format('update public.%I set user_id = %L where user_id <> %L',
                   t, 'manifuels', 'manifuels');
    execute format('alter table public.%I alter column user_id set default %L',
                   t, 'manifuels');
  end loop;
end $$;

-- app_settings: primary key is user_id, so collapse to one row. Keep the row
-- that actually has opening volumes; if none does, keep any row.
do $$
declare keep text;
begin
  select user_id into keep from public.app_settings
   order by (coalesce(opening_msd,0) + coalesce(opening_hsd,0)) desc,
            updated_at desc nulls last
   limit 1;
  if keep is null then
    insert into public.app_settings (user_id) values ('manifuels')
    on conflict (user_id) do nothing;
  else
    delete from public.app_settings where user_id <> keep;
    update public.app_settings set user_id = 'manifuels' where user_id = keep;
  end if;
  alter table public.app_settings alter column user_id set default 'manifuels';
end $$;

-- customer_profiles is keyed on customer_name alone, so no collision.
update public.customer_profiles set user_id = 'manifuels' where user_id <> 'manifuels';
alter table public.customer_profiles alter column user_id set default 'manifuels';

-- Verify:
--   select distinct user_id from stock_items;      -- one row: manifuels
--   select user_id, opening_msd, opening_hsd, rates from app_settings;  -- one row

-- ▼▼▼ 009_updated_at.sql ▼▼▼

-- ManiFuels — 009_updated_at.sql
--
-- The client stamps updated_at on every row it writes and uses it to resolve
-- sync conflicts: newest wins. Three tables never had the column, so Postgres
-- rejected the whole row with
--
--   column "updated_at" of relation "fuel_loads" does not exist
--
-- The write then sat in the outbox retrying — which is why fuel loads saved on
-- one device never appeared on another. stock_items and shift_records already
-- had the column, which is why those synced fine and the fault looked specific
-- to loads.
--
-- Without a timestamp the merge falls back to "server always wins", so an edit
-- made on a phone is silently undone by the next sync. These columns are what
-- make last-write-wins actually work.

alter table public.ledger_entries
  add column if not exists updated_at timestamptz default now();

alter table public.oil_invoices
  add column if not exists updated_at timestamptz default now();

alter table public.fuel_loads
  add column if not exists updated_at timestamptz default now();

-- Existing rows get a sensible starting point rather than a null, so the first
-- merge after this migration does not treat every server row as older than a
-- local copy that has never been edited.
update public.ledger_entries set updated_at = coalesce(updated_at, created_at, now()) where updated_at is null;
update public.oil_invoices   set updated_at = coalesce(updated_at, created_at, now()) where updated_at is null;
update public.fuel_loads     set updated_at = coalesce(updated_at, created_at, now()) where updated_at is null;

-- Verify:
--   select table_name from information_schema.columns
--   where column_name='updated_at' and table_schema='public' order by 1;
--   -- expect: fuel_loads, ledger_entries, oil_invoices, shift_records, stock_items, app_settings, customer_profiles

-- ═══════════════════════════════════════════════════════════════════
-- Verify:
--   select distinct user_id from stock_items;                    -- manifuels
--   select table_name from information_schema.columns
--    where column_name='updated_at' and table_schema='public' order by 1;
--   select user_id, opening_msd, opening_hsd from app_settings;  -- one row
-- ═══════════════════════════════════════════════════════════════════
