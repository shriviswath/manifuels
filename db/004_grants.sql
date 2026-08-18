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
