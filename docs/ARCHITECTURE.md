# Architecture

## Single file, no build

`index.html` contains all markup, CSS and JavaScript. That is deliberate: it
deploys as a static file, works from `file://` for testing, and there is no
toolchain to maintain. The cost is that the file is ~7,600 lines, so **edits
must be scoped**. Two blocks are marked in comments as critical:

* `CRITICAL BLOCK — AUTH / SESSION` (`showLoginScreen` → `initAuth`)
* `CRITICAL BLOCK — MULTI-DEVICE SYNC` (visibility, poll, realtime)

Both have been silently deleted by whole-file overwrites in the past. Never
paste a full replacement file; change the specific function.

## Data flow

```
  user input
      │
      ▼
  localStorage        ← source of truth on the device, always written first
      │
      ├── _sbUpsert(table, rows) ──► Supabase
      │        │
      │        └── on failure ──► mf_outbox (localStorage) ──► retried on
      │                                                       reconnect / sync
      ▼
  loadAllFromSupabase()
      │
      └── _mergeById(local, remote, tsField) ──► merged set, local-only rows
                                                 pushed up
```

### Conflict keys

`_sbUpsert` used to hardcode `onConflict: 'id'`. Not every table is keyed on
`id` — `app_settings` is keyed on `user_id`, `users` on `username`,
`customer_profiles` on `customer_name`, `pack_sizes` on `size`, and
`staff_attendance` on `(staff_id, date, shift)`. `MF_CONFLICT_KEY` maps them.
Add a table, add its key.

### Why writes go through `_sbUpsert`

`supabase-js` **resolves with `{ error }` rather than throwing**. The original
code did `await _supa.from(t).upsert(row)` and discarded the result, so an RLS
rejection or a constraint violation looked exactly like success. `_sbUpsert`
checks the error, and parks the row in the outbox if anything went wrong.

### Why reads merge instead of replace

`loadAllFromSupabase` used to do `records = serverRows`. A shift entered on a
phone with no signal survived until the next successful sync and then vanished.
`_mergeById` keeps rows from both sides, resolves conflicts by timestamp where
one exists (`savedAt` on shifts and dips), and returns the local-only rows so
they can be uploaded.

### Egress

Supabase free allows 5 GB/month. Four devices polling the full table set every
30 seconds is roughly 4 GB/month on its own — the whole allowance, growing every
month. Polling is now every 5 minutes and **skips entirely while the realtime
channel is connected**, since realtime already reports changes. It still runs if
the outbox has something waiting.

## The money model

Three ideas that are easy to conflate:

| Concept | Definition | Where |
|---|---|---|
| **Cash over/short** | collections + credit + expenses − value sold | Tally, `bal` |
| **Revenue** | value of goods sold, *excluding* credit repayments | `_recRevenue(r)` |
| **COGS** | cost of what was sold — litres × weighted-average cost | `_fuelWAC`, `_recNonFuelCOGS` |

A cash surplus is not profit. Credit collected is a receivable coming back, not
a sale. Stock bought in a period is not the cost of what was sold in it. All
three were conflated in earlier versions and each produced a wrong number.

### Weighted-average cost

`_fuelWAC(type, upto)` — total landed cost ÷ total litres across all loads of
that type up to a date. It never falls back to `basicPrice`, which is ₹ per KL
and would be ~1000× too large.

`_stockUnitCost()` / `_packUnitCost()` — weighted-average purchase price per
stock item and per pack size, from oil invoices and the pack register.

Anything that cannot be priced from purchase history is reported as *unpriced
revenue* and estimated from the buy:sell ratio, never silently costed at zero.

## Dates

Everything uses `_isoLocal()`, not `toISOString().slice(0,10)`. The latter is
UTC — in IST every timestamp before 05:30 resolves to the previous day, which
made night shifts default to yesterday's date and pushed month boundaries off by
one at both ends.

## Ledger model

* `amount > 0` — credit given to the customer
* `amount < 0` — advance received from the customer
* `paid_back` — settled so far, against `|amount|` either way

Settlement is oldest-first. Payment beyond the outstanding debt becomes a new
negative-amount row (an advance) rather than being discarded.

## The recurring fault

Every write site has to remember to call Supabase. Across three audit passes,
twelve of them did not — the change was written to `localStorage`, looked
saved, and was undone by the next merge. If you add a mutation, it needs a
matching `_sbUpsert` / `_sbRemove` call, or it will exhibit exactly this bug.

The real fix is a store layer where saving *is* syncing, so there is nothing to
forget. Worth doing after `db/006`, not before — no sense hardening a data path
that is about to be rewritten.

## Notes and ledger adjustments

`notes` is the only table with no fixed shape. Everything else in the app is a
form with a schema; the pad is where the things that do not have one yet live.
It merges by id on `updated_at`, same as every other collection.

An **adjustment** moves an amount between two customer accounts. It writes two
rows sharing one `ADJ-<id>` reference — `+X` on the account the money leaves,
`-X` on the account it lands in, both `kind='adjust'`, `fuel='ADJUST'`. Nothing
is created or destroyed, so the ledger totals are unchanged and either side can
be traced to the other. Writing one side only was the tempting shortcut and it
leaves the books unbalanced with nothing to point at three months later.

## Why writes fail silently at the database, not the client

Three separate faults have produced "the app saved it but Supabase is empty":

1. A column named in the insert does not exist (`updated_at`, `stock_sold`,
   `billing`, `owner`). PostgREST rejects the whole row.
2. The table does not exist — the base schema was hand-run and versions differ.
3. RLS re-enabled on one table from the dashboard.

All three look identical from the app: the outbox parks the row and the header
shows "n unsent". `db/apply_all.sql` fixes 1 and 2; `db/004_grants.sql` fixes 3.
Where a column is genuinely new, the writer retries without it rather than lose
the record — `sbSaveRecord`, `sbSaveCustProfile` and `sbSaveDrawing` all do this.

## Deletes need a tombstone

Deleting is two operations: remove it here, ask the server to remove it there.
The second can fail — offline, rejected, or simply slower than the next poll —
and `_mergeById` had no memory of the first, so the server's copy was pulled
straight back in. The row "came back", which reads as data corruption and is
really just an ordering problem.

`_tombAdd(table,id)` records the id at the moment the delete is *attempted*,
not after it succeeds. `_dropDeleted(table, remoteRows)` filters the pulled set
against that record and re-issues any delete that evidently did not stick.
Tombstones expire after 60 days — long enough for a phone that was switched off
for a month.

## Ids must be integers

An older build minted ids as `Date.now()+Math.random()`, so rows created then
carry a fractional id against a `bigint` column. Two consequences, both of which
presented as "the credit ledger does not sync":

* `sbSaveAllLedger` sent the raw id. One fractional value makes Postgres reject
  the **whole array**, and `saveLedger()` sends the entire ledger on every
  change — so one legacy row stopped all credit sync.
* the per-row writer rounded before sending, so the server knew the row by a
  different id than the device did. The merge saw two rows; a delete aimed at
  one never touched the other.

`_intId()` rounds on the way in and out. `_normaliseIds()` repairs the stored
ledger once at boot, collapsing a rounding pair into one row and keeping the
larger `paidBack` so a recorded payment is never lost.

## A rejected array must not cost the whole array

`_sbUpsert` now splits a rejected batch and retries row by row, so a bad row
costs one row instead of every row, and the console names the id that failed.

## Sync Health

The outbox always knew why the server refused a write; it only ever said so in
the console. **Sync Health** (user menu, or tap the "n unsent" chip) shows the
per-table rejection message, maps the common ones to the migration that fixes
them, and offers retry, discard, and copy-diagnostics.

## Known sharp edges

* `user_id` is the username, so each owner has a separate set of books.
  `db/006` fixes this with `station_id`.
* Role gating (`_isOwner`, `.owner-only`) is client-side only and trivially
  bypassed. Real enforcement needs RLS — also `db/006`.
* Pack stock is tracked in `pack_register` *and* in a name-matched `stock_items`
  row. One register per commodity, matched by id, is the eventual fix.
* Machine count and tank capacities are hardcoded.
