-- ════════════════════════════════════════════════════════════════════════════
-- ManiFuels — 019_fuel_load_payments.sql                        MF_FUELLOAD_V1
--
-- fuel_loads.payments (jsonb): each payment to the fuel supplier — date,
-- amount, mode (RTGS / UPI / cheque …), UTR or cheque number, who entered it.
-- amount_paid stays as the running total, so older app versions keep working.
--
-- The app works without the column: payment dates stay on the phone that
-- entered them and it says so in the console. Run in the Supabase SQL editor.
-- Safe to run again. Needs nothing else.
-- ════════════════════════════════════════════════════════════════════════════

alter table public.fuel_loads add column if not exists payments jsonb;

-- Verify:
--   select column_name, data_type from information_schema.columns
--    where table_schema='public' and table_name='fuel_loads' and column_name in ('payments','receipt');
