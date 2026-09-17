-- ═══════════════════════════════════════════════════════════════════
-- ManiFuels — apply_all.sql   (v3.1)
--
-- Migrations 001–014 in order. The base schema already exists and is NOT
-- recreated here; this adds the columns and tables the current client writes
-- to, repairs realtime, and re-asserts grants.
--
-- Idempotent and safe against live data. Runs as one transaction: if any part
-- fails, nothing changes.
--
-- Paste the whole file into: Supabase → SQL Editor → New query → Run.
-- Expected: "Success. No rows returned" plus a few NOTICE lines.
--
-- 007 and 008 touch live rows (settings carry-over, one-station re-key).
-- TAKE A BACKUP FIRST: Actions → Nightly database backup → Run workflow.
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

-- ▲▲▲ 001_reconcile.sql ▲▲▲


-- ▼▼▼ 002_dip_readings.sql ▼▼▼

-- ManiFuels — 002_dip_readings.sql
-- Physical tank dips. Book stock comes from the same meters the shift entry
-- uses, so it can never disagree with itself. A dip is an independent
-- measurement — the only thing in the system that can catch evaporation,
-- a leaking line, or theft.

create table if not exists public.dip_readings (
  id          bigint primary key,
  user_id     text not null default 'manifuels',   -- station id, not a person (see 008)
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

-- Match the access model of every other table in this schema (see 099 for RLS).
alter table public.dip_readings disable row level security;
grant all on public.dip_readings to anon, authenticated;

-- ▲▲▲ 002_dip_readings.sql ▲▲▲


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
    'owner_drawings','dip_readings','notes'
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

-- ▲▲▲ 003_realtime.sql ▲▲▲


-- ▼▼▼ 004_grants.sql ▼▼▼

-- ManiFuels — 004_grants.sql
--
-- stock_items started returning 401 Unauthorized to the anon key. The base
-- schema granted it, so something later revoked the grant or re-enabled RLS on
-- that table alone. This re-asserts the access model the whole schema uses.
--
-- This is a stopgap, not the answer. The answer is RLS with real auth, staged
-- as 099_rls_and_auth.sql.pending. Until then the anon key can read and write
-- everything, which is exactly the exposure that migration closes.

do $$
declare t text;
begin
  foreach t in array array[
    'shift_records','stock_items','ledger_entries','oil_invoices','fuel_loads',
    'app_settings','settings','pack_sizes','users','customer_profiles',
    'pack_register','activity_log','rate_history','staff','staff_attendance',
    'staff_payments','owner_drawings','dip_readings','notes'
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

-- ▲▲▲ 004_grants.sql ▲▲▲


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

-- ▲▲▲ 005_settings_config.sql ▲▲▲


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

-- ▲▲▲ 006_staff_salary_history.sql ▲▲▲


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

-- ▲▲▲ 007_settings_carryover.sql ▲▲▲


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

-- ▲▲▲ 008_one_station.sql ▲▲▲


-- ▼▼▼ 009_updated_at.sql ▼▼▼

-- ManiFuels — 009_updated_at.sql
--
-- The client sends `updated_at` on stock_items, ledger_entries, oil_invoices,
-- fuel_loads and owner_drawings. Merge resolution depends on it: a row without
-- a timestamp always loses to the server copy, so a local edit is silently
-- undone by the next sync.
--
-- More urgently: PostgREST rejects an insert naming a column that does not
-- exist. If this migration has not been applied, EVERY write to those four
-- tables fails, lands in the outbox, and the header shows "n unsent" forever.
-- That is the usual cause of "the app works but nothing reaches Supabase".
--
-- Idempotent. Safe against live data.

alter table public.stock_items    add column if not exists updated_at timestamptz default now();
alter table public.ledger_entries add column if not exists updated_at timestamptz default now();
alter table public.oil_invoices   add column if not exists updated_at timestamptz default now();
alter table public.fuel_loads     add column if not exists updated_at timestamptz default now();

-- Backfill so existing rows are not treated as "older than everything".
update public.stock_items    set updated_at = now() where updated_at is null;
update public.ledger_entries set updated_at = now() where updated_at is null;
update public.oil_invoices   set updated_at = now() where updated_at is null;
update public.fuel_loads     set updated_at = now() where updated_at is null;

-- Verify:
--   select column_name from information_schema.columns
--   where table_schema='public' and column_name='updated_at' order by table_name;

-- ▲▲▲ 009_updated_at.sql ▲▲▲


-- ▼▼▼ 010_ensure_tables.sql ▼▼▼

-- ManiFuels — 010_ensure_tables.sql
--
-- The base schema was created by hand in the SQL editor, so which tables exist
-- depends on which version of that script was run. Anything missing fails
-- silently: supabase-js resolves with {error}, the row is parked in the outbox,
-- and the app looks like it saved. This creates whatever is absent, leaves
-- whatever exists untouched, and asserts the access model.
--
-- Idempotent. Never drops or alters existing columns.

create table if not exists public.customer_profiles (
  customer_name  text primary key,
  user_id        text not null default 'manifuels',
  discount_per_l numeric default 0,
  notes          text default '',
  updated_at     timestamptz default now(),
  updated_by     text
);

create table if not exists public.pack_register (
  id         bigint primary key,
  user_id    text not null default 'manifuels',
  size       integer not null default 40,
  date       date not null,
  supplier   text default '',
  qty        numeric default 0,
  cost       numeric default 0,
  total_cost numeric default 0,
  notes      text default '',
  created_by text
);

create table if not exists public.staff (
  id             bigint primary key,
  user_id        text not null default 'manifuels',
  name           text not null,
  role           text default 'Operator',
  phone          text default '',
  monthly_salary numeric default 0,
  joined_date    date,
  notes          text default '',
  active         boolean default true,
  salary_history jsonb not null default '[]'::jsonb
);

create table if not exists public.staff_attendance (
  id       bigserial primary key,
  user_id  text not null default 'manifuels',
  staff_id bigint not null,
  date     date not null,
  shift    text not null,
  status   text,
  notes    text default ''
);
create unique index if not exists staff_attendance_natural_key
  on public.staff_attendance (staff_id, date, shift);

create table if not exists public.staff_payments (
  id               bigint primary key,
  user_id          text not null default 'manifuels',
  staff_id         bigint not null,
  date             date not null,
  type             text not null,
  amount           numeric default 0,
  advance_deducted numeric default 0,
  notes            text default '',
  created_by       text
);

create table if not exists public.owner_drawings (
  id         bigint primary key,
  user_id    text not null default 'manifuels',
  date       date not null,
  amount     numeric default 0,
  purpose    text default '',
  notes      text default '',
  created_by text,
  updated_at timestamptz default now()
);

-- Free-text notes. The only table in the schema with no fixed shape, which is
-- the point: it holds the things that do not have a form yet.
create table if not exists public.notes (
  id         bigint primary key,
  user_id    text not null default 'manifuels',
  title      text default '',
  body       text default '',
  tag        text default '',
  pinned     boolean default false,
  created_by text,
  updated_by text,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);
create index if not exists notes_recent_idx on public.notes (user_id, updated_at desc);

create table if not exists public.activity_log (
  id           bigserial primary key,
  username     text,
  display_name text,
  action       text,
  entity_type  text,
  entity_id    text,
  details      text default '',
  created_at   timestamptz default now()
);

create table if not exists public.rate_history (
  id         bigserial primary key,
  fuel       text,
  old_rate   numeric,
  new_rate   numeric,
  changed_by text,
  changed_at timestamptz default now()
);

-- Same access model as the rest of the schema until 099 lands.
do $$
declare t text;
begin
  foreach t in array array[
    'customer_profiles','pack_register','staff','staff_attendance',
    'staff_payments','owner_drawings','notes','activity_log','rate_history'
  ] loop
    execute format('alter table public.%I disable row level security', t);
    execute format('grant all on public.%I to anon, authenticated', t);
  end loop;
end $$;

do $$
declare s text;
begin
  for s in select sequencename from pg_sequences where schemaname='public' loop
    execute format('grant usage, select on sequence public.%I to anon, authenticated', s);
  end loop;
end $$;

-- ▲▲▲ 010_ensure_tables.sql ▲▲▲


-- ▼▼▼ 011_drawings_owner.sql ▼▼▼

-- ManiFuels — 011_drawings_owner.sql
--
-- A drawing recorded who ENTERED it (created_by) but not who TOOK the money.
-- With four owners on one account that is the only question the page is
-- actually asked, so it gets its own column rather than being buried in the
-- purpose text.

alter table public.owner_drawings
  add column if not exists owner      text default '',
  add column if not exists updated_at timestamptz default now();

update public.owner_drawings set updated_at = now() where updated_at is null;

-- ▲▲▲ 011_drawings_owner.sql ▲▲▲


-- ▼▼▼ 012_billing.sql ▼▼▼

-- ManiFuels — 012_billing.sql
--
-- Bill-to block for customer invoicing: registered name, GSTIN, address,
-- phone, email. One jsonb column rather than five, because it is printed as a
-- block and never queried field by field.

alter table public.customer_profiles
  add column if not exists billing jsonb not null default '{}'::jsonb;

-- ▲▲▲ 012_billing.sql ▲▲▲


-- ▼▼▼ 013_soft_deletes.sql ▼▼▼

-- ManiFuels — 013_soft_deletes.sql
--
-- A delete has never reached a second device. The client keeps deleted ids in
-- its own localStorage (`mf_tombstones`) and re-issues the delete whenever the
-- server still returns the row — which works, but only for the device that did
-- the deleting. Every other device pulls, does not see the row, keeps the copy
-- it already has, and pushes it back up on its next full save. The two devices
-- then fight and whichever syncs last wins, so a deleted shift or ledger row
-- reappears minutes later for no visible reason.
--
-- `deleted_at` is the half that was missing. The row stays, marked. Other
-- devices see the mark, drop their own copy, and stop re-uploading it.
--
-- It also means a mistaken delete is recoverable, which it never was before —
-- see "Undo" at the bottom.
--
-- Idempotent. Safe against live data. Adds columns only; drops nothing.

-- ── 1. the column, on every table the client deletes from or merges ────
do $$
declare t text;
begin
  foreach t in array array[
    'shift_records','stock_items','ledger_entries','oil_invoices','fuel_loads',
    'pack_register','staff','staff_payments','owner_drawings','notes',
    'dip_readings','customer_profiles'
  ] loop
    if to_regclass('public.'||t) is null then
      raise notice 'skipping %, not present', t;
      continue;
    end if;
    execute format('alter table public.%I add column if not exists deleted_at timestamptz', t);
  end loop;
end $$;

-- ── 2. partial indexes so the live-row reads stay cheap ────────────────
-- Only live rows are indexed, so the index does not grow with deleted history.
do $$
declare t text;
begin
  foreach t in array array[
    'shift_records','stock_items','ledger_entries','oil_invoices','fuel_loads',
    'pack_register','staff','staff_payments','owner_drawings','notes',
    'dip_readings','customer_profiles'
  ] loop
    if to_regclass('public.'||t) is null then continue; end if;
    execute format(
      'create index if not exists %I on public.%I (user_id) where deleted_at is null',
      t||'_live_idx', t);
  end loop;
end $$;

-- ── 3. NOT backfilled, deliberately ────────────────────────────────────
-- deleted_at stays NULL on every existing row, which is what "not deleted"
-- means. Nothing to update.

-- ── 4. same access model as the rest of the schema until 099 lands ─────
do $$
declare t text;
begin
  foreach t in array array[
    'shift_records','stock_items','ledger_entries','oil_invoices','fuel_loads',
    'pack_register','staff','staff_payments','owner_drawings','notes',
    'dip_readings','customer_profiles'
  ] loop
    if to_regclass('public.'||t) is null then continue; end if;
    execute format('grant all on public.%I to anon, authenticated', t);
  end loop;
end $$;

-- ═══════════════════════════════════════════════════════════════════════
-- What the client does with it
--
-- Deleting marks the row instead of removing it. The client filters marked
-- rows out on read (`_dropDeleted`) and drops its own copy in the merge, so
-- nothing marked here is visible in the app.
--
-- If this migration has NOT been applied, the client notices the missing
-- column on its first delete, warns once in the console, and falls back to the
-- old hard delete. Nothing breaks and nothing is lost — deletes simply keep
-- failing to reach other devices until you run this.
--
-- staff_attendance is not included: it is deleted by compound key
-- (staff_id, date, shift) rather than id, and still hard-deletes. Re-marking a
-- day overwrites the row anyway, so there is nothing to resurrect.
--
-- Verify:
--   select table_name from information_schema.columns
--    where table_schema='public' and column_name='deleted_at' order by 1;
--   -- expect 12 rows
--
-- What has been deleted, and when:
--   select 'ledger_entries' t, id, customer, amount, deleted_at
--     from ledger_entries where deleted_at is not null
--   order by deleted_at desc limit 50;
--
-- Undo a delete (the thing that was impossible before):
--   update ledger_entries set deleted_at = null where id = <id>;
--   -- then clear that id from mf_tombstones on the device that deleted it,
--   -- or it will simply re-mark it on the next sync:
--   --   localStorage.removeItem('mf_tombstones')   in the browser console
--
-- Purge rows deleted more than a year ago, once you are confident:
--   delete from ledger_entries where deleted_at < now() - interval '1 year';
-- ═══════════════════════════════════════════════════════════════════════

-- ▲▲▲ 013_soft_deletes.sql ▲▲▲


-- ▼▼▼ 014_payments_and_locking.sql ▼▼▼

-- ManiFuels — 014_payments_and_locking.sql
--
-- Two things the accounting layer has never had.
--
-- 1. A PAYMENT HAS NO IDENTITY.
--    Money received is added to `paid_back` on the bill it settles and nothing
--    else is kept. So a payment has no date of its own, no mode, no reference
--    and no row — which means none of these can be answered at all:
--        how much did we collect in cash last week
--        what did this customer actually pay, and when
--        reverse that payment, it was entered twice
--    `ledger_payments` records the event. `paid_back` on the bill is left
--    exactly as it is and remains the figure every report reads, so this is
--    purely additive: nothing recalculates, nothing moves.
--
-- 2. A SUBMITTED SHIFT IS FREELY EDITABLE.
--    Any shift can be re-saved or deleted at any time, and the P&L behind it
--    changes with no record that it ever read differently. `locked_at` closes
--    a shift; after that the client refuses to overwrite or delete it, and
--    unlocking is an owner action that lands in the activity log.
--
-- Idempotent. Safe against live data. Adds only; changes no existing value.

-- ── 1. the payment event ───────────────────────────────────────────────
create table if not exists public.ledger_payments (
  id          bigint primary key,
  user_id     text not null default 'manifuels',
  -- The bill this part of the payment landed on. A lump sum spread over six
  -- bills writes six rows sharing one `ref`.
  ledger_id   bigint,
  customer    text not null,
  date        date not null,
  amount      numeric not null default 0,
  mode        text default 'Cash',          -- Cash | GPay | Paytm | Bank Transfer | Cheque | Other
  ref         text default '',              -- PAY-xxxxx, groups the rows of one payment
  note        text default '',
  -- credit  = settled a bill
  -- advance = paid beyond the debt and is being held
  kind        text default 'credit',
  source      text default 'ledger',        -- ledger | shift  (where it was entered)
  created_by  text,
  created_at  timestamptz default now(),
  updated_at  timestamptz default now(),
  deleted_at  timestamptz
);

create index if not exists ledger_payments_cust_idx
  on public.ledger_payments (user_id, customer, date desc) where deleted_at is null;
create index if not exists ledger_payments_date_idx
  on public.ledger_payments (user_id, date desc) where deleted_at is null;
create index if not exists ledger_payments_ref_idx
  on public.ledger_payments (user_id, ref);
create index if not exists ledger_payments_bill_idx
  on public.ledger_payments (user_id, ledger_id);

-- ── 2. shift locking ───────────────────────────────────────────────────
alter table public.shift_records
  add column if not exists locked_at timestamptz,
  add column if not exists locked_by text;

-- Nothing is locked retrospectively. Locking is a decision someone makes about
-- a shift they have checked, not something to apply to history in bulk.

-- ── 3. same access model as the rest of the schema until 099 lands ─────
alter table public.ledger_payments disable row level security;
grant all on public.ledger_payments to anon, authenticated;

do $$
declare s text;
begin
  for s in select sequencename from pg_sequences where schemaname='public' loop
    execute format('grant usage, select on sequence public.%I to anon, authenticated', s);
  end loop;
end $$;

-- ── 4. realtime, to match every other synced table ─────────────────────
do $$
begin
  execute 'alter table public.ledger_payments replica identity full';
  begin
    execute 'alter publication supabase_realtime add table public.ledger_payments';
  exception
    when duplicate_object then null;
    when insufficient_privilege then
      raise notice 'cannot publish ledger_payments from SQL — add it under Database > Replication';
  end;
end $$;

-- ═══════════════════════════════════════════════════════════════════════
-- What the client does with it
--
-- Every payment now writes a row here as well as adding to `paid_back`:
-- the per-bill RECORD button, the bulk RECEIVE PAYMENT panel, and the
-- credit-back lines on a shift. `paid_back` stays authoritative, so if this
-- migration has not been applied the client logs one warning and carries on
-- recording payments exactly as before — only the history is missing.
--
-- Making `paid_back` a derived total of these rows is the NEXT step and is
-- deliberately not done here. It is a real cutover: it changes what every
-- report reads, and it needs the history below to be complete first.
--
-- Backfilling what has already happened
--
-- Payments recorded since the bulk-payback release stamped their reference
-- onto the bill's `notes`, e.g. "PAY-123: ₹7,000.00 Cash 2026-09-14". Those
-- can be recovered:
--   select id, customer, notes from ledger_entries
--    where notes ~ 'PAY-[0-9]+' order by date;
-- Anything older than that release left no trace beyond the paid_back total
-- and cannot be reconstructed — which is the reason this table exists.
--
-- Verify:
--   select count(*) from ledger_payments;
--   select column_name from information_schema.columns
--    where table_schema='public' and table_name='shift_records'
--      and column_name in ('locked_at','locked_by');   -- expect 2 rows
--
-- Collections by mode, last 7 days:
--   select mode, sum(amount) from ledger_payments
--    where deleted_at is null and date >= current_date - 7
--    group by mode order by 2 desc;
--
-- Unlock a shift from SQL, if someone locks one by mistake and no owner is
-- around (the app can do this too):
--   update shift_records set locked_at = null, locked_by = null
--    where id = '2026-09-17-morning';
-- ═══════════════════════════════════════════════════════════════════════

-- ▲▲▲ 014_payments_and_locking.sql ▲▲▲


-- ═══════════════════════════════════════════════════════════════════
-- Verify afterwards:
--   select distinct user_id from stock_items;              -- one row: manifuels
--   select user_id, opening_msd, opening_hsd from app_settings;
--   select table_name from information_schema.columns
--    where table_schema='public' and column_name='updated_at' order by 1;
--   select tablename, rowsecurity from pg_tables
--    where schemaname='public' order by 1;                 -- rowsecurity false
-- ═══════════════════════════════════════════════════════════════════
