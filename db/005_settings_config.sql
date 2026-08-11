-- ManiFuels — 005_settings_config.sql
--
-- Pack sizes, tank capacities and the loose-oil source were stored only in
-- each device's localStorage. All three change how a shift is calculated, so
-- two phones with different settings produced different numbers from identical
-- meter readings — silently.
--
-- They now ride in app_settings.config rather than needing three new tables.

alter table public.app_settings
  add column if not exists config jsonb not null default '{}'::jsonb;

-- Shape:
--   {
--     "packSizes":   [{"size":40,"rate":40,"enabled":true}, ...],
--     "tankCfg":     {"capMSD":15000,"capHSD":20000,"tol":0},
--     "looseOilCfg": {"stockId":"502","litresPerUnit":5}
--   }
