-- ════════════════════════════════════════════════════════════════════════════
-- ManiFuels — 017_five_features.sql                                MF_FIVE_V1
--
-- 1. fuel_loads.receipt (jsonb): the tanker delivery check — gauge litres
--    before / after unloading, litres sold while unloading, density measured.
--    The app works without it (the check stays on the phone that entered it);
--    with it, every phone sees the check.
-- 2. The evening report (mf_alert.digest from 015_notifications.sql) gains a
--    tank line: litres now from the latest gauge / dip reading, roughly how
--    many days that lasts at the last 7 days' sales, and water if the gauge
--    showed any. Flags when today's gauge reading has not been entered.
--
-- Run in the Supabase SQL editor AFTER 015_notifications.sql. Safe to run again.
-- ════════════════════════════════════════════════════════════════════════════

alter table public.fuel_loads add column if not exists receipt jsonb;

create or replace function mf_alert.digest(day date) returns json language plpgsql stable as $$
declare
  s mf_alert.settings := mf_alert.cfg();
  t record; w numeric; sales numeric; lines text[] := '{}'; owe record; top text; od record; adv numeric;
  fl record; oil numeric; low text; cost_msd numeric; cost_hsd numeric; title text;
  tk record; dp record; sold numeric; inl numeric; lvl numeric; per_day numeric;   -- MF_FIVE_V1
  tanks text[] := '{}'; stale boolean := false;
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

  -- MF_FIVE_V1: tank stock from the latest ATG / dip reading, days left, water
  for tk in select * from (values ('MSD'), ('HSD')) v(t) loop
    select mf_alert.dt(j->>'date') d,
           case j->>'slot' when 'open' then 0 when 'mid' then 1 else 2 end r,
           mf_alert.num(j->>'observed_l') obs,
           mf_alert.num(substring(j->>'notes' from 'water ([0-9.]+) L')) water
      into dp
      from public.dip_readings x, lateral (select to_jsonb(x) j) q
     where j->>'user_id' = s.station and j->>'deleted_at' is null
       and upper(j->>'type') = tk.t and mf_alert.dt(j->>'date') <= day
     order by 1 desc, 2 desc, j->>'saved_at' desc nulls last limit 1;
    if dp.d is null then continue; end if;
    -- shifts after the reading: morning = 1, night = 2 on the same date
    select coalesce(sum(case when tk.t = 'MSD' then msd_l - test_msd else hsd_l - test_hsd end), 0) into sold
      from mf_alert.shifts()
     where d <= day and (d > dp.d or (d = dp.d and (case when shift = 'night' then 2 else 1 end) > dp.r));
    -- tankers land in the day shift (between 1 and 2)
    select coalesce(sum(mf_alert.num(j->>'vol')), 0) into inl
      from public.fuel_loads x, lateral (select to_jsonb(x) j) q
     where j->>'user_id' = s.station and j->>'deleted_at' is null and upper(j->>'type') = tk.t
       and mf_alert.dt(j->>'date') <= day
       and (mf_alert.dt(j->>'date') > dp.d or (mf_alert.dt(j->>'date') = dp.d and dp.r < 2));
    lvl := dp.obs + inl - sold;
    select coalesce(sum(case when tk.t = 'MSD' then msd_l else hsd_l end), 0) / 7.0 into per_day
      from mf_alert.shifts() where d between day - 7 and day - 1;
    tanks := tanks || (case tk.t when 'MSD' then 'Petrol ' else 'Diesel ' end || mf_alert.lit(lvl) ||
                       case when per_day > 0 then ' ≈' || floor(greatest(lvl, 0) / per_day)::int || ' days' else '' end ||
                       case when dp.water > 0 then ' 💧 water ' || dp.water || ' L' else '' end);
    if dp.d < day then stale := true; end if;
  end loop;
  if coalesce(array_length(tanks, 1), 0) > 0 then
    lines := lines || ('Tanks: ' || array_to_string(tanks, ' · ') ||
                       case when stale then ' — ⚠ today''s gauge reading not entered' else '' end);
  else
    lines := lines || 'Tanks: no gauge reading entered yet'::text;
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
