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
