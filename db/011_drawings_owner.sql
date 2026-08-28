-- ManiFuels — 011_drawings_owner.sql
--
-- A drawing recorded who ENTERED it (created_by) but not who TOOK the money.
-- With four owners on one account that is the only question the page is
-- actually asked, so it gets its own column rather than being buried in the
-- purpose text.

alter table public.owner_drawings
  add column if not exists owner      text default '',
  add column if not exists updated_at timestamptz default now();

update public.owner_drawings set updated_at = now() where updated_at is null;
