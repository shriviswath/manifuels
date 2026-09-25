-- ════════════════════════════════════════════════════════════════════════════
-- ManiFuels — EMERGENCY UNDO of stage2_lock.sql
-- Puts the database back to "public key can read and write everything" so the
-- app works while a problem is fixed. This is the INSECURE state — re-run
-- stage2_lock.sql as soon as possible. Accounts and members are kept; the old
-- login table stays closed.
-- ════════════════════════════════════════════════════════════════════════════
drop event trigger if exists mf_rls_guard;
do $$
declare t text; p record;
begin
  for t in
    select c.relname from pg_class c join pg_namespace n on n.oid = c.relnamespace
     where n.nspname = 'public' and c.relkind in ('r', 'p') and c.relname <> 'users'
  loop
    for p in select policyname from pg_policies where schemaname = 'public' and tablename = t loop
      execute format('drop policy %I on public.%I', p.policyname, t);
    end loop;
    execute format('alter table public.%I disable row level security', t);
    execute format('grant all on public.%I to anon, authenticated', t);
  end loop;
end $$;
grant usage, select on all sequences in schema public to anon, authenticated;
