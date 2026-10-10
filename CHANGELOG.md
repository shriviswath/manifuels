# Changelog

## [Unreleased]

Credit ledger, profit reporting and sync correctness, plus the first two pieces
of the transaction layer. Requires `db/013_soft_deletes.sql` and
`db/014_payments_and_locking.sql`; the client falls back safely if either is
not applied.

### Assistant (`MF_AI_V1`, `patch_ai_assistant.py`)
Needs `db/021_ai_assistant.sql`, the `mf-ai` edge function and a free Groq key
to answer typed questions — steps in `docs/AI_ASSISTANT_SETUP.md`. Without
them the ⚡ buttons still work: they read the app directly.
- **Ask in plain words**, from ✦ ASK in the header, the menu or the dashboard:
  sales and litres for any period, profit and why it moved, petrol vs diesel
  margin, who owes and who is overdue, one customer's account, supplier dues,
  tank levels and when to order, oil stock, staff pay, expenses, tanker loads,
  the audit checks, and how the app itself works.
- **The figures are the app's.** Each answer comes from a tool that wraps the
  existing engine (`_plCore`, `_plExtras`, `_custPosition`, `orderAdvice`,
  `payrollFor`, `_plAuditChecks`, `computeAlerts`…) — there is no second set
  of arithmetic to disagree with Reports. The model picks the tool and words
  the result; it never sees the database. Cards under the answer are drawn
  from the tool result, not from the model's text.
- **Invented figures are caught.** Every amount, litre figure and percentage
  in the model's sentence is checked against what the tools returned (or the
  exact sum or difference of two of them) and flagged ⚠ if it is not there.
- **"Why was profit lower" is arithmetic, not opinion**: the change in fuel
  gross profit is split exactly into a volume part and a margin part, plus
  oil/stock and expenses, and the answer says when the two periods do not
  hold the same number of shifts.
- **Statement PDFs**: customer statement and invoice, business statement and
  business report for a period, staff statement. The assistant opens the
  document the app already prints, from a button on a card.
- **Nothing is recorded without a tap.** "Record ₹5,000 from Kumar by GPay"
  and "make a note…" produce a card showing exactly what will happen; CONFIRM
  runs the app's own save. The activity log line ends "via assistant". A card
  older than 15 minutes refuses.
- **Owners and managers only**, decided on the server. Managers get no
  profit, margins, drawings, business statement or audit checks — those tools
  are not offered to the model for a manager, and refuse if called anyway.
- **The key is not in this file.** The `mf-ai` edge function holds it, checks
  the caller through `mf_ai_gate()` (role, per-minute and per-day limits), and
  falls back to a second model when the first is rate-limited. `mf_ai.usage`
  counts calls and tokens; it has no column for questions or answers.
- **Out of reach is not out of use.** No internet, allowance used up, or the
  server part not installed: the assistant says which, and answers the plain
  questions straight from the tools.
- `submitBulkPayment()` is split at its `confirm()`: the save is now
  `_bulkPayCommit()` — the same lines, moved not rewritten (only the
  activity-log line gains an optional "via" label) — shared by the ledger's
  RECORD button and the assistant's CONFIRM. No figure moves.

### Price revisions at 6 AM (`MF_PRICE_6AM_V1`, `patch_price_change_6am.py`)
No migration: the 6 AM readings ride in `shift_records.meters.rates` (jsonb).
- **Entry.** A revision takes effect at 6 AM, so "PRICE CHANGED AT 6 AM" is
  offered on the Morning shift only. Staff enter the meter reading taken at
  6 AM per machine; litres at the old rate are opening → 6 AM, at the new rate
  6 AM → closing. Typed "litres before / after" are gone, so the split cannot
  disagree with the meters. Each half is rounded to paise.
- **The panel closes on save.** It used to stay open on the next shift and
  block it with "Split is 0.000 L but meters show …".
- **The new rate goes everywhere on save**: rate box, saved rates (synced to
  every phone), rate history stamped 06:00, activity log. A corrected or
  back-filled older shift writes history only and never changes today's rate.
- **Fuel is costed at a moving average.** Each load is blended into what is in
  the tank when it arrives (book stock, capped at tank capacity); each shift is
  costed at the tank's average when it sold. The all-time average barely moved
  after a revision, so profit stayed wrong by nearly the whole revision for
  months. With flat prices the two methods give identical figures; historical
  profit moves only in periods after a cost change.
- **Stock gain / loss on a revision** — stock in the tank at the change × the
  change — is shown on the entry panel, shift detail, P&L cards, CA workings
  (2A-iv), statement, Petrol vs Diesel report and dashboard. It is a memo, not
  an extra profit line: it reaches gross profit as that stock is sold.
- The dashboard no longer raises "cost vs pump rate — check the tanker
  entries" when a recent revision explains the margin; a price cut is listed
  as a stock loss instead.
- Statement and "Pump rate periods" show both rates of a revised shift rather
  than a blended rate.

### Added
- **Payments are records.** Money received used to be added to `paid_back` on
  the bill and nothing else was kept, so a payment had no date of its own, no
  mode and no reference. Every payment now also writes to `ledger_payments` —
  from the per-bill button, the bulk panel, and the credit-back lines on a
  shift — and a customer's page shows a dated payment history grouped by
  reference. `paid_back` is unchanged and still drives every report, so no
  figure moves.
- **Shift locking.** A saved shift could be re-saved or deleted at any time and
  the P&L behind it changed with no record. Locking closes a shift to edits and
  deletion; unlocking is owner-only, requires a reason, and lands in the
  activity log. Clearing history now keeps locked shifts.
- Bulk payback on a customer account. One lump sum is laid across the unpaid
  bills oldest-first, with a live preview of where it lands before recording.
  Excess over the debt is held as an advance. Each bill it touches is stamped
  with a `PAY-` reference, mode and date.
- Net margin and a shift-count warning on the weekly profit widget. A profit
  drop caused by unentered shifts now looks different from a real one.

### Fixed — money
- One profit engine (`_plCore`) behind both the dashboard widget and the
  Reports page. The widget had its own formula: it counted oil, pack and
  counter-stock revenue at the top and none of their margin at the bottom
  while still deducting every shift expense, so selling lubricants made
  reported profit worse.
- Weekly profit is costed at each period's own end. The widget used an
  all-time weighted average, so last week's profit moved every time a tanker
  was recorded.
- The hydrometer draw no longer inflates COGS. Its litres are recovered from
  its rupee value at each shift's own pump rate and removed from the costed
  litres — fuel that went back in the tank was being charged for.
- "Last 7 days" was eight days (`date >= today-7`), and disagreed with both
  the weekly widget and the 7d report range. All three are seven days.
- The KPI tiles netted testing fuel out of revenue in some places and not
  others, so two tiles on one screen showed different revenue.

### Fixed — data integrity
- A delete now reaches other devices. `deleted_at` travels; devices drop their
  own copy instead of pushing the row back up. Deletes are also recoverable
  for the first time.
- The bulk ledger save no longer re-stamps every row. `saveLedger()` runs on
  every change and called `_touch()` on the whole ledger, so all rows shared
  one fresh timestamp — the merge resolves on that, so the last device to sync
  won every row and silently reverted the other's edits.

### Fixed — interface
- Customer cards are equal height and names no longer break mid-word.

### Fixed — repository
- The root `apply_all.sql` was a stale v2.1 copy holding only migrations
  001–003. Running it skipped 004–012, including `009_updated_at`, whose
  absence makes every write to four tables fail into the outbox. It is now a
  stub that refuses to run and points at `db/apply_all.sql`.
- `db/README.md` listed 8 of the 13 migrations.

## [2.1.0] — 2026-08-10

Correctness pass across accounting, dates and sync, plus repository structure.
No visual changes.

### Fixed — money
- Revenue no longer counts credit repayments as sales.
- COGS is the cost of goods **sold**, not stock purchased in the period.
- Supplier dues no longer subtract the payment twice.
- Fuel cost per litre is volume-weighted and never falls back to `basicPrice`.
- Staff advances are no longer expensed twice; wage cost is gross salary + bonus.
- Owner drawings moved below the profit line.
- Excess credit repayment is carried forward as an advance instead of discarded.
- Credit settlement is explicitly oldest-first.
- Loose oil converts litres to units of its source stock item.
- Line-level cost for counter stock, packs and loose oil.
- Money rounded to paise on save.

### Fixed — data integrity
- All dates use local time. UTC dates made night shifts default to the previous
  day and shifted month boundaries by one at each end.
- Re-saving a shift no longer double-deducts stock or duplicates ledger rows.
- Deleting a shift reverses stock and removes the credit rows it created.
- `clearHistory` now clears the server too.
- Offline writes are queued and retried instead of silently lost.
- Sync merges by id instead of replacing local data wholesale.
- Unique ids: `Date.now() + Math.random()` collided within a millisecond.

### Fixed — validation
- Mid-shift price-change split is checked against the metered litres.
- Meter continuity between consecutive shifts is checked.
- Testing fuel is entered in litres so it leaves tank stock.

### Added
- **Dip & Variation** — physical tank dip against book stock, cumulative.
- Carry-forward of the previous shift's closing meter readings.
- "n unsent" chip showing queued offline writes.

### Fixed — platform
- Real `sw.js`; the blob-URL service worker was rejected by Chrome and offline
  never worked.
- Static `manifest.json` instead of a generated blob.
- Polling every 5 minutes instead of 30 seconds (~4 GB/month of egress against
  a 5 GB free-tier allowance).
- Customer, staff, supplier and item names escaped before interpolation.

### Repository
- `deploy.yml` moved to `.github/workflows/` — it was in the root named
  `manifuels_complete_setup.sql` and had never run.
- Nightly `pg_dump` backup workflow, which also keeps the free-tier project
  from auto-pausing.
- Schema reconstructed into `db/001`–`005`; RLS and `station_id` staged as
  `db/006_rls_and_auth.sql.pending`.
- `docs/ARCHITECTURE.md`, `docs/ROADMAP.md`.
