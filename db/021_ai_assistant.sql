-- ════════════════════════════════════════════════════════════════════════════
-- ManiFuels — the assistant's server side                              MF_AI_V1
--
-- The assistant in the app answers from the figures the app itself works out
-- on the phone. This file adds only the door in front of the language model:
--   • who may use it      — owners, and managers unless the owner turns that off
--   • how much            — per person and for the station, per minute and per day
--   • a usage log         — who asked, when, how many tokens. NOT what was asked:
--                           no question, answer or business figure is stored here.
--
-- Nothing in your business tables is touched or read by this file.
--
-- Requires: security stage 1 + 2 (mf_auth.members), and the edge function
-- `mf-ai` deployed with its GROQ_API_KEY secret (docs/AI_ASSISTANT_SETUP.md).
-- Run once in Supabase → SQL Editor. Safe to run again.
-- ════════════════════════════════════════════════════════════════════════════

do $$ begin
  if to_regclass('mf_auth.members') is null then
    raise exception 'Run the security stages first (stage1_accounts.sql, stage2_lock.sql).';
  end if;
end $$;

create schema if not exists mf_ai;
revoke all on schema mf_ai from public;
do $$ begin execute 'revoke all on schema mf_ai from anon, authenticated';
exception when undefined_object then null; end $$;

-- ── settings: one row ───────────────────────────────────────────────────────
create table if not exists mf_ai.settings(
  id              int primary key default 1 check (id = 1),
  enabled         boolean not null default true,    -- the switch for everyone
  allow_managers  boolean not null default true,    -- false = owners only
  per_minute      int     not null default 12,      -- model calls per person per minute
  per_user_day    int     not null default 250,     -- model calls per person per day (IST)
  station_day     int     not null default 800      -- model calls for the station per day (IST)
);
insert into mf_ai.settings(id) values (1) on conflict (id) do nothing;

-- ── usage: one row per model call. Counts only — no text. ───────────────────
create table if not exists mf_ai.usage(
  id         bigint generated always as identity primary key,
  at         timestamptz not null default now(),
  auth_uid   uuid not null,
  username   text not null,
  role       text not null,
  status     int,            -- 200 answered · 429 provider busy · 5xx failed · null = no reply recorded
  model      text,
  tok_in     int not null default 0,
  tok_out    int not null default 0,
  tok_cached int not null default 0
);
create index if not exists mf_ai_usage_at  on mf_ai.usage(at);
create index if not exists mf_ai_usage_who on mf_ai.usage(auth_uid, at);

alter table mf_ai.settings enable row level security;   -- no policies: reached only
alter table mf_ai.usage    enable row level security;   -- through the functions below

-- Start of today, India time (the station's day)
create or replace function mf_ai.day_start() returns timestamptz
language sql stable set search_path = '' as $$
  select date_trunc('day', now() at time zone 'Asia/Kolkata') at time zone 'Asia/Kolkata';
$$;

-- ── the gate: called by the mf-ai function before every model call ──────────
-- Runs as the signed-in person. Returns {ok:true, id, left_today} and records
-- the call, or {ok:false, error} and records nothing.
create or replace function public.mf_ai_gate() returns json
language plpgsql volatile security definer set search_path = '' as $$
declare
  me mf_auth.members; s mf_ai.settings; d0 timestamptz := mf_ai.day_start();
  n_min int; n_day int; n_all int; rid bigint; wait_s int;
begin
  select * into me from mf_auth.members where auth_uid = auth.uid();
  if me.auth_uid is null then return json_build_object('ok', false, 'error', 'not_member'); end if;
  select * into s from mf_ai.settings where id = 1;
  if not s.enabled then return json_build_object('ok', false, 'error', 'disabled'); end if;
  if me.role = 'owner' or (me.role = 'manager' and s.allow_managers) then null;
  else return json_build_object('ok', false, 'error', 'role'); end if;

  -- One person's count at a time, so two phones cannot both take the last slot
  perform pg_advisory_xact_lock(hashtext('mf_ai:' || me.auth_uid::text));
  select count(*) filter (where at > now() - interval '1 minute'), count(*)
    into n_min, n_day from mf_ai.usage where auth_uid = me.auth_uid and at >= d0;
  if n_min >= s.per_minute then
    select greatest(1, ceil(60 - extract(epoch from now() - min(at))))::int into wait_s
      from mf_ai.usage where auth_uid = me.auth_uid and at > now() - interval '1 minute';
    return json_build_object('ok', false, 'error', 'limit_minute', 'retry_after', coalesce(wait_s, 30));
  end if;
  if n_day >= s.per_user_day then
    return json_build_object('ok', false, 'error', 'limit_user_day',
      'retry_after', ceil(extract(epoch from d0 + interval '1 day' - now()))::int);
  end if;
  select count(*) into n_all from mf_ai.usage where at >= d0;
  if n_all >= s.station_day then
    return json_build_object('ok', false, 'error', 'limit_station_day',
      'retry_after', ceil(extract(epoch from d0 + interval '1 day' - now()))::int);
  end if;

  insert into mf_ai.usage(auth_uid, username, role) values (me.auth_uid, me.username, me.role)
    returning id into rid;
  if rid % 200 = 0 then delete from mf_ai.usage where at < now() - interval '120 days'; end if;
  return json_build_object('ok', true, 'id', rid, 'role', me.role, 'username', me.username,
    'left_today', least(s.per_user_day - n_day, s.station_day - n_all) - 1);
end $$;

-- The mf-ai function reports how the call ended. A person can only complete
-- their own row, and only once.
create or replace function public.mf_ai_done(p_id bigint, p_status int, p_model text, p_in int, p_out int, p_cached int)
returns void language sql volatile security definer set search_path = '' as $$
  update mf_ai.usage
     set status = p_status, model = left(p_model, 80),
         tok_in = greatest(0, coalesce(p_in, 0)), tok_out = greatest(0, coalesce(p_out, 0)),
         tok_cached = greatest(0, coalesce(p_cached, 0))
   where id = p_id and auth_uid = auth.uid() and status is null;
$$;

-- What the app shows in the assistant's settings sheet
create or replace function public.mf_ai_status() returns json
language plpgsql stable security definer set search_path = '' as $$
declare me mf_auth.members; s mf_ai.settings; d0 timestamptz := mf_ai.day_start();
begin
  select * into me from mf_auth.members where auth_uid = auth.uid();
  if me.auth_uid is null then raise exception 'not a member'; end if;
  select * into s from mf_ai.settings where id = 1;
  return json_build_object(
    'enabled', s.enabled,
    'allowed', s.enabled and (me.role = 'owner' or (me.role = 'manager' and s.allow_managers)),
    'role', me.role,
    'used_today', (select count(*) from mf_ai.usage where auth_uid = me.auth_uid and at >= d0),
    'per_user_day', s.per_user_day,
    'station_today', (select count(*) from mf_ai.usage where at >= d0),
    'station_day', s.station_day,
    -- owners also see the switches and who used it
    'settings', case when me.role = 'owner' then json_build_object(
        'enabled', s.enabled, 'allow_managers', s.allow_managers, 'per_minute', s.per_minute,
        'per_user_day', s.per_user_day, 'station_day', s.station_day) end,
    'people', case when me.role = 'owner' then (
        select coalesce(json_agg(json_build_object('username', u.username, 'role', u.role, 'today', u.today, 'week', u.week)
                                 order by u.week desc), '[]'::json)
          from (select username, max(role) as role,
                       count(*) filter (where at >= d0) as today, count(*) as week
                  from mf_ai.usage where at >= d0 - interval '6 days' group by username) u) end,
    'last_error', case when me.role = 'owner' then (
        select json_build_object('at', at, 'status', status) from mf_ai.usage
         where status is not null and status <> 200 and at > now() - interval '24 hours'
         order by at desc limit 1) end);
end $$;

-- Owner switches. Only keys that are present change.
create or replace function public.mf_ai_settings(p jsonb) returns json
language plpgsql volatile security definer set search_path = '' as $$
begin
  if not public.mf_is_owner() then raise exception 'owners only'; end if;
  update mf_ai.settings set
    enabled        = case when p ? 'enabled'        then (p->>'enabled')::boolean        else enabled end,
    allow_managers = case when p ? 'allow_managers' then (p->>'allow_managers')::boolean else allow_managers end,
    per_minute     = case when p ? 'per_minute'     then least(60,   greatest(1, (p->>'per_minute')::int))    else per_minute end,
    per_user_day   = case when p ? 'per_user_day'   then least(2000, greatest(1, (p->>'per_user_day')::int))  else per_user_day end,
    station_day    = case when p ? 'station_day'    then least(5000, greatest(1, (p->>'station_day')::int))   else station_day end
   where id = 1;
  return public.mf_ai_status();
end $$;

-- ── permissions ─────────────────────────────────────────────────────────────
revoke all on all tables in schema mf_ai from public;
revoke all on all functions in schema mf_ai from public;
revoke execute on function public.mf_ai_gate(), public.mf_ai_done(bigint, int, text, int, int, int),
  public.mf_ai_status(), public.mf_ai_settings(jsonb) from public;
grant execute on function public.mf_ai_gate(), public.mf_ai_done(bigint, int, text, int, int, int),
  public.mf_ai_status(), public.mf_ai_settings(jsonb) to authenticated;
do $$ begin
  execute 'revoke execute on function public.mf_ai_gate(), public.mf_ai_done(bigint, int, text, int, int, int), public.mf_ai_status(), public.mf_ai_settings(jsonb) from anon';
  execute 'revoke all on all functions in schema mf_ai from anon, authenticated';
  execute 'revoke all on all tables in schema mf_ai from anon, authenticated';
exception when undefined_object then null; end $$;

-- Check: the switches as they stand, and nobody has used it yet
select enabled, allow_managers, per_minute, per_user_day, station_day,
       (select count(*) from mf_ai.usage) as calls_logged
  from mf_ai.settings;

-- ── useful afterwards ───────────────────────────────────────────────────────
-- Who used it this week:
--   select username, count(*) calls, sum(tok_in) tok_in, sum(tok_out) tok_out
--     from mf_ai.usage where at > now() - interval '7 days' group by 1 order by 2 desc;
-- Switch it off for everyone:   update mf_ai.settings set enabled = false;
-- Owners only:                  update mf_ai.settings set allow_managers = false;
