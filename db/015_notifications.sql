-- ════════════════════════════════════════════════════════════════════════════
-- ManiFuels — phone notifications                   MF_PUSH_V1 + MF_SHIFT_CLOCK_V2
--
-- Push notifications to the installed app on each phone — no third party
-- reads them: the message is encrypted for that phone before it leaves
-- Supabase (standard Web Push). Every 5 minutes the database checks:
--   • a shift saved             → summary; 🔴 cash short / 🟡 over beyond a limit
--   • a shift not saved 1 h after it ended (morning 10 AM, night 7 PM)
--   • a dip outside the tank tolerance
--   • an oil item or pack size dropping to low / out (once per drop)
--   • the day's report each evening (once the night shift is saved, from
--     6 PM; by 9 PM regardless). Yesterday's goes out the next morning if it
--     was never sent.
-- Shifts are dated by the day they CLOSE:
--   MORNING of D = (D-1) 6 PM → D 9 AM,   NIGHT of D = D 9 AM → D 6 PM.
-- Safe to run again (the upgrade from the first version is just a re-run).
-- Owners and managers can get all of these; staff get missed-shift and stock
-- reminders. Each person picks what they want on their phone.
--
-- Requires: security stage 1 + 2 (mf_auth.members), and the edge function
-- `mf-push` deployed FIRST (docs/NOTIFICATIONS_SETUP.md). Safe to run again.
-- ════════════════════════════════════════════════════════════════════════════

create extension if not exists pg_net;
create extension if not exists pg_cron;
create extension if not exists pgcrypto with schema extensions;

do $$ begin
  if to_regclass('mf_auth.members') is null then
    raise exception 'Run the security stages first (stage1_accounts.sql, stage2_lock.sql).';
  end if;
end $$;

create schema if not exists mf_alert;
revoke all on schema mf_alert from public;
do $$ begin execute 'revoke all on schema mf_alert from anon, authenticated';
exception when undefined_object then null; end $$;

-- ── configuration & bookkeeping ─────────────────────────────────────────────
create table if not exists mf_alert.settings(
  id                  int primary key default 1 check (id = 1),
  enabled             boolean not null default true,
  station             text    not null default 'manifuels',
  short_alert         numeric not null default 200,   -- ₹ cash short that is flagged 🔴
  over_alert          numeric not null default 500,   -- ₹ cash over that is flagged 🟡
  digest_from_hour    int     not null default 18,    -- IST, once the day's night shift (9 AM–6 PM) is in
  digest_latest_hour  int     not null default 21,    -- IST, send anyway by this hour
  quiet_from_hour     int     not null default 23,    -- IST: hold notifications from…
  quiet_to_hour       int     not null default 6,     -- …until
  overdue_days        int     not null default 14,
  stock_low_qty       numeric not null default 2,     -- same rule as the app's alert bell
  fn_url              text,                           -- the mf-push edge function
  fn_key              text,                           -- public anon key (the function checks JWTs)
  fn_secret           text    not null default encode(extensions.gen_random_bytes(24), 'hex')
);
-- health: so a broken sender shows up in the app instead of failing silently
alter table mf_alert.settings add column if not exists last_ping_id     bigint;
alter table mf_alert.settings add column if not exists last_ping_status int;
alter table mf_alert.settings add column if not exists last_ping_error  text;
alter table mf_alert.settings add column if not exists last_ping_at     timestamptz;
alter table mf_alert.settings add column if not exists last_sent_at     timestamptz;
insert into mf_alert.settings(id) values (1) on conflict (id) do nothing;
-- MF_SHIFT_CLOCK_V2: the day now closes at 6 PM, so the report moved from the
-- next morning (10 AM / 1 PM) to the same evening. Only the old defaults move.
alter table mf_alert.settings alter column digest_from_hour set default 18, alter column digest_latest_hour set default 21;
update mf_alert.settings set digest_from_hour = 18 where digest_from_hour = 10 and digest_latest_hour = 13;
update mf_alert.settings set digest_latest_hour = 21 where digest_latest_hour = 13;
update mf_alert.settings set
  fn_url = coalesce(fn_url, 'https://hiapuixdmhibimbinlri.supabase.co/functions/v1/mf-push'),
  fn_key = coalesce(fn_key, 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImhpYXB1aXhkbWhpYmltYmlubHJpIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzQwNzk1NDIsImV4cCI6MjA4OTY1NTU0Mn0.4F7tWfrq2J4A426AesIHAEvVqthNja7mUhpTikWSuFc')
 where id = 1;

create table if not exists mf_alert.sent(          -- alerts already raised
  key text primary key, sent_at timestamptz not null default now());
create table if not exists mf_alert.state(         -- last known stock status
  key text primary key, val text, at timestamptz not null default now());
create table if not exists mf_alert.queue(         -- notifications waiting for / sent by mf-push
  id         bigserial primary key,
  at         timestamptz not null default now(),
  cat        text not null,                        -- cash | shift | missed | dip | stock | digest | test
  title      text not null,
  body       text not null,
  page       text,                                 -- app page opened on tap
  tag        text,                                 -- same tag replaces the older notification
  target_uid uuid,                                 -- only this person (test); null = everyone allowed
  picked_at  timestamptz,
  sent_at    timestamptz,
  delivered  int not null default 0,
  failed     int not null default 0              -- -1 = expired unsent (too old to be useful)
);
alter table mf_alert.queue add column if not exists attempts int not null default 0;
create index if not exists queue_unsent_idx on mf_alert.queue (id) where sent_at is null;
create table if not exists mf_alert.push_subs(     -- one row per phone that turned notifications on
  endpoint   text primary key,
  auth_uid   uuid not null references auth.users(id) on delete cascade,
  p256dh     text not null,
  auth       text not null,
  label      text,
  cats       text[] not null default '{}',
  created_at timestamptz not null default now(),
  last_ok    timestamptz,
  fails      int not null default 0
);
create table if not exists mf_alert.vapid(         -- the server's signing key; made by mf-push on first run
  id          int primary key default 1 check (id = 1),
  public_key  text not null,                       -- base64url, 65-byte uncompressed P-256 point
  private_jwk jsonb not null,
  created_at  timestamptz not null default now()
);

-- ── helpers ─────────────────────────────────────────────────────────────────
-- India time. Tests can pin the clock with:  set mf.now = '2026-09-25 19:05';
create or replace function mf_alert.ist() returns timestamp language sql stable as $$
  select coalesce(nullif(current_setting('mf.now', true), '')::timestamp,
                  now() at time zone 'Asia/Kolkata');
$$;
create or replace function mf_alert.num(t text) returns numeric language sql immutable as $$
  select case when t ~ '^\s*[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?\s*$' then t::numeric else 0 end;
$$;
create or replace function mf_alert.dt(t text) returns date language sql immutable as $$
  select case when left(t, 10) ~ '^\d{4}-\d{2}-\d{2}$' then left(t, 10)::date end;
$$;
-- ₹1,23,456 (Indian grouping, whole rupees)
create or replace function mf_alert.inr(n numeric) returns text language plpgsql immutable as $$
declare i text := trunc(abs(round(coalesce(n,0))))::text; head text;
begin
  if length(i) > 3 then
    head := regexp_replace(left(i, length(i) - 3), '(\d)(?=(\d\d)+$)', '\1,', 'g');
    i := head || ',' || right(i, 3);
  end if;
  return case when coalesce(n,0) < -0.5 then '-' else '' end || '₹' || i;
end $$;
create or replace function mf_alert.lit(n numeric) returns text language sql immutable as $$
  select to_char(coalesce(n,0), 'FM999G999G990D0') || ' L';
$$;
create or replace function mf_alert.dshort(d date) returns text language sql immutable as $$
  select to_char(d, 'FMDD Mon');
$$;
create or replace function mf_alert.cfg() returns mf_alert.settings language sql stable as $$
  select * from mf_alert.settings where id = 1;
$$;
-- app_settings.config (tank tolerance, pack minimums …) and rates
create or replace function mf_alert.app() returns jsonb language sql stable as $$
  select coalesce((select to_jsonb(a) from public.app_settings a
                    where a.user_id = (select station from mf_alert.cfg()) limit 1), '{}'::jsonb);
$$;

-- ── normalised views of the app tables (type- and column-tolerant) ─────────
create or replace function mf_alert.shifts()
returns table(id text, d date, shift text, msd_l numeric, hsd_l numeric, test_msd numeric, test_hsd numeric,
              msd_v numeric, hsd_v numeric, other_v numeric, bal numeric, credit numeric, cred_back numeric,
              exp numeric, gpay numeric, paytm numeric, cash numeric, pv numeric, ps numeric,
              extra jsonb, saved_by text)
language sql stable as $$
  select j->>'id', mf_alert.dt(j->>'date'), lower(j->>'shift'),
         mf_alert.num(j->>'msd_t'), mf_alert.num(j->>'hsd_t'),
         mf_alert.num(j->>'test_msd_l'), mf_alert.num(j->>'test_hsd_l'),
         mf_alert.num(j->>'msd_v'), mf_alert.num(j->>'hsd_v'),
         mf_alert.num(j->>'pv') + mf_alert.num(j->>'ov') + mf_alert.num(j->>'st_rev'),
         mf_alert.num(j->>'bal'), mf_alert.num(j->>'credit'), mf_alert.num(j->>'cred_back'),
         mf_alert.num(j->>'exp'), mf_alert.num(j->>'gpay'), mf_alert.num(j->>'paytm'), mf_alert.num(j->>'cash'),
         mf_alert.num(j->>'pv'),
         case when j->'meters' ? 'ps' then mf_alert.num(j->'meters'->>'ps') end,
         coalesce(case when jsonb_typeof(j->'extra_pack_sold') = 'object' then j->'extra_pack_sold' end, '{}'::jsonb),
         coalesce(nullif(j->>'updated_by', ''), nullif(j->>'created_by', ''), '')
    from public.shift_records r, lateral (select to_jsonb(r) j) x
   where j->>'user_id' = (select station from mf_alert.cfg())
     and j->>'deleted_at' is null
     and mf_alert.dt(j->>'date') is not null;
$$;
create or replace function mf_alert.ledger()
returns table(customer text, d date, amount numeric, due numeric) language sql stable as $$
  select j->>'customer', mf_alert.dt(j->>'date'), mf_alert.num(j->>'amount'),
         mf_alert.num(j->>'amount') - mf_alert.num(j->>'paid_back')
    from public.ledger_entries r, lateral (select to_jsonb(r) j) x
   where j->>'user_id' = (select station from mf_alert.cfg()) and j->>'deleted_at' is null;
$$;
create or replace function mf_alert.dips()
returns table(id text, d date, slot text, tank text, variation numeric) language sql stable as $$
  select j->>'id', mf_alert.dt(j->>'date'), j->>'slot', upper(j->>'type'), mf_alert.num(j->>'variation_l')
    from public.dip_readings r, lateral (select to_jsonb(r) j) x
   where j->>'user_id' = (select station from mf_alert.cfg()) and j->>'deleted_at' is null;
$$;
create or replace function mf_alert.stock()
returns table(id text, name text, qty numeric) language sql stable as $$
  select j->>'id', j->>'name', mf_alert.num(j->>'qty')
    from public.stock_items r, lateral (select to_jsonb(r) j) x
   where j->>'user_id' = (select station from mf_alert.cfg()) and j->>'deleted_at' is null;
$$;
-- Pack stock, same arithmetic as the app: received − sold on shifts ± shelf correction
create or replace function mf_alert.packs()
returns table(size int, balance numeric, min numeric) language sql stable as $$
  with a as (select mf_alert.app() j),
  cfg as (select coalesce(j->'config', '{}'::jsonb) c,
                 coalesce(nullif(mf_alert.num(j->'rates'->>'pack'), 0), 40) pack_rate from a),
  sizes as (
    select 40 sz
    union select coalesce(nullif(mf_alert.num(to_jsonb(p)->>'size'), 0), 40)::int
            from public.pack_register p
           where to_jsonb(p)->>'user_id' = (select station from mf_alert.cfg()) and to_jsonb(p)->>'deleted_at' is null
    union select mf_alert.num(e->>'size')::int
            from cfg, jsonb_array_elements(case when jsonb_typeof(c->'packSizes') = 'array' then c->'packSizes' else '[]' end) e
           where coalesce((e->>'enabled')::boolean, false)),
  recv as (
    select coalesce(nullif(mf_alert.num(to_jsonb(p)->>'size'), 0), 40)::int sz, sum(mf_alert.num(to_jsonb(p)->>'qty')) q
      from public.pack_register p
     where to_jsonb(p)->>'user_id' = (select station from mf_alert.cfg()) and to_jsonb(p)->>'deleted_at' is null
     group by 1),
  sold40 as (
    select sum(coalesce(s.ps, greatest(0, round((s.pv - (
             select coalesce(sum(mf_alert.num(e.value) * coalesce((
                      select mf_alert.num(p->>'rate')
                        from jsonb_array_elements(case when jsonb_typeof(c->'packSizes') = 'array' then c->'packSizes' else '[]' end) p
                       where p->>'size' = e.key limit 1), 0)), 0)
               from jsonb_each_text(s.extra) e)) / pack_rate)))) q
      from mf_alert.shifts() s, cfg),
  soldx as (
    select e.key::int sz, sum(mf_alert.num(e.value)) q
      from mf_alert.shifts() s, jsonb_each_text(s.extra) e
     where e.key ~ '^\d+$' group by 1)
  select sizes.sz,
         round(coalesce(recv.q, 0)
               - case when sizes.sz = 40 then coalesce((select q from sold40), 0) else coalesce(soldx.q, 0) end
               + mf_alert.num(cfg.c->'packStockCfg'->'adj'->>sizes.sz::text)),
         coalesce(case when cfg.c->'packStockCfg'->'min' ? sizes.sz::text
                       then mf_alert.num(cfg.c->'packStockCfg'->'min'->>sizes.sz::text) end, 20)
    from sizes cross join cfg
    left join recv  on recv.sz  = sizes.sz
    left join soldx on soldx.sz = sizes.sz;
$$;

-- ── the checks: one row per notification ────────────────────────────────────
-- key: raise-once key (null for stock rows, which use skey/sval instead)
-- title/body null: record silently
drop function if exists mf_alert.collect();
create or replace function mf_alert.collect()
returns table(cat text, key text, title text, body text, page text, skey text, sval text)
language plpgsql stable as $$
declare
  s mf_alert.settings := mf_alert.cfg();
  now_ timestamp := mf_alert.ist();
  app jsonb := mf_alert.app();
  tol numeric := coalesce(case when app->'config'->'tankCfg' ? 'tol' then mf_alert.num(app->'config'->'tankCfg'->>'tol') end, 25);
  r record; sl record; detail text;
begin
  -- 1. Shifts saved in the last 3 days, not yet announced
  for r in select * from mf_alert.shifts() x
            where x.d >= now_::date - 3
              and not exists (select 1 from mf_alert.sent where sent.key = 'shift:' || x.id)
            order by x.d, case x.shift when 'night' then 2 else 1 end loop
    detail := 'MSD ' || mf_alert.lit(r.msd_l) || ' · HSD ' || mf_alert.lit(r.hsd_l) ||
              ' · Sales ' || mf_alert.inr(r.msd_v + r.hsd_v + r.other_v) ||
              case when r.credit > 0 then ' · Credit ' || mf_alert.inr(r.credit) else '' end ||
              case when r.saved_by <> '' then ' · by ' || r.saved_by else '' end;
    key := 'shift:' || r.id; page := 'history'; skey := null; sval := null;
    if r.bal < -greatest(s.short_alert, 1) then
      cat := 'cash'; title := '🔴 Cash short ' || mf_alert.inr(-r.bal) || ' — ' || initcap(r.shift) || ' ' || mf_alert.dshort(r.d);
      body := detail;
    elsif r.bal > greatest(s.over_alert, 1) then
      cat := 'cash'; title := '🟡 Cash over ' || mf_alert.inr(r.bal) || ' — ' || initcap(r.shift) || ' ' || mf_alert.dshort(r.d);
      body := detail;
    else
      cat := 'shift'; title := '✅ ' || initcap(r.shift) || ' ' || mf_alert.dshort(r.d) || ' saved';
      body := detail || ' · Cash ' || case when r.bal < -0.5 then 'short ' || mf_alert.inr(-r.bal)
                                          when r.bal > 0.5 then 'over ' || mf_alert.inr(r.bal) else 'balanced' end;
    end if;
    return next;
  end loop;

  -- 2. Shifts not saved 1 h after they ended (last 30 h). A shift is dated by
  --    the day it closes: MORNING of D ends D 09:00, NIGHT of D ends D 18:00.
  for sl in
    select g.d, g.sh,
           case g.sh when 'morning' then g.d + time '09:00' else g.d + time '18:00' end as ends
      from generate_series(now_::date - 2, now_::date, interval '1 day') gd(dd),
           lateral (select gd.dd::date d) dd, lateral (values (dd.d, 'morning'), (dd.d, 'night')) g(d, sh)
  loop
    if sl.ends + interval '1 hour' <= now_ and sl.ends > now_ - interval '30 hours'
       and not exists (select 1 from mf_alert.shifts() x where x.d = sl.d and x.shift = sl.sh) then
      cat := 'missed'; key := 'missed:' || sl.d || ':' || sl.sh; page := 'entry'; skey := null; sval := null;
      title := '⏰ ' || initcap(sl.sh) || ' shift of ' || mf_alert.dshort(sl.d) || ' not saved';
      body := 'It ended ' || to_char(sl.ends, 'FMHH12:MI AM') ||
              case when sl.ends::date = now_::date then ' today' else ' on ' || mf_alert.dshort(sl.ends::date) end ||
              '. Tap to enter it.';
      return next;
    end if;
  end loop;

  -- 3. Dip readings outside tolerance (last 3 days)
  for r in select * from mf_alert.dips() x
            where x.d >= now_::date - 3 and abs(x.variation) > tol
              and not exists (select 1 from mf_alert.sent where sent.key = 'dip:' || x.id) loop
    cat := 'dip'; key := 'dip:' || r.id; page := 'dip'; skey := null; sval := null;
    title := '📏 ' || r.tank || ' dip ' || case when r.variation < 0 then 'short ' else 'excess ' end || mf_alert.lit(abs(r.variation));
    body := 'Against book stock' ||
            coalesce(' (≈' || mf_alert.inr(abs(r.variation) * nullif(mf_alert.num(app->'rates'->>lower(r.tank)), 0)) || ')', '') ||
            ' — ' || mf_alert.dshort(r.d) || ' ' || coalesce(r.slot, '') || '. Tolerance ±' || tol || ' L.';
    return next;
  end loop;

  -- 4. Oil / counter stock: once when an item drops to LOW or OUT
  for r in select x.*, case when x.qty <= 0 then 'OUT' when x.qty <= s.stock_low_qty then 'LOW' else 'OK' end st,
                  (select val from mf_alert.state where state.key = 'stock:' || x.id) prev
             from mf_alert.stock() x loop
    cat := 'stock'; key := null; page := 'stock'; skey := 'stock:' || r.id; sval := r.st;
    if r.st <> 'OK' and coalesce(r.prev, 'OK') <> r.st and not (r.prev = 'OUT' and r.st = 'LOW') then
      title := '📦 ' || r.name || ' — ' || case r.st when 'OUT' then 'out of stock' else r.qty::int || ' left' end;
      body := case r.st when 'OUT' then 'Nothing left on the shelf. Order more.' else 'Running low. Order more.' end;
    else title := null; body := null; end if;
    return next;
  end loop;

  -- 5. Pack oil against its minimum
  for r in select x.*, case when x.balance <= 0 then 'OUT' when x.balance <= x.min then 'LOW' else 'OK' end st,
                  (select val from mf_alert.state where state.key = 'pack:' || x.size) prev
             from mf_alert.packs() x loop
    cat := 'stock'; key := null; page := 'stock'; skey := 'pack:' || r.size; sval := r.st;
    if r.st <> 'OK' and coalesce(r.prev, 'OK') <> r.st and not (r.prev = 'OUT' and r.st = 'LOW') then
      title := '🧴 ' || r.size || ' ml packs — ' || case r.st when 'OUT' then 'out of stock' else r.balance::int || ' left' end;
      body := case when r.balance < 0 then 'The register shows ' || r.balance::int || ' — count the shelf and correct it on the Oil Stock page.'
                   when r.st = 'OUT' then 'None left by the register. Order more.'
                   else 'At or below the minimum of ' || r.min::int || '. Order more.' end;
    else title := null; body := null; end if;
    return next;
  end loop;
end $$;

-- ── the day's report (morning + night shift of one date) ───────────────────
drop function if exists mf_alert.digest(date);
create or replace function mf_alert.digest(day date) returns json language plpgsql stable as $$
declare
  s mf_alert.settings := mf_alert.cfg();
  t record; w numeric; sales numeric; lines text[] := '{}'; owe record; top text; od record; adv numeric;
  fl record; oil numeric; low text; cost_msd numeric; cost_hsd numeric; title text;
begin
  select count(*) n, bool_or(shift = 'morning') has_m, bool_or(shift = 'night') has_n,
         coalesce(sum(msd_l), 0) msd_l, coalesce(sum(hsd_l), 0) hsd_l,
         coalesce(sum(test_msd), 0) tm, coalesce(sum(test_hsd), 0) th,
         coalesce(sum(msd_v), 0) msd_v, coalesce(sum(hsd_v), 0) hsd_v, coalesce(sum(other_v), 0) oth,
         coalesce(sum(cash), 0) cash, coalesce(sum(gpay), 0) gpay, coalesce(sum(paytm), 0) paytm,
         coalesce(sum(credit), 0) credit, coalesce(sum(cred_back), 0) cred_back, coalesce(sum(exp), 0) exp,
         coalesce(sum(bal), 0) bal
    into t from mf_alert.shifts() where d = day;
  sales := t.msd_v + t.hsd_v + t.oth;
  select avg(v) into w from (select sum(msd_v + hsd_v + other_v) v from mf_alert.shifts()
                              where d between day - 7 and day - 1 group by d) q;

  title := '📊 ' || to_char(day, 'FMDy DD Mon') || ' — ' ||
           case when t.n = 0 then 'no shifts saved'
                else 'Sales ' || mf_alert.inr(sales) ||
                     case when w > 0 then ' (' || case when sales >= w then '+' else '' end || round((sales / w - 1) * 100, 1) || '% vs 7-day avg)' else '' end end;
  if not (coalesce(t.has_m, false) and coalesce(t.has_n, false)) then
    lines := lines || ('⚠ Not saved: ' || concat_ws(', ', case when not coalesce(t.has_m, false) then 'morning' end,
                                                      case when not coalesce(t.has_n, false) then 'night' end));
  end if;
  if t.n > 0 then
    lines := lines || ('Petrol ' || mf_alert.lit(t.msd_l) || ' · Diesel ' || mf_alert.lit(t.hsd_l));
    lines := lines || ('Cash ' || mf_alert.inr(t.cash) || ' · GPay ' || mf_alert.inr(t.gpay) || ' · Paytm ' || mf_alert.inr(t.paytm));
    lines := lines || ('Credit given ' || mf_alert.inr(t.credit) || ' · received ' || mf_alert.inr(t.cred_back) || ' · Expenses ' || mf_alert.inr(t.exp));
    lines := lines || ('Cash result: ' || case when t.bal < -0.5 then 'short ' || mf_alert.inr(-t.bal)
                                              when t.bal > 0.5 then 'over ' || mf_alert.inr(t.bal) else 'balanced' end);
    select case when mf_alert.num(to_jsonb(f)->>'vol') > 0 then mf_alert.num(to_jsonb(f)->>'total_cost') / mf_alert.num(to_jsonb(f)->>'vol') end
      into cost_msd from public.fuel_loads f
     where to_jsonb(f)->>'user_id' = s.station and to_jsonb(f)->>'deleted_at' is null
       and upper(to_jsonb(f)->>'type') = 'MSD' and mf_alert.dt(to_jsonb(f)->>'date') <= day
     order by mf_alert.dt(to_jsonb(f)->>'date') desc limit 1;
    select case when mf_alert.num(to_jsonb(f)->>'vol') > 0 then mf_alert.num(to_jsonb(f)->>'total_cost') / mf_alert.num(to_jsonb(f)->>'vol') end
      into cost_hsd from public.fuel_loads f
     where to_jsonb(f)->>'user_id' = s.station and to_jsonb(f)->>'deleted_at' is null
       and upper(to_jsonb(f)->>'type') = 'HSD' and mf_alert.dt(to_jsonb(f)->>'date') <= day
     order by mf_alert.dt(to_jsonb(f)->>'date') desc limit 1;
    if cost_msd is not null and cost_hsd is not null and t.msd_l > 0 and t.hsd_l > 0 then
      lines := lines || ('Fuel margin ≈ ' || mf_alert.inr((t.msd_l - t.tm) * (t.msd_v / t.msd_l - cost_msd) + (t.hsd_l - t.th) * (t.hsd_v / t.hsd_l - cost_hsd)) ||
                         ' (estimate at latest load cost)');
    end if;
  end if;

  -- position now
  select coalesce(sum(due), 0) total, count(*) n into owe
    from (select customer, sum(due) due from mf_alert.ledger() where amount > 0 group by customer having sum(due) > 0.5) q;
  select string_agg(customer || ' ' || mf_alert.inr(due), ', ' order by due desc) into top
    from (select customer, sum(due) due from mf_alert.ledger() where amount > 0 group by customer
           having sum(due) > 0.5 order by 2 desc limit 2) q;
  select coalesce(sum(-due), 0) into adv from mf_alert.ledger() where amount < 0;
  select coalesce(sum(due), 0) total, count(distinct customer) n into od from mf_alert.ledger()
   where amount > 0 and due > 0.5 and d <= mf_alert.ist()::date - s.overdue_days;
  select count(*) n, coalesce(sum(due), 0) due into fl from (
    select case when to_jsonb(f)->>'total_cost' is not null then mf_alert.num(to_jsonb(f)->>'total_cost') else mf_alert.num(to_jsonb(f)->>'amount_due') end
           - mf_alert.num(to_jsonb(f)->>'amount_paid') due
      from public.fuel_loads f
     where to_jsonb(f)->>'user_id' = s.station and to_jsonb(f)->>'deleted_at' is null) q where due > 0.5;
  select coalesce(sum(mf_alert.num(to_jsonb(o)->>'amount_due')), 0) into oil from public.oil_invoices o
   where to_jsonb(o)->>'user_id' = s.station and to_jsonb(o)->>'deleted_at' is null
     and mf_alert.num(to_jsonb(o)->>'amount_due') > 0.5;
  select string_agg(x, ' · ') into low from (
    select name || ' ' || qty::int x from mf_alert.stock() where qty <= s.stock_low_qty
    union all
    select size || ' ml packs ' || greatest(balance, 0)::int from mf_alert.packs() where balance <= min) q;

  lines := lines || ('Customers owe ' || mf_alert.inr(owe.total) || ' (' || owe.n || ')' ||
                     case when top is not null then ' — ' || top else '' end ||
                     case when adv > 0.5 then '; advances held ' || mf_alert.inr(adv) else '' end);
  if od.total > 0.5 then
    lines := lines || ('Overdue ' || s.overdue_days || '+ days: ' || mf_alert.inr(od.total) || ' (' || od.n || ' customer' || case when od.n > 1 then 's' else '' end || ')');
  end if;
  lines := lines || ('You owe suppliers ' || mf_alert.inr(fl.due + oil));
  if low is not null then lines := lines || ('Low stock: ' || low); end if;
  return json_build_object('title', title, 'body', array_to_string(lines, E'\n'));
end $$;

-- ── delivery helpers used by the mf-push edge function ─────────────────────
-- Who may receive what: owners and managers everything; staff reminders only.
create or replace function mf_alert.allowed(p_role text, p_cat text) returns boolean language sql immutable as $$
  select p_cat = 'test' or p_role in ('owner', 'manager') or p_cat in ('missed', 'stock');
$$;
create or replace function mf_alert.cats_for(p_role text) returns text[] language sql immutable as $$
  select array(select c from unnest(array['cash', 'shift', 'missed', 'dip', 'stock', 'digest']) c where mf_alert.allowed(p_role, c));
$$;

-- Ask mf-push to deliver what is waiting
create or replace function mf_alert.ping() returns bigint language plpgsql as $$
declare s mf_alert.settings := mf_alert.cfg();
begin
  if s.fn_url is null then return null; end if;
  -- what did the previous call answer? (kept so the app can show it)
  begin
    update mf_alert.settings st set last_ping_status = r.status_code,
           last_ping_error = case when r.status_code between 200 and 299 then null
                                  else left(coalesce(r.error_msg, r.content::text, 'no answer'), 200) end
      from net._http_response r where st.id = 1 and r.id = s.last_ping_id;
  exception when others then null;                 -- response table shape differs: skip
  end;
  update mf_alert.settings set last_ping_at = now(), last_ping_id = net.http_post(url := s.fn_url,
    headers := jsonb_build_object('Content-Type', 'application/json',
                                  'Authorization', 'Bearer ' || coalesce(s.fn_key, ''),
                                  'x-mf-secret', s.fn_secret),
    body := '{}'::jsonb, timeout_milliseconds := 30000)
   where id = 1;
  return (select last_ping_id from mf_alert.settings where id = 1);
end $$;

-- mf-push claims a batch: each waiting notification × each phone allowed to get it
create or replace function mf_alert.claim(p_limit int default 20)
returns table(queue_id bigint, cat text, title text, body text, page text, tag text,
              endpoint text, p256dh text, auth text)
language plpgsql as $$
declare ids bigint[];
begin
  -- too old to be useful (sending was broken for a while): close, do not send
  update mf_alert.queue set sent_at = now(), failed = -1
   where sent_at is null and at < now() - interval '12 hours';
  select array_agg(q.id) into ids from (
    select q.id from mf_alert.queue q
     where q.sent_at is null and (q.picked_at is null or q.picked_at < now() - interval '5 minutes')
     order by q.id limit p_limit for update skip locked) q;
  if ids is null then return; end if;
  update mf_alert.queue set picked_at = now(), attempts = attempts + 1 where id = any(ids);
  return query
    select q.id, q.cat, q.title, q.body, q.page, q.tag, s.endpoint, s.p256dh, s.auth
      from mf_alert.queue q
      join mf_alert.push_subs s on (q.target_uid is null or s.auth_uid = q.target_uid)
      join mf_auth.members m on m.auth_uid = s.auth_uid
     where q.id = any(ids)
       and mf_alert.allowed(m.role, q.cat)
       and (q.cat = 'test' or q.cat = any(s.cats))
     order by q.id;
  -- notifications nobody is subscribed to are done now
  update mf_alert.queue q set sent_at = now()
   where q.id = any(ids) and not exists (
     select 1 from mf_alert.push_subs s join mf_auth.members m on m.auth_uid = s.auth_uid
      where (q.target_uid is null or s.auth_uid = q.target_uid)
        and mf_alert.allowed(m.role, q.cat) and (q.cat = 'test' or q.cat = any(s.cats)));
end $$;

-- mf-push reports back: results = [{queue_id, endpoint, ok, gone}]
create or replace function mf_alert.done(p_results jsonb) returns void language plpgsql as $$
begin
  update mf_alert.push_subs s set last_ok = now(), fails = 0
    from jsonb_to_recordset(p_results) r(queue_id bigint, endpoint text, ok boolean, gone boolean)
   where r.ok and s.endpoint = r.endpoint;
  update mf_alert.push_subs s set fails = s.fails + 1
    from jsonb_to_recordset(p_results) r(queue_id bigint, endpoint text, ok boolean, gone boolean)
   where not r.ok and not coalesce(r.gone, false) and s.endpoint = r.endpoint;
  delete from mf_alert.push_subs s                     -- the phone uninstalled / revoked, or failing for days
   using jsonb_to_recordset(p_results) r(queue_id bigint, endpoint text, ok boolean, gone boolean)
   where s.endpoint = r.endpoint and (coalesce(r.gone, false) or s.fails >= 50);
  update mf_alert.queue q set sent_at = now(),
         delivered = (select count(*) from jsonb_to_recordset(p_results) r(queue_id bigint, endpoint text, ok boolean, gone boolean) where r.queue_id = q.id and r.ok),
         failed    = (select count(*) from jsonb_to_recordset(p_results) r(queue_id bigint, endpoint text, ok boolean, gone boolean) where r.queue_id = q.id and not r.ok)
   where q.id in (select (e->>'queue_id')::bigint from jsonb_array_elements(p_results) e);
  -- nobody got it and the failures were temporary (5xx / 429 / timeout): try again
  -- on the next run, up to 3 attempts. (Partial success is not retried — that
  -- would send it twice to the phones that did get it.)
  update mf_alert.queue q set sent_at = null, picked_at = null
   where q.id in (select (e->>'queue_id')::bigint from jsonb_array_elements(p_results) e)
     and q.delivered = 0 and q.attempts < 3 and q.at > now() - interval '6 hours'
     and exists (select 1 from jsonb_to_recordset(p_results) r(queue_id bigint, endpoint text, ok boolean, gone boolean)
                  where r.queue_id = q.id and not r.ok and not coalesce(r.gone, false));
  if exists (select 1 from jsonb_to_recordset(p_results) r(queue_id bigint, endpoint text, ok boolean, gone boolean) where r.ok) then
    update mf_alert.settings set last_sent_at = now() where id = 1;
  end if;
end $$;

-- ── run: check, queue, ping (every 5 minutes) ──────────────────────────────
drop function if exists mf_alert.run(boolean);
create or replace function mf_alert.run(dry boolean default false) returns json language plpgsql as $$
declare
  s mf_alert.settings := mf_alert.cfg();
  h int := extract(hour from mf_alert.ist());
  today date := mf_alert.ist()::date;
  yday date := today - 1;
  rday date;
  quiet boolean; dg json; n int := 0; out json;
begin
  if not s.enabled and not dry then return json_build_object('status', 'disabled'); end if;
  quiet := case when s.quiet_from_hour > s.quiet_to_hour then h >= s.quiet_from_hour or h < s.quiet_to_hour
                else h >= s.quiet_from_hour and h < s.quiet_to_hour end;
  if quiet and not dry then return json_build_object('status', 'quiet hours'); end if;

  create temp table if not exists _mf_c(cat text, key text, title text, body text, page text, skey text, sval text) on commit drop;
  truncate _mf_c;
  insert into _mf_c select * from mf_alert.collect();
  delete from _mf_c where key is not null and exists (select 1 from mf_alert.sent where sent.key = _mf_c.key);

  -- The day closes at 6 PM with its NIGHT shift (9 AM–6 PM). Today's report goes
  -- once that shift is saved (from digest_from_hour) or by digest_latest_hour
  -- anyway; yesterday's goes the next morning only if it was never sent.
  rday := case when h >= s.digest_from_hour
                and (h >= greatest(s.digest_latest_hour, s.digest_from_hour)
                     or exists (select 1 from mf_alert.shifts() x where x.d = today and x.shift = 'night'))
               then today else yday end;
  if not exists (select 1 from mf_alert.sent where key = 'digest:' || rday)
     and (rday = today or h < s.digest_from_hour) then
    dg := mf_alert.digest(rday);
    insert into _mf_c values ('digest', 'digest:' || rday, dg->>'title', dg->>'body', 'dashboard', null, null);
  end if;

  if dry then
    select coalesce(json_agg(json_build_object('cat', cat, 'title', title, 'body', body)), '[]'::json) into out
      from _mf_c where title is not null;
    return out;
  end if;

  insert into mf_alert.queue(cat, title, body, page, tag)
    select cat, left(title, 120), left(body, 1500), page, coalesce(key, skey) from _mf_c where title is not null;
  get diagnostics n = row_count;
  insert into mf_alert.sent(key) select key from _mf_c where key is not null on conflict do nothing;
  insert into mf_alert.state(key, val, at) select skey, sval, now() from _mf_c where skey is not null
    on conflict (key) do update set val = excluded.val, at = excluded.at;
  delete from mf_alert.queue where sent_at < now() - interval '30 days';

  if exists (select 1 from mf_alert.queue where sent_at is null) then perform mf_alert.ping(); end if;
  return json_build_object('status', 'ok', 'queued', n);
end $$;

-- ── what the app calls (signed-in members only) ────────────────────────────
create or replace function public.mf_push_key() returns text
language sql stable security definer set search_path = '' as $$
  select case when public.mf_is_member() then (select public_key from mf_alert.vapid where id = 1) end;
$$;

create or replace function public.mf_push_subscribe(p_endpoint text, p_p256dh text, p_auth text, p_label text, p_cats text[])
returns json language plpgsql volatile security definer set search_path = '' as $$
declare me mf_auth.members; allowed text[];
begin
  select * into me from mf_auth.members where auth_uid = auth.uid();
  if me.auth_uid is null then raise exception 'not a member'; end if;
  -- only real push services: the server posts to this address
  if p_endpoint !~ '^https://(fcm\.googleapis\.com|android\.googleapis\.com|updates\.push\.services\.mozilla\.com|[a-z0-9.-]+\.push\.apple\.com|[a-z0-9.-]+\.notify\.windows\.com|web\.push\.apple\.com)/' then
    raise exception 'unsupported push service';
  end if;
  -- p256dh: 65-byte P-256 point (starts 0x04 → 'B'); auth: 16 bytes — as base64url
  if coalesce(p_p256dh, '') !~ '^B[A-Za-z0-9_-]{86}$' or coalesce(p_auth, '') !~ '^[A-Za-z0-9_-]{22}$' then
    raise exception 'bad subscription keys';
  end if;
  -- at most 5 phones per person: a new one replaces the one silent the longest
  delete from mf_alert.push_subs where endpoint in (
    select endpoint from mf_alert.push_subs
     where auth_uid = me.auth_uid and endpoint <> p_endpoint
     order by coalesce(last_ok, created_at) desc offset 4);
  allowed := mf_alert.cats_for(me.role);
  insert into mf_alert.push_subs(endpoint, auth_uid, p256dh, auth, label, cats)
  values (p_endpoint, me.auth_uid, p_p256dh, p_auth, left(p_label, 60),
          array(select c from unnest(coalesce(p_cats, allowed)) c where c = any(allowed)))
  on conflict (endpoint) do update
    set auth_uid = excluded.auth_uid, p256dh = excluded.p256dh, auth = excluded.auth,
        label = excluded.label, cats = excluded.cats, fails = 0;
  return public.mf_push_status(p_endpoint);
end $$;

create or replace function public.mf_push_unsubscribe(p_endpoint text) returns void
language sql volatile security definer set search_path = '' as $$
  delete from mf_alert.push_subs where endpoint = p_endpoint and auth_uid = auth.uid();
$$;

create or replace function public.mf_push_status(p_endpoint text) returns json
language plpgsql stable security definer set search_path = '' as $$
declare me mf_auth.members; sub mf_alert.push_subs; s mf_alert.settings := mf_alert.cfg();
begin
  select * into me from mf_auth.members where auth_uid = auth.uid();
  if me.auth_uid is null then raise exception 'not a member'; end if;
  select * into sub from mf_alert.push_subs where endpoint = p_endpoint and auth_uid = me.auth_uid;
  return json_build_object(
    'ready', exists (select 1 from mf_alert.vapid),
    'subscribed', sub.endpoint is not null,
    'cats', coalesce(sub.cats, '{}'::text[]),
    'allowed', mf_alert.cats_for(me.role),
    'phones', (select count(*) from mf_alert.push_subs where auth_uid = me.auth_uid),
    'settings', case when me.role = 'owner' then json_build_object(
        'enabled', s.enabled, 'short_alert', s.short_alert, 'over_alert', s.over_alert,
        'quiet_from_hour', s.quiet_from_hour, 'quiet_to_hour', s.quiet_to_hour,
        'digest_from_hour', s.digest_from_hour, 'overdue_days', s.overdue_days) end,
    'health', case when me.role = 'owner' then json_build_object(
        'last_sent_at', s.last_sent_at, 'last_ping_at', s.last_ping_at,
        'last_ping_status', s.last_ping_status, 'last_ping_error', s.last_ping_error,
        'oldest_unsent_min', (select round(extract(epoch from now() - min(at)) / 60) from mf_alert.queue where sent_at is null),
        'expired_24h', (select count(*) from mf_alert.queue where failed = -1 and at > now() - interval '24 hours')) end);
end $$;

create or replace function public.mf_push_test() returns int
language plpgsql volatile security definer set search_path = '' as $$
declare n int;
begin
  if not public.mf_is_member() then raise exception 'not a member'; end if;
  select count(*) into n from mf_alert.push_subs where auth_uid = auth.uid();
  if n = 0 then return 0; end if;
  if exists (select 1 from mf_alert.queue where target_uid = auth.uid() and cat = 'test' and at > now() - interval '1 minute') then
    return -1;                                       -- one test a minute
  end if;
  insert into mf_alert.queue(cat, title, body, page, tag, target_uid)
  values ('test', '🔔 ManiFuels notifications work', 'This phone will get the alerts you picked.', 'dashboard', 'test', auth.uid());
  perform mf_alert.ping();
  return n;
end $$;

create or replace function public.mf_notify_settings(p jsonb) returns json
language plpgsql volatile security definer set search_path = '' as $$
begin
  if not public.mf_is_owner() then raise exception 'owners only'; end if;
  -- switching back on: what happened while it was off is not news
  if p ? 'enabled' and (p->>'enabled')::boolean and not (select enabled from mf_alert.settings where id = 1) then
    perform mf_alert.seed_all();
  end if;
  -- only keys that are present change; a missing key leaves the setting alone
  update mf_alert.settings set
    enabled          = case when p ? 'enabled'          then (p->>'enabled')::boolean else enabled end,
    short_alert      = case when p ? 'short_alert'      then greatest(0, (p->>'short_alert')::numeric) else short_alert end,
    over_alert       = case when p ? 'over_alert'       then greatest(0, (p->>'over_alert')::numeric) else over_alert end,
    quiet_from_hour  = case when p ? 'quiet_from_hour'  then least(23, greatest(0, (p->>'quiet_from_hour')::int)) else quiet_from_hour end,
    quiet_to_hour    = case when p ? 'quiet_to_hour'    then least(23, greatest(0, (p->>'quiet_to_hour')::int)) else quiet_to_hour end,
    digest_from_hour = case when p ? 'digest_from_hour' then least(23, greatest(0, (p->>'digest_from_hour')::int)) else digest_from_hour end,
    overdue_days     = case when p ? 'overdue_days'     then least(365, greatest(1, (p->>'overdue_days')::int)) else overdue_days end
   where id = 1;
  return (select json_build_object('short_alert', short_alert, 'over_alert', over_alert, 'quiet_from_hour', quiet_from_hour,
                                   'quiet_to_hour', quiet_to_hour, 'digest_from_hour', digest_from_hour, 'enabled', enabled)
            from mf_alert.settings where id = 1);
end $$;

-- ── first install: history is not news ─────────────────────────────────────
create or replace function mf_alert.seed() returns void language plpgsql as $$
begin
  insert into mf_alert.sent(key) select 'shift:' || id from mf_alert.shifts() on conflict do nothing;
  insert into mf_alert.sent(key) select 'dip:' || id from mf_alert.dips() on conflict do nothing;
  insert into mf_alert.state(key, val)
    select 'stock:' || id, case when qty <= 0 then 'OUT' when qty <= (select stock_low_qty from mf_alert.cfg()) then 'LOW' else 'OK' end
      from mf_alert.stock() on conflict (key) do nothing;
  insert into mf_alert.state(key, val)
    select 'pack:' || size, case when balance <= 0 then 'OUT' when balance <= min then 'LOW' else 'OK' end
      from mf_alert.packs() on conflict (key) do nothing;
end $$;
create or replace function mf_alert.seed_all() returns void language plpgsql as $$
begin
  insert into mf_alert.sent(key) select 'shift:' || id from mf_alert.shifts() on conflict do nothing;
  insert into mf_alert.sent(key) select 'dip:' || id from mf_alert.dips() on conflict do nothing;
end $$;
select mf_alert.seed() where not exists (select 1 from mf_alert.sent limit 1);

-- ── permissions ────────────────────────────────────────────────────────────
revoke all on all tables in schema mf_alert from public;
revoke all on all functions in schema mf_alert from public;
revoke execute on function public.mf_push_key(), public.mf_push_subscribe(text, text, text, text, text[]),
  public.mf_push_unsubscribe(text), public.mf_push_status(text), public.mf_push_test(),
  public.mf_notify_settings(jsonb) from public;
grant execute on function public.mf_push_key(), public.mf_push_subscribe(text, text, text, text, text[]),
  public.mf_push_unsubscribe(text), public.mf_push_status(text), public.mf_push_test(),
  public.mf_notify_settings(jsonb) to authenticated;
do $$ begin
  execute 'revoke all on all functions in schema mf_alert from anon, authenticated';
  execute 'revoke all on all tables in schema mf_alert from anon, authenticated';
exception when undefined_object then null; end $$;

-- every 5 minutes; and wake mf-push once now so it creates its key
select cron.schedule('mf-notifications', '*/5 * * * *', $cron$select mf_alert.run(false)$cron$);
select mf_alert.ping();

-- Check: what would go out right now (nothing is sent by this line)
select mf_alert.run(true) as preview;
