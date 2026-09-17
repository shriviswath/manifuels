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
