-- ManiFuels — 012_billing.sql
--
-- Bill-to block for customer invoicing: registered name, GSTIN, address,
-- phone, email. One jsonb column rather than five, because it is printed as a
-- block and never queried field by field.

alter table public.customer_profiles
  add column if not exists billing jsonb not null default '{}'::jsonb;
