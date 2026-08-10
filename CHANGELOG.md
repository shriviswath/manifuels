# Changelog

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
