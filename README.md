# ManiFuels ⛽

**Fuel bunk shift account & stock manager** — built for Mani Fuels petrol station.

[![Deploy Status](https://github.com/shriviswath/manifuels/actions/workflows/deploy.yml/badge.svg)](https://github.com/shriviswath/manifuels/actions/workflows/deploy.yml)

## 🔗 Live App
**[https://shriviswath.github.io/manifuels](https://shriviswath.github.io/manifuels)**

> Install on mobile: open the link in Chrome → tap "Add to Home Screen"  
> Install on desktop: visit the link in Chrome → click the install icon in the address bar

---

## Features
- **Shift Entry** — MSD/HSD nozzle readings, loose oil, pack sales, cash/UPI/credit accounting
- **Tally** — Live shift balance verification
- **History** — Past shift records with edit/delete
- **Reports** — Revenue charts, sales trends
- **Oil Stock** — Auto-deduct on shift save (2T 1L and 0.5L bottle support)
- **Oil Register** — Invoice tracking
- **Fuel Loads** — BPCL/HPCL format load billing
- **Credit Ledger** — Customer-wise outstanding tracking
- **Staff Register** — Attendance and payment records
- **Owner Drawings** — Withdrawal tracking
- **Activity Log** — Full audit trail
- **Real-time Sync** — Any device, any time via Supabase Realtime

---

## Tech Stack
| Layer | Tool |
|---|---|
| Frontend | Single-file PWA (HTML + CSS + JS) |
| Database | Supabase (Postgres + Realtime) |
| Hosting | GitHub Pages |
| CI/CD | GitHub Actions |
| Offline | Service Worker (sw.js) |

---

## Deployment
Every push to `main` auto-deploys via GitHub Actions. No manual steps needed.

```bash
git add .
git commit -m "your change"
git push
# → Live in ~60 seconds
```

---

*Private repository — Mani Fuels internal operations tool.*
