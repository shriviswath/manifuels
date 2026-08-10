# Roadmap

Ordered by what actually costs the business money, not by effort.

## Done

| Area | Change |
|---|---|
| Dates | All local-time. UTC dates made night shifts default to yesterday and shifted month boundaries. |
| Revenue | Excludes credit repayments. Every revenue figure was previously inflated by credit collected. |
| COGS | Cost of goods **sold** — litres × weighted-average landed cost, plus line-level cost for counter stock, packs and loose oil. Was "everything bought this period". |
| Supplier dues | `totalCost − amountPaid`. Was subtracting the payment twice, halving every outstanding balance. |
| Fuel cost/L | Volume-weighted, never falls back to `basicPrice` (₹/KL, ~1000× off). |
| Wages | Gross salary + bonus. Advances are loans, and were being expensed twice. |
| Drawings | Reported below the profit line, not as an expense. |
| Re-save | Stock and ledger side effects run once per shift id. Was double-deducting. |
| Overpayment | Excess credit repayment becomes an advance instead of vanishing. |
| Settlement | Explicitly oldest-first. |
| Loose oil | Litres ÷ litres-per-unit against a configured source item. Was subtracting litres from a bottle count. |
| Testing fuel | Metered in litres so it leaves tank stock. Was rupees only. |
| Price change | Split litres validated against the meter. Was unchecked — revenue was whatever was typed. |
| Meters | Per-machine readings stored; carry-forward from the previous shift and a continuity check. |
| Delete | Reverses stock and removes the ledger rows the shift created. |
| Dip & Variation | Physical dip vs book stock, per tank, cumulative. |
| Offline | Outbox queue with retry, "n unsent" chip, merge-not-replace sync. |
| Egress | 5-minute fallback polling instead of 30-second full-table polling (~4 GB/month → negligible). |
| PWA | Real `sw.js` and `manifest.json`. The blob-URL service worker never registered, so offline never worked. |
| XSS | Customer, staff, supplier and item names escaped before interpolation. |
| Repo | Workflows in `.github/workflows/`. `deploy.yml` was sitting in the root named `manifuels_complete_setup.sql`, where GitHub never ran it. |

## Next — free

**1. `station_id` and one set of books.** `user_id` is the username and every
query filters on it, so each owner sees only what they entered. Multi-owner
reporting has never actually worked. `db/006` has the migration; the client
change goes with it.

**2. RLS and Supabase Auth.** Four plaintext passwords in the source, an anon
key that can read and write every table, and a role flag from `sessionStorage`.
Fine while it is four family phones. Not fine the day a DSM gets a login.
Same migration as above — do them together.

**3. Pack register consolidation.** Pack stock lives in two places and is
matched by string. One register, matched by id.

**4. Config-driven tanks and nozzles.** Machine count and tank capacity are
hardcoded. Adding a nozzle currently means editing HTML.

**5. DSM attribution.** Which operator was on which nozzle for which shift, so a
shortage points somewhere instead of nowhere. Needs 4 first.

## Next — costs money

| Thing | Cost | When |
|---|---|---|
| **Supabase Pro** | $25/mo (~₹2,100) | When the data starts being used for tax or disputes — the free plan has no automated backups beyond the nightly `pg_dump`, and no point-in-time recovery. Or when a second station appears. |
| Phone OTP login | ~₹0.15–0.25/SMS + DLT registration | Deferred. Username+password works and the schema supports OTP without a migration. |
| Custom domain | ~₹900–1,200/yr | Cosmetic. `github.io` installs as a PWA identically. |

## Free-tier limits to watch

* **Egress 5 GB/month** — the binding constraint. Any change that increases poll
  frequency or fetches full tables more often needs to be checked against this.
* **500 MB database** — not a concern. Two shifts and two dips a day is well
  under a megabyte a year.
* **Auto-pause after 7 idle days** — the nightly backup workflow keeps the
  project awake. Do not disable it.
