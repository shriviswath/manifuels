# ManiFuels — assistant setup

Ask the app in plain words — *"how much diesel did we sell this week"*, *"who owes
us the most"*, *"why was yesterday's profit lower"*, *"statement PDF for Kumar"* —
and get the app's own figures back.

**Needs:** the security cutover done (sign-in and the locked database).
**Cost:** nothing. It runs on Groq's free plan.
**Time:** about 10 minutes, once. Nothing to do on the phones except update the app.

The **⚡ buttons** in the assistant (TODAY, CREDIT, DUES, TANKS, ALERTS…) work as
soon as the new `index.html` is live, before any of the steps below: they read
the app directly and use no server. The steps below switch on the part that
understands a typed question.

---

## 1 · Get a free key (Groq)

1. Open **console.groq.com** and sign in. No card is asked for.
2. **API Keys** → **Create API Key** → name it `manifuels` → copy the key
   (it starts with `gsk_`). You will not be shown it again.
3. Recommended: in the Groq console's **Data Controls** settings, switch on
   **Zero Data Retention**. Groq does not keep requests by default, but may log
   some for up to 30 days when it is chasing a fault or abuse; this turns that off.

The key goes into Supabase in the next step and **nowhere else** — never into
`index.html`, never into this repository.

## 2 · Deploy the gateway (Edge Function), first time only

Supabase → **Edge Functions** → **Deploy a new function** → **Via Editor**.

1. Name it **`mf-ai`** (exactly this).
2. Replace the sample code with the whole of `supabase/functions/mf-ai/index.ts`.
3. Leave **Verify JWT** on.
4. Click **Deploy**.
5. **Edge Functions** → **Secrets** → add a secret named **`GROQ_API_KEY`** with
   the key from step 1 → Save.

## 3 · Run the database part

Supabase → **SQL Editor** → paste all of `db/021_ai_assistant.sql` → **Run**.

It adds the limits, the on/off switches and a usage count. It does not touch or
read any business table. Safe to run again. The result is one row:

| enabled | allow_managers | per_minute | per_user_day | station_day | calls_logged |
|---|---|---|---|---|---|
| true | true | 12 | 250 | 800 | 0 |

## 4 · Update the app

Upload the new `index.html` to GitHub (or merge the pull request) and wait a
minute for Vercel. On each phone, close the app fully and open it again.

## 5 · Check it

Open the app as an owner → **✦ ASK** (top of the screen, or in the menu) → tap
**ⓘ**. Under TODAY it should say **● Ready**. Then ask something.

| ⓘ says | Meaning |
|---|---|
| ● Ready | Working |
| ● Language-model key not set | Step 2.5: the `GROQ_API_KEY` secret is missing or misspelt |
| "server part is not installed yet" | Step 2: the function is not deployed, or not named exactly `mf-ai` |
| "database part is missing" | Step 3 was not run |

---

## What it does

| You ask | It uses |
|---|---|
| Sales, litres, collections, cash short/over, for any period | the shift records, through the Reports engine |
| Profit, margins, petrol vs diesel, *why* profit moved | the same P&L engine as Reports (owners only) |
| Who owes, who is overdue, one customer's account | the Credit Ledger |
| What we owe suppliers | Fuel Loads and the Oil Register |
| Tank levels, days left, when to order | the Order Advisor |
| Oil and pack stock, anything needing attention | Oil Stock and the alert bell |
| Staff pay for a month, expenses, tanker loads | Staff Register, shifts, Fuel Loads |
| Audit checks — where money can leak | the CA workings' checks (owners only) |
| "Statement PDF for …", "business statement for last month" | the app's own statement, invoice and report |
| "Record ₹5,000 from Kumar by GPay", "make a note to …" | a card you must **CONFIRM** |
| "What does cash short mean?", "how do I enter a price change?" | built-in notes on how this app works |

**Every figure is worked out by the app, on the phone**, with the code that draws
the Reports and Ledger pages. The language model only chooses what to look up
and writes the sentence; it cannot read the database. Under each answer the
**cards** show the app's figures as they are. If the sentence contains a number
that is not in those figures, the app marks it **⚠** — go by the card.

**It changes nothing by itself.** A payment or a note is prepared as a card; it
is recorded only when you tap **CONFIRM**, through the same save as the ledger's
own RECORD button, and the Activity Log line ends with *via assistant*. A payment
recorded this way can be reversed from the customer's payment history like any
other. The assistant cannot edit or delete shifts, loads, stock or staff records.

## Who can use it

- **Owners:** everything.
- **Managers:** sales, cash, credit, stock, dues, staff pay and documents — **not**
  profit, margins, drawings, the business statement or the audit checks, the same
  as the pages. An owner can switch managers off altogether under ⓘ.
- **Staff:** not at all. The button is not shown, and the server refuses them.

The server decides this from the person's sign-in, not the browser.

## What leaves the app

Your question, and the short result of each lookup — for example *"sales
₹2,83,333 from 2 shifts"* or the list of who owes what — go to Groq (United
States) so it can write the sentence. Customer and staff names in those results
go with them. Nothing else does: no login, no passwords, no access to the
database.

The station keeps a count of who used the assistant and when (`mf_ai.usage`).
It does not keep what was asked or answered.

## Limits

Groq's free plan, per model, in October 2026: 30 requests a minute, 1,000 a day,
8,000 tokens a minute, 200,000 tokens a day. A typical question is two requests.
The app uses two models in turn (`openai/gpt-oss-120b`, then `openai/gpt-oss-20b`),
so in practice that is a question or two a minute at the worst and a few hundred
a day. These numbers are Groq's and can change without notice.

When the free allowance runs out for a moment, the assistant says so and shows
the app's own figures for the question anyway. On top of Groq's limits the
station has its own, in `mf_ai.settings`: 12 requests a minute and 250 a day per
person, 800 a day for everyone.

## Day to day

| Need | Where |
|---|---|
| Switch it off for everyone | ✦ ASK → ⓘ → untick *Assistant switched on* (or `update mf_ai.settings set enabled = false;`) |
| Owners only | ✦ ASK → ⓘ → untick *Managers may use it* |
| Who used it | ✦ ASK → ⓘ, or `select username, count(*) from mf_ai.usage where at > now() - interval '7 days' group by 1;` |
| Change the limits | `update mf_ai.settings set per_user_day = 400;` |
| Replace the key | Supabase → Edge Functions → Secrets → `GROQ_API_KEY` |
| Use another provider | Secrets: `MF_AI_BASE_URL`, `MF_AI_KEY`, `MF_AI_MODELS` — any OpenAI-compatible service. No code change. |
| Remove it completely | Delete the `mf-ai` function and run `drop schema mf_ai cascade;`. The ⚡ buttons keep working. |

## Troubleshooting

| Problem | Fix |
|---|---|
| ✦ ASK is not shown | The person is staff, or the phone still has the old app — close it fully and reopen |
| "Your sign-in has expired" | Sign out and in again |
| "The free allowance … is used up for the moment" | Wait the seconds it says. The ⚡ buttons still work |
| "You have used today's allowance" | The station's own limit; raise `per_user_day` if it is too tight |
| ⚠ under an answer | The model wrote a figure the app did not give it. Use the card. If it happens often, tell Claude which question |
| An answer about the wrong customer | It asks when two names fit; if it picked wrongly, say the full name |
| Nothing happens on CONFIRM | The card is older than 15 minutes — ask again |
| The assistant is slow or fails often | Supabase → Edge Functions → `mf-ai` → **Logs** |
