# ManiFuels ⛽

A fuel station management system built from scratch — no frameworks, no fluff, just one HTML file running a full business.


## What Is This?
ManiFuels is a Progressive Web App that handles the complete day-to-day operations of a fuel station. Built as a single self-contained HTML file with a Supabase PostgreSQL backend and deployed on Cloudflare Pages for unlimited free hosting.
No React. No Node. No build pipeline. Just open the URL and run your station.

## Why It Exists
Running a fuel station involves a surprising amount of manual bookkeeping — shift meter readings, fuel load invoices, oil stock, customer credit, staff attendance, daily balances. This was all done on paper. ManiFuels replaces all of it with a fast, mobile-friendly web app that syncs everything to the cloud in real time with full multi-user support.

## What It Does
### 🏠 Dashboard
Live summary of today's revenue, last 7-day performance, current balance, and revenue trend chart — visible the moment you log in.

### 📋 Shift Entry

Dual-machine meter readings for MSD (Petrol) and HSD (Diesel)
Auto-calculates litres dispensed, revenue, GPay/Paytm/cash collections, expenses, and closing balance
Price change mode — if fuel rate changes mid-shift, enter split readings at two different rates and the system calculates the correct blended total
40ml pack oil and loose 2T Oil (1L) automatically deducted from stock after each shift save

### ⛽ Fuel Load Register

Matches the exact BPCL/HPCL/Nayara invoice format
Fields: Basic Price (₹/KL), TN VAT (₹/L), VAT/LST %, Lorry Rental — full bill breakdown auto-calculated
2-stage confirmation + permanent lock — once locked, records cannot be edited or deleted
Supplier payment tracking with FULLY PAID indicator

### 📊 Live Stock Dashboard

Real-time tank levels for MSD (15 KL) and HSD (20 KL) with visual gauge bars
Status: OK / LOW / CRITICAL based on tank thresholds
Daily average consumption and estimated days of stock remaining
Profit margin comparison: expected profit from load calculations vs actual shift balance with target-met indicator

### 📒 Credit Ledger

Customer-wise credit and payment tracking with full history
Payments from shift entry are automatically date-stamped and synced to each customer's ledger
SHIFT vs MANUAL payment badges in history view
Partial payments, outstanding balance, and per-customer discount rate support

### 🧾 Oil Stock Registry

Lubricant and accessory inventory management
Stock auto-deducted when oil invoices are registered, reversed on deletion
40ml pouches linked to shift pack readings, 2T Oil linked to loose oil readings

### 👥 Staff Management

Staff master register with roles, salary, and join date
Per-shift attendance tracking (Present / Absent / Half-day)
Salary, advance, bonus, and chit payment records
Advance deduction tracked automatically on salary entries

### 💰 Owner Drawings

Separate tracking of money taken out of the business by the owner
Distinct from operational expenses for clean P&L

### 📈 Reports & Activity Log

Rate history — every fuel/oil rate change logged with who changed it and when
Activity log — full audit trail of who did what across every module
Revenue trend charts and shift history


## Tech Stack
LayerTechFrontendVanilla JS, HTML5, CSS3BackendSupabase (PostgreSQL)AuthSHA-256 hashed passwords, sessionStorageHostingCloudflare PagesBuild toolNoneDependenciesZero (CDN only)

## Database Schema
14 tables, no RLS, anon key access:
shift_records       — shift meter readings and financials
stock_items         — oil and accessory inventory  
ledger_entries      — customer credit with payment history
oil_invoices        — lubricant purchase invoices
fuel_loads          — tanker load records with bill breakdown
app_settings        — rates, opening stock, preferences
users               — multi-user logins with SHA-256 hashed passwords
customer_profiles   — per-customer discount rates and notes
pack_register       — 40ml/20ml pack purchase log
activity_log        — full audit trail (who did what, when)
rate_history        — fuel/oil rate change history
staff               — staff master register
staff_attendance    — per-shift attendance records
staff_payments      — salary, advance, bonus, chit payments
owner_drawings      — owner withdrawal tracking

### Multi-User Access
ManiFuels supports multiple family/staff logins, each with their own display name and role. Passwords are stored as SHA-256 hashes — never plain text. Every record is tagged with created_by and updated_by for full accountability.
Owner  → full access to all modules
Staff  → shift entry, stock, ledger

# Images

## Login Page

<img width="1674" height="748" alt="image" src="https://github.com/user-attachments/assets/47d867bf-7ba0-4995-845a-ccaf43743e77" />

## Main Page

<img width="1920" height="1023" alt="image" src="https://github.com/user-attachments/assets/bc6d2035-888a-4cb7-a848-9fcae1cfe185" />

## Menu

<img width="322" height="980" alt="image" src="https://github.com/user-attachments/assets/d902eef2-e22c-4432-86b8-ddf02a156e86" />


