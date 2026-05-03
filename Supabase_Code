-- ═══════════════════════════════════════════════════════
--  ManiFuels v2.5 — COMPLETE DATABASE SETUP
--  Run this entire file in: Supabase → SQL Editor → New Query → Run
--  Safe to re-run. Will not delete or overwrite existing data.
-- ═══════════════════════════════════════════════════════


-- ╔═══════════════════════════════════════════════════════╗
-- ║  PART 1: BASE TABLES                                  ║
-- ╚═══════════════════════════════════════════════════════╝

-- ─── SHIFT RECORDS ─────────────────────────────────────
CREATE TABLE IF NOT EXISTS shift_records (
  id            TEXT PRIMARY KEY,
  user_id       TEXT NOT NULL DEFAULT 'shriviswath',
  date          DATE NOT NULL,
  shift         TEXT NOT NULL,
  msd_t         NUMERIC DEFAULT 0,
  hsd_t         NUMERIC DEFAULT 0,
  msd_v         NUMERIC DEFAULT 0,
  hsd_v         NUMERIC DEFAULT 0,
  ps            INTEGER DEFAULT 0,
  os            NUMERIC DEFAULT 0,
  pv            NUMERIC DEFAULT 0,
  ov            NUMERIC DEFAULT 0,
  st_rev        NUMERIC DEFAULT 0,
  right_total   NUMERIC DEFAULT 0,
  left_total    NUMERIC DEFAULT 0,
  gpay          NUMERIC DEFAULT 0,
  paytm         NUMERIC DEFAULT 0,
  cash          NUMERIC DEFAULT 0,
  exp           NUMERIC DEFAULT 0,
  credit        NUMERIC DEFAULT 0,
  cred_back     NUMERIC DEFAULT 0,
  bal           NUMERIC DEFAULT 0,
  notes         TEXT DEFAULT '',
  saved_at      TIMESTAMPTZ DEFAULT NOW()
);


-- ─── STOCK ITEMS ───────────────────────────────────────
CREATE TABLE IF NOT EXISTS stock_items (
  id            BIGINT PRIMARY KEY,
  user_id       TEXT NOT NULL DEFAULT 'shriviswath',
  name          TEXT NOT NULL,
  cat           TEXT DEFAULT 'Oil',
  qty           NUMERIC DEFAULT 0,
  rate          NUMERIC DEFAULT 0,
  unit          TEXT DEFAULT 'Bottle'
);


-- ─── LEDGER ENTRIES (Credit/Advance) ───────────────────
CREATE TABLE IF NOT EXISTS ledger_entries (
  id            BIGINT PRIMARY KEY,
  user_id       TEXT NOT NULL DEFAULT 'shriviswath',
  date          DATE NOT NULL,
  customer      TEXT NOT NULL,
  shift         TEXT,
  fuel          TEXT,
  amount        NUMERIC NOT NULL,
  paid_back     NUMERIC DEFAULT 0
);


-- ─── OIL PURCHASE INVOICES ─────────────────────────────
CREATE TABLE IF NOT EXISTS oil_invoices (
  id            BIGINT PRIMARY KEY,
  user_id       TEXT NOT NULL DEFAULT 'shriviswath',
  date          DATE NOT NULL,
  inv           TEXT,
  company       TEXT,
  items         JSONB DEFAULT '[]',
  total_cost    NUMERIC DEFAULT 0,
  total_sell    NUMERIC DEFAULT 0,
  profit        NUMERIC DEFAULT 0,
  amount_due    NUMERIC DEFAULT 0,
  amount_paid   NUMERIC DEFAULT 0
);


-- ─── FUEL LOADS ────────────────────────────────────────
CREATE TABLE IF NOT EXISTS fuel_loads (
  id            BIGINT PRIMARY KEY,
  user_id       TEXT NOT NULL DEFAULT 'shriviswath',
  date          DATE NOT NULL,
  inv           TEXT,
  supplier      TEXT,
  driver        TEXT DEFAULT '',
  lorry         TEXT DEFAULT '',
  transport     TEXT DEFAULT '',
  type          TEXT NOT NULL,
  vol           NUMERIC DEFAULT 0,
  vol_kl        NUMERIC DEFAULT 0,
  basic_price   NUMERIC DEFAULT 0,
  tn_vat        NUMERIC DEFAULT 0,
  lst_pct       NUMERIC DEFAULT 0,
  lorry_rent    NUMERIC DEFAULT 0,
  basic_amt     NUMERIC DEFAULT 0,
  tn_vat_amt    NUMERIC DEFAULT 0,
  lst_amt       NUMERIC DEFAULT 0,
  bill_total    NUMERIC DEFAULT 0,
  sell          NUMERIC DEFAULT 0,
  total_cost    NUMERIC DEFAULT 0,
  revenue       NUMERIC DEFAULT 0,
  profit        NUMERIC DEFAULT 0,
  density       NUMERIC DEFAULT 0.82,
  buy           NUMERIC DEFAULT 0,
  gst_pct       NUMERIC DEFAULT 0,
  gst_amt       NUMERIC DEFAULT 0,
  amount_due    NUMERIC DEFAULT 0,
  amount_paid   NUMERIC DEFAULT 0,
  locked        BOOLEAN DEFAULT FALSE
);


-- ─── SETTINGS (rates + opening volumes per user) ───────
CREATE TABLE IF NOT EXISTS settings (
  user_id       TEXT PRIMARY KEY,
  rates         JSONB DEFAULT '{}',
  opening_msd   NUMERIC DEFAULT 0,
  opening_hsd   NUMERIC DEFAULT 0,
  updated_at    TIMESTAMPTZ DEFAULT NOW()
);


-- ─── PACK SIZES CONFIG ─────────────────────────────────
CREATE TABLE IF NOT EXISTS pack_sizes (
  size          INTEGER PRIMARY KEY,
  user_id       TEXT NOT NULL DEFAULT 'shriviswath',
  enabled       BOOLEAN DEFAULT FALSE,
  rate          NUMERIC DEFAULT 0
);


-- ╔═══════════════════════════════════════════════════════╗
-- ║  PART 2: USERS & AUTH                                 ║
-- ╚═══════════════════════════════════════════════════════╝

-- ─── USERS TABLE ───────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
  username      TEXT PRIMARY KEY,
  display_name  TEXT NOT NULL,
  password_hash TEXT NOT NULL,
  role          TEXT NOT NULL DEFAULT 'staff',
  last_login    TIMESTAMPTZ,
  login_count   INTEGER DEFAULT 0,
  created_at    TIMESTAMPTZ DEFAULT NOW()
);

-- Insert/update the 4 family users (passwords are SHA-256 hashed)
INSERT INTO users (username, display_name, password_hash, role) VALUES
  ('shriviswath', 'Shri Viswath C K', 'e1eaca4ebf0808bb81709f12a19d05eb76987cdb963032e7a998bdfca07bf024', 'owner'),
  ('kalimuthu',   'Kalimuthu M',      '11ac4af7a255a6b5fa5dbc6cc28283678da059648fd9def8116f79192f1f7018', 'owner'),
  ('kumutha',     'Kumutha K',        '175ffd6fac32bcd8e7a114429062820d8e7df5156c193114ca5a283f144d64d6', 'owner'),
  ('nithin',      'Nithin K',         '11d7a0f63e957da9ee166a19b554ec1f48209774cbd6913750812dd5710b1905', 'owner')
ON CONFLICT (username) DO UPDATE SET
  display_name = EXCLUDED.display_name,
  role         = EXCLUDED.role;
-- Note: password_hash is NOT updated on conflict (passwords stay as set).


-- ╔═══════════════════════════════════════════════════════╗
-- ║  PART 3: NEW FEATURE TABLES                           ║
-- ╚═══════════════════════════════════════════════════════╝

-- ─── CUSTOMER PROFILES (per-customer discount rate) ────
CREATE TABLE IF NOT EXISTS customer_profiles (
  customer_name    TEXT PRIMARY KEY,
  user_id          TEXT NOT NULL DEFAULT 'shriviswath',
  discount_per_l   NUMERIC DEFAULT 0,
  notes            TEXT DEFAULT '',
  created_at       TIMESTAMPTZ DEFAULT NOW(),
  updated_at       TIMESTAMPTZ DEFAULT NOW(),
  updated_by       TEXT
);


-- ─── PACK REGISTER (40ml/20ml/etc pack purchases) ──────
CREATE TABLE IF NOT EXISTS pack_register (
  id            BIGINT PRIMARY KEY,
  user_id       TEXT NOT NULL DEFAULT 'shriviswath',
  date          DATE NOT NULL,
  supplier      TEXT DEFAULT '',
  qty           INTEGER NOT NULL DEFAULT 0,
  cost          NUMERIC DEFAULT 0,
  total_cost    NUMERIC DEFAULT 0,
  notes         TEXT DEFAULT '',
  size          INTEGER DEFAULT 40,
  created_at    TIMESTAMPTZ DEFAULT NOW(),
  created_by    TEXT
);


-- ─── ACTIVITY LOG (who did what, when) ─────────────────
CREATE TABLE IF NOT EXISTS activity_log (
  id            BIGSERIAL PRIMARY KEY,
  username      TEXT NOT NULL,
  display_name  TEXT,
  action        TEXT NOT NULL,
  entity_type   TEXT,
  entity_id     TEXT,
  details       TEXT DEFAULT '',
  ip_address    TEXT,
  created_at    TIMESTAMPTZ DEFAULT NOW()
);


-- ─── RATE HISTORY (every fuel/oil rate change) ─────────
CREATE TABLE IF NOT EXISTS rate_history (
  id            BIGSERIAL PRIMARY KEY,
  fuel          TEXT NOT NULL,
  old_rate      NUMERIC NOT NULL,
  new_rate      NUMERIC NOT NULL,
  changed_by    TEXT,
  changed_at    TIMESTAMPTZ DEFAULT NOW()
);


-- ─── STAFF REGISTER ────────────────────────────────────
CREATE TABLE IF NOT EXISTS staff (
  id              BIGSERIAL PRIMARY KEY,
  user_id         TEXT NOT NULL DEFAULT 'shriviswath',
  name            TEXT NOT NULL,
  role            TEXT DEFAULT 'operator',
  monthly_salary  NUMERIC DEFAULT 0,
  phone           TEXT DEFAULT '',
  active          BOOLEAN DEFAULT TRUE,
  joined_date     DATE,
  notes           TEXT DEFAULT '',
  created_at      TIMESTAMPTZ DEFAULT NOW()
);


-- ─── STAFF ATTENDANCE ──────────────────────────────────
CREATE TABLE IF NOT EXISTS staff_attendance (
  id            BIGSERIAL PRIMARY KEY,
  user_id       TEXT NOT NULL DEFAULT 'shriviswath',
  staff_id      BIGINT NOT NULL,
  date          DATE NOT NULL,
  shift         TEXT NOT NULL,
  status        TEXT DEFAULT 'present',
  notes         TEXT DEFAULT '',
  created_at    TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(staff_id, date, shift)
);


-- ─── STAFF PAYMENTS ────────────────────────────────────
CREATE TABLE IF NOT EXISTS staff_payments (
  id                BIGSERIAL PRIMARY KEY,
  user_id           TEXT NOT NULL DEFAULT 'shriviswath',
  staff_id          BIGINT NOT NULL,
  date              DATE NOT NULL,
  type              TEXT DEFAULT 'salary',
  amount            NUMERIC NOT NULL,
  advance_deducted  NUMERIC DEFAULT 0,
  notes             TEXT DEFAULT '',
  created_by        TEXT,
  created_at        TIMESTAMPTZ DEFAULT NOW()
);


-- ─── OWNER DRAWINGS ────────────────────────────────────
CREATE TABLE IF NOT EXISTS owner_drawings (
  id            BIGSERIAL PRIMARY KEY,
  user_id       TEXT NOT NULL DEFAULT 'shriviswath',
  date          DATE NOT NULL,
  amount        NUMERIC NOT NULL,
  purpose       TEXT DEFAULT '',
  notes         TEXT DEFAULT '',
  created_by    TEXT,
  created_at    TIMESTAMPTZ DEFAULT NOW()
);


-- ╔═══════════════════════════════════════════════════════╗
-- ║  PART 4: ADD MISSING COLUMNS (safe re-runs)           ║
-- ╚═══════════════════════════════════════════════════════╝

ALTER TABLE shift_records   ADD COLUMN IF NOT EXISTS created_by TEXT;
ALTER TABLE shift_records   ADD COLUMN IF NOT EXISTS updated_by TEXT;
ALTER TABLE shift_records   ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();
ALTER TABLE shift_records   ADD COLUMN IF NOT EXISTS extra_pack_sold JSONB DEFAULT '{}';
ALTER TABLE shift_records   ADD COLUMN IF NOT EXISTS tag TEXT DEFAULT '';

ALTER TABLE stock_items     ADD COLUMN IF NOT EXISTS updated_by TEXT;

ALTER TABLE ledger_entries  ADD COLUMN IF NOT EXISTS created_by TEXT;
ALTER TABLE ledger_entries  ADD COLUMN IF NOT EXISTS updated_by TEXT;
ALTER TABLE ledger_entries  ADD COLUMN IF NOT EXISTS kind TEXT DEFAULT 'credit';

ALTER TABLE oil_invoices    ADD COLUMN IF NOT EXISTS created_by TEXT;

ALTER TABLE fuel_loads      ADD COLUMN IF NOT EXISTS created_by TEXT;

ALTER TABLE pack_register   ADD COLUMN IF NOT EXISTS size INTEGER DEFAULT 40;

ALTER TABLE staff_payments  ADD COLUMN IF NOT EXISTS advance_deducted NUMERIC DEFAULT 0;


-- ╔═══════════════════════════════════════════════════════╗
-- ║  PART 5: INDEXES FOR SPEED                            ║
-- ╚═══════════════════════════════════════════════════════╝

CREATE INDEX IF NOT EXISTS idx_shift_records_date     ON shift_records(date DESC);
CREATE INDEX IF NOT EXISTS idx_shift_records_savedat  ON shift_records(saved_at DESC);
CREATE INDEX IF NOT EXISTS idx_ledger_customer        ON ledger_entries(customer);
CREATE INDEX IF NOT EXISTS idx_ledger_date            ON ledger_entries(date DESC);
CREATE INDEX IF NOT EXISTS idx_fuel_loads_date        ON fuel_loads(date DESC);
CREATE INDEX IF NOT EXISTS idx_oil_invoices_date      ON oil_invoices(date DESC);
CREATE INDEX IF NOT EXISTS idx_pack_register_date     ON pack_register(date DESC);
CREATE INDEX IF NOT EXISTS idx_activity_log_created   ON activity_log(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_activity_log_user      ON activity_log(username, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_rate_history_date      ON rate_history(changed_at DESC);
CREATE INDEX IF NOT EXISTS idx_rate_history_fuel      ON rate_history(fuel, changed_at DESC);
CREATE INDEX IF NOT EXISTS idx_staff_active           ON staff(active, name);
CREATE INDEX IF NOT EXISTS idx_attendance_date        ON staff_attendance(date DESC);
CREATE INDEX IF NOT EXISTS idx_attendance_staff       ON staff_attendance(staff_id, date DESC);
CREATE INDEX IF NOT EXISTS idx_payments_staff         ON staff_payments(staff_id, date DESC);
CREATE INDEX IF NOT EXISTS idx_drawings_date          ON owner_drawings(date DESC);


-- ╔═══════════════════════════════════════════════════════╗
-- ║  PART 6: DISABLE ROW LEVEL SECURITY                   ║
-- ║  (so the anon key can read/write — your app uses      ║
-- ║   custom username/password auth, not Supabase Auth)   ║
-- ╚═══════════════════════════════════════════════════════╝

ALTER TABLE shift_records      DISABLE ROW LEVEL SECURITY;
ALTER TABLE stock_items        DISABLE ROW LEVEL SECURITY;
ALTER TABLE ledger_entries     DISABLE ROW LEVEL SECURITY;
ALTER TABLE oil_invoices       DISABLE ROW LEVEL SECURITY;
ALTER TABLE fuel_loads         DISABLE ROW LEVEL SECURITY;
ALTER TABLE settings           DISABLE ROW LEVEL SECURITY;
ALTER TABLE pack_sizes         DISABLE ROW LEVEL SECURITY;
ALTER TABLE users              DISABLE ROW LEVEL SECURITY;
ALTER TABLE customer_profiles  DISABLE ROW LEVEL SECURITY;
ALTER TABLE pack_register      DISABLE ROW LEVEL SECURITY;
ALTER TABLE activity_log       DISABLE ROW LEVEL SECURITY;
ALTER TABLE rate_history       DISABLE ROW LEVEL SECURITY;
ALTER TABLE staff              DISABLE ROW LEVEL SECURITY;
ALTER TABLE staff_attendance   DISABLE ROW LEVEL SECURITY;
ALTER TABLE staff_payments     DISABLE ROW LEVEL SECURITY;
ALTER TABLE owner_drawings     DISABLE ROW LEVEL SECURITY;


-- ╔═══════════════════════════════════════════════════════╗
-- ║  PART 7: GRANT ACCESS TO ANON ROLE                    ║
-- ╚═══════════════════════════════════════════════════════╝

GRANT ALL ON shift_records      TO anon, authenticated;
GRANT ALL ON stock_items        TO anon, authenticated;
GRANT ALL ON ledger_entries     TO anon, authenticated;
GRANT ALL ON oil_invoices       TO anon, authenticated;
GRANT ALL ON fuel_loads         TO anon, authenticated;
GRANT ALL ON settings           TO anon, authenticated;
GRANT ALL ON pack_sizes         TO anon, authenticated;
GRANT ALL ON users              TO anon, authenticated;
GRANT ALL ON customer_profiles  TO anon, authenticated;
GRANT ALL ON pack_register      TO anon, authenticated;
GRANT ALL ON activity_log       TO anon, authenticated;
GRANT ALL ON rate_history       TO anon, authenticated;
GRANT ALL ON staff              TO anon, authenticated;
GRANT ALL ON staff_attendance   TO anon, authenticated;
GRANT ALL ON staff_payments     TO anon, authenticated;
GRANT ALL ON owner_drawings     TO anon, authenticated;

-- Grant sequence access (needed for BIGSERIAL primary keys)
GRANT USAGE, SELECT ON SEQUENCE activity_log_id_seq       TO anon, authenticated;
GRANT USAGE, SELECT ON SEQUENCE rate_history_id_seq       TO anon, authenticated;
GRANT USAGE, SELECT ON SEQUENCE staff_id_seq              TO anon, authenticated;
GRANT USAGE, SELECT ON SEQUENCE staff_attendance_id_seq   TO anon, authenticated;
GRANT USAGE, SELECT ON SEQUENCE staff_payments_id_seq     TO anon, authenticated;
GRANT USAGE, SELECT ON SEQUENCE owner_drawings_id_seq     TO anon, authenticated;


-- ═══════════════════════════════════════════════════════
--  ✅ DONE!
--
--  VERIFY EVERYTHING WORKED:
--    SELECT username, display_name, role FROM users;
--    SELECT COUNT(*) FROM shift_records;
--    SELECT COUNT(*) FROM ledger_entries;
--
--  TEST LOGIN CREDENTIALS:
--    Username: shriviswath  | Password: shriviswath
--    Username: kalimuthu    | Password: kalimuthu
--    Username: kumutha      | Password: kumutha
--    Username: nithin       | Password: nithin
--
--  TO CHANGE A USER'S PASSWORD:
--    1. Open browser DevTools console on the app
--    2. Run: await sha256('your_new_password')
--    3. Copy the hash
--    4. Run in SQL Editor:
--       UPDATE users SET password_hash='<paste_hash>' WHERE username='<name>';
--
--  TO ADD A NEW USER LATER:
--    INSERT INTO users (username, display_name, password_hash, role)
--    VALUES ('newname', 'Display Name', '<sha256_hash>', 'staff');
-- ═══════════════════════════════════════════════════════
