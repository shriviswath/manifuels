-- ════════════════════════════════════════════════════════════════════════════
-- ManiFuels — SECURITY STAGE 2: lock the database               MF_AUTH_LOCK_V3
--
-- Run ONLY after:
--   1. stage1_accounts.sql has been run and you have signed in as owner, and
--   2. EVERY phone runs the new app (update prompt accepted, or closed and
--      reopened) and shows no "unsent" badge. A phone still on the old app
--      cannot send anything once this runs.
--
-- After this:
--   • the public key in index.html can no longer read or write anything;
--   • only signed-in members can; owner drawings are owners-only; only owners
--     can permanently delete rows (staff can still clear attendance marks);
--   • the activity log is append-only, readable by owners, and records who
--     really did it — "created_by / updated_by" are stamped by the server;
--   • every change or delete keeps a before-copy (mf_auth.history), so any
--     edit can be traced and undone; locked shifts can be changed by owners only;
--   • old password hashes are wiped;
--   • a guard keeps row-level security ON even if an old migration
--     (004_grants.sql, apply_all.sql) is run again by mistake.
--
-- Undo (emergency only): stage2_unlock.sql
-- ════════════════════════════════════════════════════════════════════════════

do $$
declare n_owner int;
begin
  if to_regclass('mf_auth.members') is null then raise exception 'Run stage1_accounts.sql first.'; end if;
  select count(*) filter (where role = 'owner') into n_owner from mf_auth.members;
  if n_owner = 0 then
    raise exception 'No owner has signed in with the new app yet — locking now would lock everyone out.';
  end if;
end $$;

-- ── 1. row-level security + policies on every table ─────────────────────────
-- One function decides the rules for a table; the lock and the guard (5) both use it.
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
do $$
declare t text;
begin
  for t in select c.relname from pg_class c join pg_namespace n on n.oid = c.relnamespace
            where n.nspname = 'public' and c.relkind in ('r', 'p') loop
    perform mf_auth.lock_table(t);
  end loop;
end $$;

-- ── 2. who did it: stamped by the server, not typed by the phone ────────────
create or replace function mf_auth.stamp_actor() returns trigger
language plpgsql security definer set search_path = '' as $$
declare m mf_auth.members;
begin
  select * into m from mf_auth.members where auth_uid = auth.uid();
  if m.auth_uid is null then return new; end if;     -- SQL Editor / service role: leave as given
  if TG_ARGV[0] = 'log' then
    new.username := m.username;
    if TG_ARGV[1] = 'y' then new.display_name := coalesce(m.display, m.username); end if;
    return new;
  end if;
  if TG_ARGV[0] in ('c', 'cu') then
    new.created_by := case when TG_OP = 'UPDATE' then old.created_by else m.username end;
  end if;
  if TG_ARGV[0] in ('u', 'cu') then new.updated_by := m.username; end if;
  return new;
end $$;
do $$
declare t text; hc boolean; hu boolean; hd boolean;
begin
  for t in
    select c.relname from pg_class c join pg_namespace n on n.oid = c.relnamespace
     where n.nspname = 'public' and c.relkind = 'r'
  loop
    execute format('drop trigger if exists mf_stamp_actor on public.%I', t);
    select bool_or(column_name = 'created_by'), bool_or(column_name = 'updated_by'), bool_or(column_name = 'display_name')
      into hc, hu, hd from information_schema.columns where table_schema = 'public' and table_name = t;
    if t = 'activity_log' then
      if exists (select 1 from information_schema.columns where table_schema = 'public' and table_name = t and column_name = 'username') then
        execute format('create trigger mf_stamp_actor before insert on public.%I for each row execute function mf_auth.stamp_actor(%L, %L)',
                       t, 'log', case when hd then 'y' else 'n' end);
      end if;
    elsif hc or hu then
      execute format('create trigger mf_stamp_actor before insert or update on public.%I for each row execute function mf_auth.stamp_actor(%L)',
                     t, case when hc and hu then 'cu' when hc then 'c' else 'u' end);
    end if;
  end loop;
end $$;

-- ── 2b. history: a before-copy of every change and delete ──────────────────
create table if not exists mf_auth.history(
  id      bigserial primary key,
  at      timestamptz not null default now(),
  tbl     text not null,
  row_id  text,
  op      text not null,            -- update | soft-delete | restore | delete
  actor   text,                     -- member username, or sql-editor
  old_row jsonb,
  new_row jsonb
);
create index if not exists history_row_idx on mf_auth.history (tbl, row_id, at desc);
create or replace function mf_auth.keep_history() returns trigger
language plpgsql security definer set search_path = '' as $$
declare o jsonb := to_jsonb(old); n jsonb; who text; op text;
begin
  if TG_OP = 'UPDATE' then
    n := to_jsonb(new);
    -- a re-upload of the same row (sync) is not a change
    if (o - 'updated_at' - 'updated_by') = (n - 'updated_at' - 'updated_by') then return null; end if;
    op := case when n->>'deleted_at' is not null and o->>'deleted_at' is null then 'soft-delete'
               when n->>'deleted_at' is null and o->>'deleted_at' is not null then 'restore'
               else 'update' end;
  else
    op := 'delete';
  end if;
  select username into who from mf_auth.members where auth_uid = auth.uid();
  insert into mf_auth.history(tbl, row_id, op, actor, old_row, new_row)
  values (TG_TABLE_NAME, coalesce(o->>'id', o->>'customer_name', o->>'user_id'), op,
          coalesce(who, case when auth.uid() is null then 'sql-editor' else 'unknown' end), o, n);
  return null;
end $$;

-- Locked records (a locked shift): owners only. A re-upload of the same row
-- is let through so a staff phone syncing does not get stuck.
create or replace function mf_auth.guard_locked() returns trigger
language plpgsql security definer set search_path = '' as $$
declare o jsonb := to_jsonb(old);
begin
  if o->>'locked_at' is null or auth.uid() is null or public.mf_is_owner() then
    return case when TG_OP = 'DELETE' then old else new end;
  end if;
  if TG_OP = 'UPDATE' and (o - 'updated_at' - 'updated_by' - 'created_by')
                        = (to_jsonb(new) - 'updated_at' - 'updated_by' - 'created_by') then
    return new;
  end if;
  raise exception 'permission denied: this record is locked — only an owner can change it';
end $$;

do $$
declare t text;
begin
  for t in select c.relname from pg_class c join pg_namespace n on n.oid = c.relnamespace
            where n.nspname = 'public' and c.relkind = 'r' and c.relname not in ('activity_log', 'users') loop
    execute format('drop trigger if exists mf_history on public.%I', t);
    execute format('create trigger mf_history after update or delete on public.%I for each row execute function mf_auth.keep_history()', t);
    execute format('drop trigger if exists mf_locked on public.%I', t);
    if exists (select 1 from information_schema.columns where table_schema = 'public' and table_name = t and column_name = 'locked_at') then
      execute format('create trigger mf_locked before update or delete on public.%I for each row execute function mf_auth.guard_locked()', t);
    end if;
  end loop;
end $$;

-- Owners can read the history (the app and, later, the assistant use this)
create or replace function public.mf_history(p_table text default null, p_row_id text default null, p_limit int default 100)
returns table(at timestamptz, tbl text, row_id text, op text, actor text, old_row jsonb, new_row jsonb)
language plpgsql stable security definer set search_path = '' as $$
begin
  if not public.mf_is_owner() then raise exception 'owners only'; end if;
  return query select h.at, h.tbl, h.row_id, h.op, h.actor, h.old_row, h.new_row from mf_auth.history h
                where (p_table is null or h.tbl = p_table) and (p_row_id is null or h.row_id = p_row_id)
                order by h.id desc limit least(coalesce(p_limit, 100), 1000);
end $$;
revoke execute on function public.mf_history(text, text, int) from public;
grant execute on function public.mf_history(text, text, int) to authenticated;

-- ── 3. the public key gets nothing but the invite check ─────────────────────
revoke all on all tables    in schema public from anon;
revoke all on all sequences in schema public from anon;
revoke execute on all functions in schema public from anon;
grant execute on function public.mf_invite_check(text, text) to anon;
do $$ begin
  if to_regclass('public.users') is not null then execute 'revoke all on public.users from anon, authenticated'; end if;
end $$;
alter default privileges in schema public revoke all on tables    from anon;
alter default privileges in schema public revoke all on sequences from anon;
alter default privileges in schema public revoke execute on functions from anon;

-- Views, materialised views and foreign tables are not covered by row-level
-- security; the app does not use any. Close them.
do $$
declare r record;
begin
  for r in select c.relname, c.relkind from pg_class c join pg_namespace n on n.oid = c.relnamespace
            where n.nspname = 'public' and c.relkind in ('v', 'm', 'f') loop
    execute format('revoke all on public.%I from anon, authenticated', r.relname);
    raise notice 'Closed % "%" (not used by the app)', case r.relkind when 'v' then 'view' when 'm' then 'materialised view' else 'foreign table' end, r.relname;
  end loop;
end $$;

-- Other SECURITY DEFINER functions in public run with full rights whoever
-- calls them — close them unless they are ours.
do $$
declare r record;
begin
  for r in select p.oid::regprocedure sig from pg_proc p join pg_namespace n on n.oid = p.pronamespace
            where n.nspname = 'public' and p.prosecdef and p.proname not like 'mf\_%' loop
    execute format('revoke execute on function %s from public, anon, authenticated', r.sig);
    raise notice 'Closed security-definer function % (not used by the app)', r.sig;
  end loop;
end $$;

-- ── 4. wipe the old password hashes ─────────────────────────────────────────
do $$
begin
  if exists (select 1 from information_schema.columns
              where table_schema = 'public' and table_name = 'users' and column_name = 'password_hash') then
    begin
      update public.users set password_hash = null;
    exception when not_null_violation then
      update public.users set password_hash = '';
    end;
  end if;
end $$;

-- ── 5. guard: keep row-level security on, for old migrations and new tables ──
create or replace function mf_auth.rls_guard() returns event_trigger
language plpgsql security definer set search_path = '' as $$
declare r record; tname text;
begin
  for r in select * from pg_event_trigger_ddl_commands() where schema_name = 'public' loop
    begin
      if r.object_type = 'table' then
        select relname into tname from pg_class where oid = r.objid and relkind in ('r', 'p') and not relrowsecurity;
        if tname is not null then
          perform mf_auth.lock_table(tname);
          if tname not in ('activity_log', 'users') then
            execute format('drop trigger if exists mf_history on public.%I', tname);
            execute format('create trigger mf_history after update or delete on public.%I for each row execute function mf_auth.keep_history()', tname);
          end if;
          raise notice 'ManiFuels guard: row-level security kept ON for "%" — the database is locked (stage2_lock.sql).', tname;
        end if;
      elsif r.object_type in ('view', 'materialized view') then
        execute format('revoke all on %s from anon, authenticated', r.object_identity);
        raise notice 'ManiFuels guard: new view % closed to the app keys (views bypass row-level security).', r.object_identity;
      end if;
    exception when others then
      -- never block your own change; say loudly that it is not protected
      raise warning 'ManiFuels guard could not secure %: % — run stage2_lock.sql again.', r.object_identity, sqlerrm;
    end;
  end loop;
end $$;
do $$
begin
  drop event trigger if exists mf_rls_guard;
  create event trigger mf_rls_guard on ddl_command_end
    when tag in ('CREATE TABLE', 'ALTER TABLE', 'CREATE TABLE AS', 'SELECT INTO', 'CREATE VIEW', 'CREATE MATERIALIZED VIEW')
    execute function mf_auth.rls_guard();
exception when insufficient_privilege or feature_not_supported then
  raise notice 'Guard not installed on this project (%). Never run 004_grants.sql or apply_all.sql again — they switch the security off.', sqlerrm;
end $$;

-- ── check ───────────────────────────────────────────────────────────────────
-- Every table should say locked = true; then review the member list.
select c.relname as "table", c.relrowsecurity as locked
  from pg_class c join pg_namespace n on n.oid = c.relnamespace
 where n.nspname = 'public' and c.relkind in ('r', 'p') order by 2, 1;
select m.username, m.role, m.created_at::date as joined, u.last_sign_in_at::date as last_sign_in
  from mf_auth.members m join auth.users u on u.id = m.auth_uid order by m.role, m.username;
