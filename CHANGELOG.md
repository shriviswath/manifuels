# Changelog

## [Unreleased]

Credit ledger, profit reporting and sync correctness, plus the first two pieces
of the transaction layer. Requires `db/013_soft_deletes.sql` and
`db/014_payments_and_locking.sql`; the client falls back safely if either is
not applied.

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
