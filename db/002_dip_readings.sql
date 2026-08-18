-- ManiFuels — 002_dip_readings.sql
-- Physical tank dips. Book stock comes from the same meters the shift entry
-- uses, so it can never disagree with itself. A dip is an independent
-- measurement — the only thing in the system that can catch evaporation,
-- a leaking line, or theft.

create table if not exists public.dip_readings (
  id          bigint primary key,
  user_id     text not null default 'manifuels',   -- station id, not a person (see 008)
  date        date not null,
  slot        text not null,                 -- morning | night | opening | closing
  type        text not null,                 -- MSD | HSD
  dip_cm      numeric,                       -- the stick reading as taken
  observed_l  numeric not null default 0,    -- litres in the tank, from the chart
  book_l      numeric not null default 0,    -- opening + loads − sales − testing
  variation_l numeric not null default 0,    -- observed − book; negative = loss
  notes       text default '',
  created_by  text,
  saved_at    timestamptz default now()
);

create unique index if not exists dip_readings_unique_slot
  on public.dip_readings (user_id, date, slot, type);
create index if not exists dip_readings_date_idx
  on public.dip_readings (user_id, type, date desc);

-- Match the access model of every other table in this schema (see 099 for RLS).
alter table public.dip_readings disable row level security;
grant all on public.dip_readings to anon, authenticated;
