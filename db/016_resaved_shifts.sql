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

-- ── MF_AUDIT_FIX_V1 ─────────────────────────────────────────────────────
-- Until this fix, deleting a shift did NOT undo the credit collected in it.
-- Re-entering that shift applied the same collection a second time, so the
-- customer's balance went down twice. Read-only: lists the likely doubles.

-- 4. Shift collections recorded twice (same customer, date, shift, amount)
select customer, date, note, amount, count(*) as times,
       array_agg(id order by id)        as payment_ids,
       array_agg(ledger_id order by id) as bills_paid
from public.ledger_payments
where deleted_at is null and source = 'shift'
group by customer, date, note, amount
having count(*) > 1
order by date desc;

-- 5. For each customer above, the bills and what the app thinks was paid
-- select id, date, amount, paid_back, notes from public.ledger_entries
--  where customer = 'NAME HERE' and deleted_at is null order by date;
