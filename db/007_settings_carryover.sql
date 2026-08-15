-- ManiFuels — 007_settings_carryover.sql
--
-- Two settings tables exist. The client uses `app_settings`; `settings` is
-- left over from the original schema. When the app moved across, the opening
-- tank volumes did not come with it:
--
--   settings      opening_msd 3023.91   opening_hsd 6405.2   (03 May 2026)
--   app_settings  opening_msd 0         opening_hsd 0
--
-- Zero openings are why the tank gauges read empty. This copies the volumes
-- across, leaves the rates alone (app_settings has the current ones), and then
-- retires the dead table.
--
-- Run AFTER taking a backup: Actions → Nightly database backup → Run workflow.

-- 1 ── carry the opening volumes over, only where they are still unset
update public.app_settings a
set opening_msd = s.opening_msd,
    opening_hsd = s.opening_hsd,
    updated_at  = now()
from public.settings s
where a.user_id = s.user_id
  and coalesce(a.opening_msd,0) = 0
  and coalesce(a.opening_hsd,0) = 0
  and (coalesce(s.opening_msd,0) <> 0 or coalesce(s.opening_hsd,0) <> 0);

-- 2 ── check before dropping. Expect the real volumes, not zeros.
--   select user_id, rates, opening_msd, opening_hsd from public.app_settings;

-- 3 ── retire the dead table. Uncomment once step 2 looks right.
--   drop table public.settings;
