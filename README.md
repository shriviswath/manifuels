<div align="center">

# ⛽ ManiFuels

**Shift accounts, stock, credit and profit for a fuel station, in one offline-first web app.**

Built for **Mani Fuels, Karamadai**: morning and night shifts, petrol (MSD) and diesel (HSD),
lubricants, customer credit, staff and owners' books.

[**Open the app → manifuels.vercel.app**](https://manifuels.vercel.app) · [Architecture](docs/ARCHITECTURE.md) · [Database](db/README.md) · [Security cutover](docs/SECURITY_CUTOVER.md) · [Roadmap](docs/ROADMAP.md) · [Changelog](CHANGELOG.md)

</div>

---

## Why this exists

Paper registers and spreadsheets answer "how much cash is in the drawer", but not
*"did we actually make money this week, and where did it leak?"* ManiFuels records
every shift from the meter readings up, keeps the credit ledger and stock in the
same place, and works out profit the way an accountant would: cost of what was
**sold**, not of what was bought. Every figure can be traced back to the entries
behind it.

It runs on the phones at the pump, keeps working without internet, and syncs
when the connection comes back.

## What it does

### Shift operations
- **Two shifts a day.** Morning is 9 AM – 6 PM; night is 6 PM – 9 AM and is filed under the date it starts. The app opens on the shift that is due and warns an hour after a shift ends if it has not been saved.
- **Meter readings per machine** (MSD M1/M2, HSD M1/M2). Readings carry forward from the previous shift and are checked for continuity. A price change mid-shift splits the litres.
- **Testing fuel and hydrometer draws** are metered in litres and returned to the tank, so they leave neither revenue nor stock wrong.
- **Collections:** cash, GPay, Paytm, customer credit, credit repaid, cash handed over, and expenses by head (tea/food, items, chit fund, other).
- **Tally:** what was collected against what was sold. Cash over or short is shown per shift.
- **Staff on duty:** attendance is marked while entering the shift and written to the register on save.
- **Shift locking.** A locked shift cannot be edited or deleted. Unlocking is owner-only, needs a reason and is logged.

### Stock
- **Fuel tanks:** live book stock per tank, days of stock left, and an **order advisor** (what to order, when, and whether it fits).
- **Dip & variation:** physical dip against book stock, per tank and cumulative, flagged beyond a tolerance.
- **Fuel loads:** bill calculation (basic ₹/KL, TN VAT, VAT/LST, lorry rent), landed cost per litre, supplier dues.
- **Oil & lubricants:** counter stock, oil purchase register, 40 ml pack stock with minimum-level alerts, and loose oil drawn from opened bottles.

### Customers & credit
- Credit sales per shift land in each customer's ledger. **Payments settle the oldest bills first.** Anything paid beyond the debt is kept as an advance.
- Payments are dated records with mode and reference. Bulk payback shows where the money will land before it is recorded.
- Transfers between accounts, a per-customer discount rate, and billing details.
- **Invoice PDF** and **account statement PDF** per customer. Overdue credit is flagged on the dashboard.

### Staff & owners
- Staff register, attendance, advances, salary, bonuses, a monthly payroll report and **printable payslips**.
- **Owner drawings** are recorded below the profit line, not as an expense.

### Reports
- **Profit & loss** from one engine (`_plCore`): revenue excluding credit repaid, weighted-average landed cost of fuel sold, line-level cost for oil, packs and counter stock, operating expenses, and gross and net margin.
- **CA workings:** the full statement with Notes 1–8, shift-by-shift schedules, tie-outs, and a *"where money can leak"* checks section.
- **Business statement:** a bank-statement-style ledger of every money movement with a running balance. Printable A4 and CSV.
- **Export report** of all business data, and a weekly profit comparison on the dashboard.
- Every printed document paginates on A4 with repeated table headers and a "Page x of y" footer.

### Security (MF_AUTH_V2)
- Personal accounts (Supabase Auth). The server decides who is an owner or staff, not the browser.
- Owners add, reset and remove people from the in-app **Members** panel.
- Row-level security: only signed-in members of the station can read or write. Owner drawings and the activity log are owners-only.
- `created_by` / `updated_by` and the activity log are stamped by the server. Every edit and delete keeps a before-copy in `mf_auth.history`.

> Rolled out through [`docs/SECURITY_CUTOVER.md`](docs/SECURITY_CUTOVER.md). Until stage 2 of that guide is run, the database is still open to the public key.

### Works offline
- Installable PWA. The app shell and the Supabase client are precached, so it opens and records with no signal.
- Writes go to the phone first. Anything the server has not accepted waits in an **outbox** (the orange *"n unsent"* badge) and is never silently dropped.
- **Sync Health** (tap the badge) shows why the server refused an entry.
- Realtime updates between phones, with a 5-minute fallback poll.

## How it's built

```
 phone (PWA)                                     Supabase
┌──────────────────────────────────┐            ┌──────────────────────────────┐
│ index.html — markup, CSS, JS     │            │ Postgres                     │
│   │                              │  upsert    │  shift_records, ledger_*,    │
│   ▼                              │ ─────────► │  stock_items, fuel_loads,    │
│ localStorage  (device truth,     │            │  staff_*, dip_readings, …    │
│   written first)                 │ ◄───────── │  row-level security          │
│   │   └─ outbox → retried        │  merge by  │ Auth  (members, roles)       │
│   ▼                              │  id + time │ Realtime (changes → phones)  │
│ _plCore · _fuelWAC · workings    │            └──────────────────────────────┘
└──────────────────────────────────┘                    ▲
           ▲  sw.js: shell + vendor/supabase.min.js     │ nightly pg_dump
           │  precached, network-first for index.html   │ (GitHub Actions)
        Vercel (static hosting, deploys on push)
```

| Layer | Choice | Why |
|---|---|---|
| App | One `index.html`, vanilla JS, no build step | Deploys as a static file, runs from `file://` for testing, nothing to maintain |
| Data | Supabase Postgres + Auth + Realtime | Hosted, free tier fits one station comfortably |
| Offline | `localStorage` + outbox + `sw.js` | The pump is not always online |
| Charts | Chart.js 4.4.1 | — |
| Client lib | `vendor/supabase.min.js` (supabase-js 2.115.0), pinned CDN fallback | Loads offline |
| Hosting | Vercel, auto-deploy from `main` | — |
| Backups | `.github/workflows/backup.yml`: nightly `pg_dump`, 90 days | The free plan has none, and this also stops the project auto-pausing |

The money model, sync, merge and tombstone rules are in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Repository

```
index.html              the whole app
sw.js                   service worker (bump CACHE when shipped files change)
manifest.json, icons    PWA install
vendor/supabase.min.js  supabase-js, served locally so it works offline
db/                     SQL migrations — see db/README.md
  stage1_accounts.sql     accounts, members, invites        (security stage 1)
  stage2_lock.sql         row-level security, history, guard (security stage 2)
  stage2_unlock.sql       emergency undo of stage 2
docs/                   ARCHITECTURE, ROADMAP, SECURITY_CUTOVER
.github/workflows/      nightly database backup
```

## Setting it up

1. **Database:** in Supabase → SQL Editor, apply the migrations in [`db/`](db/README.md) in order, then do the security cutover in [`docs/SECURITY_CUTOVER.md`](docs/SECURITY_CUTOVER.md).
2. **Supabase settings:** Authentication → Email → **Confirm email: off**. Accounts are `username@manifuels.vercel.app` and nothing is e-mailed.
3. **App:** set `SUPABASE_URL` and `SUPABASE_ANON_KEY` near the top of `index.html`. The anon key is meant to be public; security comes from row-level security. **Never** put a service-role key or database URL in the repo.
4. **Hosting:** connect the repo to Vercel (no build command, output = repo root). Every push to `main` deploys.
5. **Backups:** add the repository secret `SUPABASE_DB_URL` (session pooler, port 5432). The details are in `backup.yml`.
6. **First sign-in:** follow steps 3–5 of the cutover guide (a one-time owner code from the SQL Editor). Then invite everyone else from **Members**.

## Working on the code

The single-file design has one rule that matters more than any other:

> **Never paste a whole replacement `index.html`.** Change the specific function.

Two blocks are marked `CRITICAL BLOCK — AUTH / SESSION` and `CRITICAL BLOCK — MULTI-DEVICE SYNC`. Both have been silently deleted by whole-file overwrites before.

How changes are made here:
- **Scoped patches.** Each change is a script of exact-string hunks. Every anchor must match exactly once or nothing is written, a sentinel string makes it safe to run twice, and every `<script>` block is syntax-checked before saving.
- **Every write syncs.** Any new mutation needs a matching `_sbUpsert` / `_sbRemove` call. Otherwise it saves locally, looks fine, and is undone by the next merge.
- **Test at phone width.** 390 px, on the actual pages. Check printed output as real A4 PDFs.
- **Migrations are idempotent** and applied one file at a time. After the security lock, **never run `004_grants.sql` or `apply_all.sql`**; both switch security off, and both now refuse to run.
- **Ship `sw.js` with a new `CACHE` name** whenever vendored files change, so open apps offer the update.

## Business rules the app enforces

| Rule | Detail |
|---|---|
| Shift windows | Morning 9 AM–6 PM; night 6 PM–9 AM, dated by its start |
| Revenue | Value of goods sold. Credit repaid is a receivable coming back, not a sale |
| Cost of goods | Litres sold × weighted-average landed cost up to that date, never the purchase total of the period |
| Testing fuel | Returned to the tank; not revenue, not a loss |
| Credit settlement | Oldest bill first; excess becomes an advance |
| Drawings | Appropriation of profit, below the line |
| Cash over/short | Collections + credit + expenses − value sold. A surplus is not profit |

## Roadmap

Priority order agreed for the next stage:

1. **Security lock-down.** Supabase Auth, roles, row-level security, history. *Built; cutover in progress.*
2. **Phone notifications.** Shift saved, cash short, missed shift, low stock and a morning report, as push notifications to the installed app (no third party).
3. **AI assistant in the app.** Ask *"how much did we sell yesterday?"*, *"who owes us the most?"* or *"why was profit lower this week?"* It answers only from the app's own calculations, marks estimates, and never changes records without confirmation.
4. **Fuel-bill photo.** Photograph the supplier invoice and the fuel-load form fills itself for review.

Longer-term items and free-tier limits are in [`docs/ROADMAP.md`](docs/ROADMAP.md).

## License

Private software for Mani Fuels. © Mani Fuels. All rights reserved.
