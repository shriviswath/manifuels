-- ═══════════════════════════════════════════════════════
--  ManiFuels — Enable Supabase Realtime
--  Run AFTER manifuels_complete_setup.sql
--
--  Enables instant push sync across all devices.
--  Without this, sync works via tab-focus and 60s polling.
-- ═══════════════════════════════════════════════════════

-- ─── Core tables ──────────────────────────────────────
ALTER PUBLICATION supabase_realtime ADD TABLE shift_records;
ALTER PUBLICATION supabase_realtime ADD TABLE stock_items;
ALTER PUBLICATION supabase_realtime ADD TABLE ledger_entries;
ALTER PUBLICATION supabase_realtime ADD TABLE oil_invoices;
ALTER PUBLICATION supabase_realtime ADD TABLE fuel_loads;
ALTER PUBLICATION supabase_realtime ADD TABLE settings;

-- ─── v2.5 tables ──────────────────────────────────────
ALTER PUBLICATION supabase_realtime ADD TABLE users;
ALTER PUBLICATION supabase_realtime ADD TABLE customer_profiles;
ALTER PUBLICATION supabase_realtime ADD TABLE pack_register;
ALTER PUBLICATION supabase_realtime ADD TABLE pack_sizes;
ALTER PUBLICATION supabase_realtime ADD TABLE activity_log;
ALTER PUBLICATION supabase_realtime ADD TABLE rate_history;
ALTER PUBLICATION supabase_realtime ADD TABLE staff;
ALTER PUBLICATION supabase_realtime ADD TABLE staff_attendance;
ALTER PUBLICATION supabase_realtime ADD TABLE staff_payments;
ALTER PUBLICATION supabase_realtime ADD TABLE owner_drawings;

-- ═══════════════════════════════════════════════════════
--  DONE.
--
--  VERIFY realtime is active:
--    SELECT tablename FROM pg_publication_tables
--    WHERE pubname = 'supabase_realtime'
--    ORDER BY tablename;
--
--  You should see all 16 tables listed.
-- ═══════════════════════════════════════════════════════
