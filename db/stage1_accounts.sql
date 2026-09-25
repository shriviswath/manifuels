-- ════════════════════════════════════════════════════════════════════════════
-- ManiFuels — SECURITY STAGE 1: real accounts                     MF_AUTH_V2
--
-- Adds proper sign-in (Supabase Auth). Changes NOTHING in your data and locks
-- nothing yet — the current app keeps working until stage 2.
--
--   • mf_auth.members — who belongs to the station, and their role. Roles live
--                       on the server now, not in the browser.
--   • mf_auth.invites — a one-time pass to create an account. Only the owner
--                       can issue one; old passwords are NOT carried over
--                       (they were published inside the old app).
--   • functions the app calls to sign in, and owner tools to add / reset /
--     remove people from inside the app.
--
-- Run once in Supabase → SQL Editor. Safe to run again. Then:
--   1. Authentication → Sign In / Providers → Email → turn OFF "Confirm email".
--   2. Create YOUR invite (pick your own one-time code, 8+ characters):
--        select mf_auth.bootstrap_owner('shriviswath', 'Shri Viswath C K', 'your-one-time-code');
--      Sign in to the new app with username + that code; it makes you choose a
--      password. Invite everyone else from the Members panel.
-- ════════════════════════════════════════════════════════════════════════════

create extension if not exists pgcrypto with schema extensions;

create schema if not exists mf_auth;
revoke all on schema mf_auth from public;
do $$ begin execute 'revoke all on schema mf_auth from anon, authenticated';
exception when undefined_object then null; end $$;

create table if not exists mf_auth.members(
  auth_uid    uuid primary key references auth.users(id) on delete cascade,
  username    text not null unique check (username ~ '^[a-z0-9._-]{3,32}$'),
  display     text,
  role        text not null default 'staff' check (role in ('owner', 'manager', 'staff')),
  must_change boolean not null default false,   -- owner gave a temporary password
  created_at  timestamptz not null default now()
);
create table if not exists mf_auth.invites(
  username   text primary key check (username ~ '^[a-z0-9._-]{3,32}$'),
  display    text,
  role       text not null default 'staff' check (role in ('owner', 'manager', 'staff')),
  pw_hash    text not null,              -- bcrypt of the one-time password
  source     text not null default 'owner',   -- owner (Members panel) | bootstrap (SQL Editor)
  tries      int  not null default 0,         -- wrong passwords; locked at 10
  created_at timestamptz not null default now(),
  created_by text
);

-- Stage 1 v1 seeded invites from the old passwords. Those passwords were
-- published inside the old app, so anyone could have claimed an owner account
-- with them. Remove any such invite if an earlier version was run.
delete from mf_auth.invites where source = 'legacy';

-- ── helpers ────────────────────────────────────────────────────────────────
create or replace function mf_auth.email_of(u text) returns text language sql immutable as $$
  select lower(u) || '@manifuels.vercel.app';
$$;
create or replace function mf_auth.pw_ok(p text, h text) returns boolean
language sql stable set search_path = '' as $$
  select h like '$2%' and extensions.crypt(p, h) = h;      -- bcrypt only
$$;
create or replace function mf_auth.me() returns mf_auth.members
language sql stable security definer set search_path = '' as $$
  select * from mf_auth.members where auth_uid = auth.uid();
$$;

-- Used by the row-level security policies in stage 2
create or replace function public.mf_is_member() returns boolean
language sql stable security definer set search_path = '' as $$
  select exists (select 1 from mf_auth.members where auth_uid = auth.uid());
$$;
create or replace function public.mf_is_owner() returns boolean
language sql stable security definer set search_path = '' as $$
  select exists (select 1 from mf_auth.members where auth_uid = auth.uid() and role = 'owner');
$$;

-- Who am I (the app calls this after every sign-in)
create or replace function public.mf_whoami() returns json
language sql stable security definer set search_path = '' as $$
  select json_build_object('username', username, 'display', display, 'role', role, 'must_change', must_change)
    from mf_auth.members where auth_uid = auth.uid();
$$;

-- Before an account exists: is this username + one-time password a valid invite?
drop function if exists public.mf_legacy_check(text, text);
create or replace function public.mf_invite_check(p_username text, p_password text) returns json
language plpgsql volatile security definer set search_path = '' as $$
declare i mf_auth.invites; u text := lower(trim(p_username));
begin
  select * into i from mf_auth.invites where username = u for update;
  if not found then return json_build_object('ok', false); end if;
  if i.tries >= 10 then return json_build_object('ok', false, 'locked', true); end if;
  if mf_auth.pw_ok(p_password, i.pw_hash) then
    return json_build_object('ok', true, 'display', i.display, 'role', i.role);
  end if;
  update mf_auth.invites set tries = tries + 1 where username = u;
  return json_build_object('ok', false);
end $$;

-- After signUp: turn the invite into membership for the signed-in account
create or replace function public.mf_claim_member(p_username text, p_invite_password text) returns json
language plpgsql volatile security definer set search_path = '' as $$
declare i mf_auth.invites; u text := lower(trim(p_username)); em text;
begin
  if auth.uid() is null then raise exception 'not signed in'; end if;
  if exists (select 1 from mf_auth.members where auth_uid = auth.uid()) then
    return public.mf_whoami();
  end if;
  select email into em from auth.users where id = auth.uid();
  if lower(em) is distinct from mf_auth.email_of(u) then raise exception 'account does not match username'; end if;
  select * into i from mf_auth.invites where username = u for update;
  if not found then raise exception 'no invite for %', u; end if;
  if i.tries >= 10 then raise exception 'invite locked after too many wrong passwords — ask the owner'; end if;
  -- An account registered before the invite existed was made by someone else
  -- (a squatter). Refuse; the owner's re-invite deletes it.
  if (select created_at from auth.users where id = auth.uid()) < i.created_at then
    raise exception 'this account was created before your invite — ask the owner to invite you again';
  end if;
  if not mf_auth.pw_ok(p_invite_password, i.pw_hash) then
    update mf_auth.invites set tries = tries + 1 where username = u;   -- returned, not raised, so the count sticks
    return json_build_object('error', 'wrong invite password');
  end if;
  insert into mf_auth.members(auth_uid, username, display, role, must_change)
  values (auth.uid(), u, i.display, i.role, false);
  delete from mf_auth.invites where username = u;
  return public.mf_whoami();
end $$;

create or replace function public.mf_password_changed() returns void
language sql volatile security definer set search_path = '' as $$
  update mf_auth.members set must_change = false where auth_uid = auth.uid();
$$;

-- ── owner tools (the app's Members panel) ─────────────────────────────────
create or replace function public.mf_members()
returns table(username text, display text, role text, status text, last_sign_in timestamptz)
language plpgsql stable security definer set search_path = '' as $$
begin
  if not public.mf_is_owner() then raise exception 'owners only'; end if;
  return query
    select m.username, m.display, m.role,
           case when m.must_change then 'temporary password' else 'active' end, u.last_sign_in_at
      from mf_auth.members m join auth.users u on u.id = m.auth_uid
    union all
    select i.username, i.display, i.role,
           case when i.tries >= 10 then 'invite locked' else 'invited' end, null::timestamptz
      from mf_auth.invites i
    order by 1;
end $$;

-- Add someone, or reset their password. The temporary password must be
-- changed by them at their next sign-in.
create or replace function public.mf_set_member(p_username text, p_display text, p_role text, p_temp_password text)
returns text language plpgsql volatile security definer set search_path = '' as $$
declare u text := lower(trim(p_username)); au uuid; me mf_auth.members := mf_auth.me();
begin
  if me.auth_uid is null or me.role <> 'owner' then raise exception 'owners only'; end if;
  if u !~ '^[a-z0-9._-]{3,32}$' then raise exception 'username: 3–32 letters, digits, dot, dash or underscore'; end if;
  if p_role not in ('owner', 'manager', 'staff') then raise exception 'role must be owner, manager or staff'; end if;
  if p_temp_password is not null and length(p_temp_password) < 6 then raise exception 'temporary password: at least 6 characters'; end if;
  if u = me.username and p_role <> 'owner'
     and (select count(*) from mf_auth.members where role = 'owner') <= 1 then
    raise exception 'you are the only owner — make someone else owner first';
  end if;

  select id into au from auth.users where lower(email) = mf_auth.email_of(u);
  if au is not null and not exists (select 1 from mf_auth.members where auth_uid = au) then
    -- An account with this name but no membership: a removed person, or someone
    -- who registered the name first. Either way it is not trusted — delete it
    -- (this also ends its sessions) and fall through to a fresh invite.
    if p_temp_password is null then raise exception 'give a temporary password to re-add %', u; end if;
    delete from auth.users where id = au;
    au := null;
  end if;
  if au is not null then
    -- existing member: role / name change, and optionally a password reset
    update mf_auth.members
       set display = coalesce(nullif(trim(p_display), ''), display), role = p_role,
           must_change = must_change or (p_temp_password is not null)
     where auth_uid = au;
    if p_temp_password is not null then
      update auth.users set encrypted_password = extensions.crypt(p_temp_password, extensions.gen_salt('bf'))
       where id = au;
      delete from auth.sessions where user_id = au;      -- signed out on every phone
    end if;
    delete from mf_auth.invites where username = u;
    return case when p_temp_password is not null then 'password reset — ' || u || ' is signed out everywhere and must choose a new password at next sign-in'
                else 'updated ' || u end;
  end if;

  if p_temp_password is null then
    update mf_auth.invites set display = coalesce(nullif(trim(p_display), ''), display), role = p_role where username = u;
    if not found then raise exception 'new person: give a temporary password'; end if;
    return 'updated invite for ' || u;
  end if;
  insert into mf_auth.invites(username, display, role, pw_hash, source, created_by)
  values (u, nullif(trim(p_display), ''), p_role, extensions.crypt(p_temp_password, extensions.gen_salt('bf')), 'owner', me.username)
  on conflict (username) do update
    set display = excluded.display, role = excluded.role, pw_hash = excluded.pw_hash,
        source = 'owner', tries = 0, created_by = excluded.created_by, created_at = now();
  return 'invited ' || u || ' — they sign in with the temporary password and choose their own';
end $$;

create or replace function public.mf_remove_member(p_username text) returns text
language plpgsql volatile security definer set search_path = '' as $$
declare u text := lower(trim(p_username)); me mf_auth.members := mf_auth.me();
begin
  if me.auth_uid is null or me.role <> 'owner' then raise exception 'owners only'; end if;
  if u = me.username then raise exception 'you cannot remove yourself'; end if;
  delete from auth.sessions where user_id = (select auth_uid from mf_auth.members where username = u);
  delete from mf_auth.members where username = u;
  delete from mf_auth.invites where username = u;
  return 'removed ' || u || ' — they lose access immediately';
end $$;

-- ── first owner: only someone in the Supabase SQL Editor can run this ──
create or replace function mf_auth.bootstrap_owner(p_username text, p_display text, p_code text) returns text
language plpgsql volatile set search_path = '' as $$
declare u text := lower(trim(p_username));
begin
  if length(coalesce(p_code, '')) < 8 then raise exception 'one-time code: at least 8 characters'; end if;
  if exists (select 1 from mf_auth.members where username = u) then
    raise exception '% is already a member — reset from the Members panel instead', u;
  end if;
  -- someone may have registered this name first: remove that account
  delete from auth.users au where lower(au.email) = mf_auth.email_of(u)
     and not exists (select 1 from mf_auth.members m where m.auth_uid = au.id);
  insert into mf_auth.invites(username, display, role, pw_hash, source, created_by)
  values (u, p_display, 'owner', extensions.crypt(p_code, extensions.gen_salt('bf')), 'bootstrap', 'sql-editor')
  on conflict (username) do update set display = excluded.display, role = 'owner', pw_hash = excluded.pw_hash,
         source = 'bootstrap', tries = 0, created_at = now();
  return 'Invite ready. In the app: username ' || u || ' + your one-time code, then choose your password.';
end $$;

-- ── who may call what ──────────────────────────────────────────────────────
revoke all on all tables in schema mf_auth from public;
revoke execute on function public.mf_is_member(), public.mf_is_owner(), public.mf_whoami(),
  public.mf_invite_check(text, text), public.mf_claim_member(text, text), public.mf_password_changed(),
  public.mf_members(), public.mf_set_member(text, text, text, text), public.mf_remove_member(text) from public;
grant execute on function public.mf_invite_check(text, text) to anon, authenticated;
grant execute on function public.mf_is_member(), public.mf_is_owner(), public.mf_whoami(),
  public.mf_claim_member(text, text), public.mf_password_changed(), public.mf_members(),
  public.mf_set_member(text, text, text, text), public.mf_remove_member(text) to authenticated;

revoke all on function mf_auth.bootstrap_owner(text, text, text) from public;

-- Check: members and open invites
select 'member' as kind, username, role from mf_auth.members
union all select 'invite', username, role from mf_auth.invites order by 1, 2;
