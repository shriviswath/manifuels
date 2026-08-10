# ManiFuels ⛽

Shift accounting, stock and credit management for **Mani Fuels**, Karamadai.

**Live:** https://shriviswath.github.io/manifuels

> Install on mobile: open in Chrome → **Add to Home Screen**
> Install on desktop: open in Chrome → install icon in the address bar

---

## Repository layout

```
├── index.html                  the entire app: markup, styles, logic
├── sw.js                       service worker — offline shell
├── manifest.json               PWA manifest
├── favicon.ico  icon-*.png     app icons
├── .github/workflows/
│   ├── deploy.yml              push to main → GitHub Pages
│   └── backup.yml              nightly pg_dump + free-tier keep-alive
├── db/
│   ├── README.md               how and when to apply each migration
│   ├── 001_schema.sql          base tables
│   ├── 002_dip_readings.sql   dip readings + variation
│   ├── 003_realtime.sql       replica identity + publication
│   ├── 004_ledger_shift_link.sql
│   ├── 005_realtime.sql        replica identity + publication
│   └── 006_rls_and_auth.sql.pending   staged — read db/README.md
└── docs/
    ├── ARCHITECTURE.md         how the data model actually works
    └── ROADMAP.md              what is left, and what it costs
```

---

## What the app does

| Screen | Purpose |
|---|---|
| **Dashboard** | Revenue, cash position, credit outstanding, supplier dues, alerts |
| **Shift Entry** | Nozzle readings, pack and loose oil, counter stock, collections, credit |
| **Tally** | Cash over/short against the value of what was sold |
| **Dip & Variation** | Physical tank dip vs book stock — the loss detector |
| **History** | Past shifts, with reversal on delete |
| **Reports / P&L** | Revenue, COGS on goods *sold*, gross and net profit |
| **Oil Stock / Register** | Counter stock and purchase invoices |
| **Fuel Loads** | Tanker billing, landed cost per litre, supplier dues |
| **Credit Ledger** | Customer-wise credit, advances, statements |
| **Staff Register** | Attendance, salary, advances |
| **Owner Drawings** | Withdrawals, reported below the profit line |
| **Activity Log** | Audit trail |

---

## Architecture in one paragraph

A single HTML file, no build step. Data lives in `localStorage` first and syncs
to Supabase Postgres. Writes go through an outbox: if the network is down or the
server rejects a row, the change is parked in `localStorage` and retried
automatically — the header shows an **"n unsent"** chip while anything is
waiting. Reads merge by id instead of replacing, so a shift entered offline is
never destroyed by the next sync. Realtime pushes changes between devices;
polling is a 5-minute fallback, not the primary mechanism.

See `docs/ARCHITECTURE.md` for the parts that are easy to get wrong.

---

## Deploying

```bash
git add .
git commit -m "your change"
git push          # live in ~60 seconds
```

`deploy.yml` checks that `index.html`, `sw.js`, `manifest.json` and the icons
all exist and that the manifest is valid JSON before publishing.

**After a deploy**, the service worker serves the new `index.html` on the next
load (network-first for the shell). If a device seems stuck on an old version,
close every tab of the app and reopen it.

---

## Database setup

Paste `db/apply_all.sql` into the Supabase SQL editor and run it. It is
idempotent, runs as one transaction, and does not recreate your existing
tables — it only adds the columns v2.1 needs and repairs the realtime setup.

Then set the repo secret `SUPABASE_DB_URL` so nightly backups run. Details in
`db/README.md`.

---

## Cost

Everything currently runs at **₹0**: GitHub Pages, GitHub Actions and the
Supabase free plan. The limit that matters is **5 GB/month of egress** — which
is why sync polling is 5 minutes and not 30 seconds. See `docs/ROADMAP.md` for
what would justify paying, and when.

---

*Private repository — Mani Fuels internal operations tool.*
