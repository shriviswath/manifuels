-- ════════════════════════════════════════════════════════════════════════════
-- ManiFuels — 020_staff_register.sql                               MF_STAFF_V1
--
-- 1. Columns the staff register now keeps:
--      staff.left_date            last working day (wages stop, final month kept)
--      staff.meta                 advance recovery plan, rejoin history
--      staff_payments.for_month   the month a salary payment settles (YYYY-MM)
--      staff_payments.mode, .ref  cash / UPI / bank / cheque, and UTR or cheque no.
-- 2. Salary and advance payments are readable and writable by OWNERS and
--    MANAGERS only. Staff logins keep attendance. (The staff list itself stays
--    readable by every member — names are needed to mark attendance.)
--
-- Requires the security stages (stage1_accounts.sql, stage2_lock.sql).
-- The app works before this runs: the new details stay on the phone that
-- entered them. Run in the Supabase SQL editor. Safe to run again.
-- ════════════════════════════════════════════════════════════════════════════

do $$ begin
  if to_regclass('mf_auth.members') is null then
    raise exception 'Run the security stages first (stage1_accounts.sql, stage2_lock.sql).';
  end if;
end $$;

alter table public.staff          add column if not exists left_date date;
alter table public.staff          add column if not exists meta      jsonb;
alter table public.staff_payments add column if not exists for_month text;
alter table public.staff_payments add column if not exists mode      text;
alter table public.staff_payments add column if not exists ref       text;

create or replace function public.mf_is_manager() returns boolean
language sql stable security definer set search_path = '' as $$
  select exists (select 1 from mf_auth.members where auth_uid = auth.uid() and role in ('owner', 'manager'));
$$;

-- The lock routine from stage2_lock.sql, with one more branch for
-- staff_payments, so running stage 2 again keeps this rule.
create or replace function mf_auth.lock_table(t text) returns void
language plpgsql security definer set search_path = '' as $$
declare p record;
begin
  execute format('alter table public.%I enable row level security', t);
  for p in select policyname from pg_policies where schemaname = 'public' and tablename = t loop
    execute format('drop policy %I on public.%I', p.policyname, t);
  end loop;
  if t = 'users' then
    return;                                        -- no policy: nobody reads the old login table
  elsif t = 'owner_drawings' then
    execute format($f$create policy mf_owners on public.%I for all to authenticated
      using ((select public.mf_is_owner())) with check ((select public.mf_is_owner()))$f$, t);
  elsif t = 'staff_payments' then                  -- MF_STAFF_V1: pay is owners' and managers' business
    execute format($f$create policy mf_mgr_read on public.%I for select to authenticated
      using ((select public.mf_is_manager()))$f$, t);
    execute format($f$create policy mf_mgr_insert on public.%I for insert to authenticated
      with check ((select public.mf_is_manager()))$f$, t);
    execute format($f$create policy mf_mgr_update on public.%I for update to authenticated
      using ((select public.mf_is_manager())) with check ((select public.mf_is_manager()))$f$, t);
    execute format($f$create policy mf_delete on public.%I for delete to authenticated
      using ((select public.mf_is_owner()))$f$, t);
  elsif t = 'activity_log' then                    -- append-only; owners read it
    execute format($f$create policy mf_log_write on public.%I for insert to authenticated
      with check ((select public.mf_is_member()))$f$, t);
    execute format($f$create policy mf_log_read on public.%I for select to authenticated
      using ((select public.mf_is_owner()))$f$, t);
  else
    execute format($f$create policy mf_read on public.%I for select to authenticated
      using ((select public.mf_is_member()))$f$, t);
    execute format($f$create policy mf_insert on public.%I for insert to authenticated
      with check ((select public.mf_is_member()))$f$, t);
    execute format($f$create policy mf_update on public.%I for update to authenticated
      using ((select public.mf_is_member())) with check ((select public.mf_is_member()))$f$, t);
    -- Permanent deletes: owners. The app deletes by marking rows (deleted_at);
    -- clearing an attendance mark is the one real delete staff make.
    execute format($f$create policy mf_delete on public.%I for delete to authenticated
      using ((select %s))$f$, t,
      case when t = 'staff_attendance' then 'public.mf_is_member()' else 'public.mf_is_owner()' end);
  end if;
end $$;
revoke all on function mf_auth.lock_table(text) from public;

select mf_auth.lock_table('staff_payments');

-- Verify:
--   select policyname, cmd from pg_policies where tablename = 'staff_payments';
--     → mf_mgr_read / mf_mgr_insert / mf_mgr_update / mf_delete
