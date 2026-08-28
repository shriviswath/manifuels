-- ManiFuels — 010_ensure_tables.sql
--
-- The base schema was created by hand in the SQL editor, so which tables exist
-- depends on which version of that script was run. Anything missing fails
-- silently: supabase-js resolves with {error}, the row is parked in the outbox,
-- and the app looks like it saved. This creates whatever is absent, leaves
-- whatever exists untouched, and asserts the access model.
--
-- Idempotent. Never drops or alters existing columns.

create table if not exists public.customer_profiles (
  customer_name  text primary key,
  user_id        text not null default 'manifuels',
  discount_per_l numeric default 0,
  notes          text default '',
  updated_at     timestamptz default now(),
  updated_by     text
);

create table if not exists public.pack_register (
  id         bigint primary key,
  user_id    text not null default 'manifuels',
  size       integer not null default 40,
  date       date not null,
  supplier   text default '',
  qty        numeric default 0,
  cost       numeric default 0,
  total_cost numeric default 0,
  notes      text default '',
  created_by text
);

create table if not exists public.staff (
  id             bigint primary key,
  user_id        text not null default 'manifuels',
  name           text not null,
  role           text default 'Operator',
  phone          text default '',
  monthly_salary numeric default 0,
  joined_date    date,
  notes          text default '',
  active         boolean default true,
  salary_history jsonb not null default '[]'::jsonb
);

create table if not exists public.staff_attendance (
  id       bigserial primary key,
  user_id  text not null default 'manifuels',
  staff_id bigint not null,
  date     date not null,
  shift    text not null,
  status   text,
  notes    text default ''
);
create unique index if not exists staff_attendance_natural_key
  on public.staff_attendance (staff_id, date, shift);

create table if not exists public.staff_payments (
  id               bigint primary key,
  user_id          text not null default 'manifuels',
  staff_id         bigint not null,
  date             date not null,
  type             text not null,
  amount           numeric default 0,
  advance_deducted numeric default 0,
  notes            text default '',
  created_by       text
);

create table if not exists public.owner_drawings (
  id         bigint primary key,
  user_id    text not null default 'manifuels',
  date       date not null,
  amount     numeric default 0,
  purpose    text default '',
  notes      text default '',
  created_by text,
  updated_at timestamptz default now()
);

-- Free-text notes. The only table in the schema with no fixed shape, which is
-- the point: it holds the things that do not have a form yet.
create table if not exists public.notes (
  id         bigint primary key,
  user_id    text not null default 'manifuels',
  title      text default '',
  body       text default '',
  tag        text default '',
  pinned     boolean default false,
  created_by text,
  updated_by text,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);
create index if not exists notes_recent_idx on public.notes (user_id, updated_at desc);

create table if not exists public.activity_log (
  id           bigserial primary key,
  username     text,
  display_name text,
  action       text,
  entity_type  text,
  entity_id    text,
  details      text default '',
  created_at   timestamptz default now()
);

create table if not exists public.rate_history (
  id         bigserial primary key,
  fuel       text,
  old_rate   numeric,
  new_rate   numeric,
  changed_by text,
  changed_at timestamptz default now()
);

-- Same access model as the rest of the schema until 099 lands.
do $$
declare t text;
begin
  foreach t in array array[
    'customer_profiles','pack_register','staff','staff_attendance',
    'staff_payments','owner_drawings','notes','activity_log','rate_history'
  ] loop
    execute format('alter table public.%I disable row level security', t);
    execute format('grant all on public.%I to anon, authenticated', t);
  end loop;
end $$;

do $$
declare s text;
begin
  for s in select sequencename from pg_sequences where schemaname='public' loop
    execute format('grant usage, select on sequence public.%I to anon, authenticated', s);
  end loop;
end $$;
