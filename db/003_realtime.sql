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
