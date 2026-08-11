-- ManiFuels — 006_staff_salary_history.sql
--
-- Staff details are now editable in place: phone numbers change, people get
-- promoted, salaries go up. Editing the row keeps attendance and payment
-- history attached to the same person instead of creating a second record.
--
-- A raise is a dated event, not just a new number — without the date, an old
-- payslip cannot be explained. Each revision is stored as
--   { "date": "2026-08-11", "from": 14000, "to": 16000, "by": "kalimuthu" }

alter table public.staff
  add column if not exists salary_history jsonb not null default '[]'::jsonb;
