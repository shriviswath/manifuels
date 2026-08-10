-- ═══════════════════════════════════════════════════════
--  ManiFuels — Data Import
--  Run AFTER manifuels_complete_setup.sql
--  Inserts all your existing data into Supabase
-- ═══════════════════════════════════════════════════════

-- ─── SHIFT RECORDS ────────────────────────────────────
INSERT INTO shift_records (id, user_id, date, shift, msd_t, hsd_t, msd_v, hsd_v, pv, ov, st_rev, right_total, left_total, gpay, paytm, cash, exp, credit, cred_back, bal, notes, saved_at) VALUES
  ('20260322_NIGHT',   'shriviswath', '2026-03-22', 'night',   480.880, 466.790, 48934.349, 43462.817, 560,   252.0, 60,  93269.166,  93315, 0,    26133, 57865, 9317,  0,     0,  45.834,  'Velu Petrol - 100',                          '2026-03-22T16:13:42.966Z'),
  ('20260322_MORNING', 'shriviswath', '2026-03-22', 'morning', 466.893, 249.412, 47511.032, 23222.751, 460,   342.0, 130, 71665.783,  71815, 1200, 20573, 35310, 10750, 3982,  0,  149.217, 'Car Diesel - 2500 , Velu GPay - 1100',       '2026-03-22T05:13:47.744Z'),
  ('20260321_NIGHT',   'shriviswath', '2026-03-21', 'night',   473.860, 551.590, 48219.994, 51358.545, 420,   144.0, 0,   100142.539, 99968, 0,    40644, 50327, 8997,  0,     0,  -174.539,'',                                           '2026-03-21T17:31:02.263Z'),
  ('20260321_MORNING', 'shriviswath', '2026-03-21', 'morning', 337.740, 337.760, 34368.422, 31448.834, 720,   172.8, 113, 66823.056,  66603, 480,  23963, 20662, 9250,  12248, 0,  -220.056,'Night Cash - 9,000',                         '2026-03-21T06:13:44.533Z'),
  ('20260320_NIGHT',   'shriviswath', '2026-03-20', 'night',   462.710, 471.370, 47085.370, 43889.261, 460,   277.2, 763, 92474.830,  92534, 0,    35841, 43076, 9117,  4500,  0,  59.170,  'Shift done by - Sindhu,Velu,Siva(from 8Pm)', '2026-03-21T05:13:35.983Z')
ON CONFLICT (id) DO UPDATE SET
  msd_t=EXCLUDED.msd_t, hsd_t=EXCLUDED.hsd_t,
  bal=EXCLUDED.bal, notes=EXCLUDED.notes;

-- ─── STOCK ITEMS ──────────────────────────────────────
INSERT INTO stock_items (id, user_id, name, cat, unit, qty, rate) VALUES
  (1,  'shriviswath', '90 Gear Oil (5L)',      'Gear Oil', 'Can',    1,  1839),
  (2,  'shriviswath', 'Multi-Purpose 5L',      'Gear Oil', 'Can',    7,  354),
  (3,  'shriviswath', '20x40 (0.5L)',          '2-Stroke', 'Bottle', 1,  181),
  (4,  'shriviswath', 'Trans Fluid (1L)',      'Gear Oil', 'Bottle', 15, 360),
  (5,  'shriviswath', 'Scooto Matic',          'Brake',    'Bottle', 8,  380),
  (6,  'shriviswath', '15-w-40 (1L)',          'Oil',      'Bottle', 7,  320),
  (7,  'shriviswath', '4T Oil (1L)',           'Oil',      'Bottle', 17, 360),
  (8,  'shriviswath', '2T Oil (1L)',           'Oil',      'Bottle', 11, 334),
  (9,  'shriviswath', 'Distilled Water',       'Water',    'Bottle', 0,  20),
  (10, 'shriviswath', '90 Gear Oil (1L)',      'Gear Oil', 'Bottle', 4,  390),
  (11, 'shriviswath', 'Acid Water',            'Water',    'Bottle', 5,  50),
  (12, 'shriviswath', 'Break Oil',             'Oil',      'Bottle', 2,  113),
  (13, 'shriviswath', 'Grease (0.5 KG)',       'Grease',   'Bottle', 17, 280),
  (14, 'shriviswath', 'Grease (1 KG)',         'Grease',   'Bottle', 3,  555),
  (15, 'shriviswath', '2T (0.5L)',             'Oil',      'Bottle', 19, 171),
  (16, 'shriviswath', 'Cool Plus',             'Oil',      'Bottle', 5,  303),
  (17, 'shriviswath', '20x40 Supreme (0.5L)',  'Oil',      'Bottle', 31, 198),
  (18, 'shriviswath', 'Active Petrol',         'Oil',      'Bottle', 11, 200),
  (19, 'shriviswath', 'Active Diesel',         'Oil',      'Bottle', 10, 200),
  (20, 'shriviswath', 'Break Fulio',           'Oil',      'Bottle', 3,  130),
  (21, 'shriviswath', '20x40 Supreme (5L)',    'Oil',      'Can',    2,  1730)
ON CONFLICT (id) DO UPDATE SET
  qty=EXCLUDED.qty, rate=EXCLUDED.rate, name=EXCLUDED.name;

-- ─── FUEL LOADS ───────────────────────────────────────
INSERT INTO fuel_loads (id, user_id, date, inv, supplier, driver, lorry, transport, type, vol, vol_kl, density, basic_price, tn_vat, lst_pct, lorry_rent, basic_amt, tn_vat_amt, lst_amt, bill_total, total_cost, sell, revenue, profit, buy, gst_pct, gst_amt, amount_due, amount_paid, locked) VALUES
  (1774195536449, 'shriviswath', '2026-03-22', '7030327480', 'Nayara (Russia)', 'Venkatesan V', 'TN58AU8719', 'Nakshatra Transport',
   'HSD', 4000, 4, 0.82, 70034.88, 9.62, 11, 12188, 280139.52, 38480.00, 30815.35, 349434.87, 361622.87,
   93.11, 372440, 10817.13, 90.41, 11, 69295.35, 0, 361622.87, true),
  (1774195401429, 'shriviswath', '2026-03-22', '7030327479', 'Nayara (Russia)', 'Venkatesan V', 'TN58AU8719', 'Nakshatra Transport',
   'MSD', 8000, 8, 0.82, 73566.23, 11.52, 13, 24376, 588529.84, 92160.00, 76508.88, 757198.72, 781574.72,
   101.76, 814080, 32505.28, 97.70, 13, 168668.88, 0, 781574.72, true)
ON CONFLICT (id) DO UPDATE SET
  amount_due=EXCLUDED.amount_due,
  amount_paid=EXCLUDED.amount_paid,
  locked=EXCLUDED.locked;

-- ─── CREDIT LEDGER ────────────────────────────────────
INSERT INTO ledger_entries (id, user_id, date, customer, shift, fuel, amount, paid_back) VALUES
  (1774070015983, 'shriviswath', '2026-03-20', 'Famous Cook',         'night',   'MSD/HSD', 3500,  0),
  (1774070015984, 'shriviswath', '2026-03-20', 'Alex',                'night',   'MSD/HSD', 1000,  0),
  (1774071246089, 'shriviswath', '2026-03-21', 'Suresh',              'morning', 'HSD',     16656, 0),
  (1774071594395, 'shriviswath', '2026-03-21', 'ITC Murugesh',        'morning', 'HSD',     12000, 0),
  (1774071662585, 'shriviswath', '2026-03-21', 'Hari Auto',           'morning', 'HSD',     11885, 0),
  (1774071812625, 'shriviswath', '2026-03-21', 'Water Board (Gov)',   'morning', 'HSD',     13965, 0),
  (1774072063447, 'shriviswath', '2026-03-21', 'Mahalakshmi',         'morning', 'HSD',     31321, 0),
  (1774072131598, 'shriviswath', '2026-03-21', 'NLPTC',               'morning', 'HSD',     47930, 0),
  (1774072178393, 'shriviswath', '2026-03-21', 'Sampath',             'morning', 'HSD',     11314, 0),
  (1774072234004, 'shriviswath', '2026-03-21', 'NGO Vinoth',          'morning', 'HSD',     10000, 0),
  (1774072286724, 'shriviswath', '2026-03-21', 'L.E.F',               'morning', 'HSD',     28225, 0),
  (1774072341154, 'shriviswath', '2026-03-21', 'Panapalayam Sathish', 'morning', 'HSD',     20600, 0),
  (1774072545688, 'shriviswath', '2026-03-21', 'Famous Cook',         'morning', 'HSD',     19340, 0),
  (1774073624533, 'shriviswath', '2026-03-21', 'Mahalakshmi',         'morning', 'MSD/HSD', 8170,  0),
  (1774073624534, 'shriviswath', '2026-03-21', 'Raja Rani',           'morning', 'MSD/HSD', 4078,  4078),
  (1774073932827, 'shriviswath', '2026-03-21', 'வாழ்க வளமுடன்',      'morning', 'HSD',     18877, 18877),
  (1774156427743, 'shriviswath', '2026-03-22', 'Raja Rani',           'morning', 'MSD/HSD', 3982,  3982)
ON CONFLICT (id) DO UPDATE SET
  amount=EXCLUDED.amount,
  paid_back=EXCLUDED.paid_back;

-- ─── APP SETTINGS ─────────────────────────────────────
INSERT INTO settings (user_id, rates, opening_msd, opening_hsd) VALUES
  ('shriviswath', '{"msd":"101.76","hsd":"93.11","pack":"20","oil":"360"}', 3023.91, 6405.2)
ON CONFLICT (user_id) DO UPDATE SET
  rates=EXCLUDED.rates,
  opening_msd=EXCLUDED.opening_msd,
  opening_hsd=EXCLUDED.opening_hsd;

-- ═══════════════════════════════════════════════════════
--  DONE. All historical data imported.
--  Open your Cloudflare app → log in → data syncs.
-- ═══════════════════════════════════════════════════════
