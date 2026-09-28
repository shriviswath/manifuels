-- ════════════════════════════════════════════════════════════════════════════
-- ManiFuels — 018_oil_stock_register.sql                           MF_OIL_V1
--
-- 1. oil_invoices.payments (jsonb): dated supplier payments — amount, mode,
--    reference, who, when. amount_paid / amount_due stay as the totals, so the
--    evening report and everything that reads them are unchanged.
-- 2. stock_items.adjustments (jsonb): shelf counts — from, to, difference,
--    reason, note, who, when (last 200 per item).
--
-- The app works without these (both stay on the phone that entered them);
-- with them, every phone sees the same history. Safe to run again.
-- ════════════════════════════════════════════════════════════════════════════

alter table public.oil_invoices add column if not exists payments jsonb;
alter table public.stock_items  add column if not exists adjustments jsonb;
