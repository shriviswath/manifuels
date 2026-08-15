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
