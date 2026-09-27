-- 016_resaved_shifts.sql — MF_RESAVE_UNDELETE_V1
-- Shifts saved again after being deleted were left with deleted_at set, so the
-- app hid them. Steps 1–2 only read. Step 3 is optional: the patched app
-- already treats these rows as live. Step 3 just makes the database agree.

-- 1. What the database holds for 25 Sep
select id, shift, saved_at, deleted_at,
       right_total, left_total, exp, credit, bal
from public.shift_records
where date = '2026-09-25'
order by id;

-- 2. Every shift hit by the bug: saved again AFTER it was deleted
select id, date, shift, saved_at, deleted_at
from public.shift_records
where deleted_at is not null
  and saved_at > deleted_at
order by date desc;

-- 3. (optional) Mark them live again
-- update public.shift_records
--    set deleted_at = null
--  where deleted_at is not null
--    and saved_at > deleted_at;
