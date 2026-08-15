-- ManiFuels — 008_one_station.sql
--
-- Every table is filtered on user_id, and the client set user_id to the
-- USERNAME. So each of the four owners had a separate stock list, separate
-- rates, separate opening volumes, separate shifts — four sets of books for
-- one bunk. It showed up plainly in the data: every stock_items row belonged
-- to 'shriviswath', so Kumutha logged in to an empty stock list.
--
-- This re-keys every row to a single station id. Who did what is not lost:
-- created_by / updated_by and the activity log still record the person.
--
-- Pair this with the client release that sets MF_STATION='manifuels'. Applying
-- one without the other hides the data until both are in place.
--
-- TAKE A BACKUP FIRST: Actions → Nightly database backup → Run workflow.

do $$
declare t text;
begin
  -- app_settings and customer_profiles are handled separately: their primary
  -- keys involve user_id, so a blind update can collide.
  foreach t in array array[
    'shift_records','stock_items','ledger_entries','oil_invoices','fuel_loads',
    'pack_register','pack_sizes','staff','staff_attendance','staff_payments',
    'owner_drawings','dip_readings'
  ] loop
    if to_regclass('public.'||t) is null then
      raise notice 'skipping %, not present', t;
      continue;
    end if;
    execute format('update public.%I set user_id = %L where user_id <> %L',
                   t, 'manifuels', 'manifuels');
    execute format('alter table public.%I alter column user_id set default %L',
                   t, 'manifuels');
  end loop;
end $$;

-- app_settings: primary key is user_id, so collapse to one row. Keep the row
-- that actually has opening volumes; if none does, keep any row.
do $$
declare keep text;
begin
  select user_id into keep from public.app_settings
   order by (coalesce(opening_msd,0) + coalesce(opening_hsd,0)) desc,
            updated_at desc nulls last
   limit 1;
  if keep is null then
    insert into public.app_settings (user_id) values ('manifuels')
    on conflict (user_id) do nothing;
  else
    delete from public.app_settings where user_id <> keep;
    update public.app_settings set user_id = 'manifuels' where user_id = keep;
  end if;
  alter table public.app_settings alter column user_id set default 'manifuels';
end $$;

-- customer_profiles is keyed on customer_name alone, so no collision.
update public.customer_profiles set user_id = 'manifuels' where user_id <> 'manifuels';
alter table public.customer_profiles alter column user_id set default 'manifuels';

-- Verify:
--   select distinct user_id from stock_items;      -- one row: manifuels
--   select user_id, opening_msd, opening_hsd, rates from app_settings;  -- one row
