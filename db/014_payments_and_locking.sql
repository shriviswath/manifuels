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
