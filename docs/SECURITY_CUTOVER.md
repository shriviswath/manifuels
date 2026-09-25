# ManiFuels — security cutover (sign-in + database lock)

**What changes:** real accounts (Supabase Auth), roles decided by the server,
no passwords inside `index.html`, and a database that only signed-in members of
the station can read or write. Every change and delete keeps a before-copy.

**Time needed:** about 30 minutes, plus a minute on each phone.
**Order matters.** Do the steps top to bottom. Nothing is locked until step 7,
and step 7 has an undo.

---

## Before you start

- [ ] Every phone has synced: no orange **"unsent"** badge in the header.
- [ ] You can open the Supabase dashboard for project `hiapuixdmhibimbinlri`.
- [ ] Pick a **one-time code** for yourself (8+ characters, not your old password).
      You will type it once in step 3 and once in the app in step 5.

## 1 · Run stage 1 in Supabase

Supabase → **SQL Editor** → New query → paste all of `db/stage1_accounts.sql` → **Run**.
It adds the accounts system; your data and the current app are untouched.
The last result shows members and invites (both empty the first time).

## 2 · Turn off "Confirm email"

Supabase → **Authentication** → **Sign In / Providers** → **Email** →
switch **Confirm email** OFF → Save.
(Accounts use `username@manifuels.vercel.app` as a label; nothing is e-mailed.)
Leave **Allow new users to sign up** ON — invited people need it to create their
account; an account without an invite gets no access.

## 3 · Create your own invite

In the SQL Editor:

```sql
select mf_auth.bootstrap_owner('shriviswath', 'Shri Viswath C K', 'YOUR-ONE-TIME-CODE');
```

Only someone inside the Supabase dashboard can run this. After step 5, clear
that query from the SQL Editor history.

## 4 · Upload the new app

GitHub → `shriviswath/manifuels` → upload, replacing the existing files:

| File | Where |
|---|---|
| `index.html` | repo root |
| `sw.js` | repo root (new cache name, so open apps offer the update) |
| `db/stage1_accounts.sql`, `db/stage2_lock.sql`, `db/stage2_unlock.sql` | `db/` |
| `db/004_grants.sql`, `db/apply_all.sql` | `db/` (now refuse to run once locked) |
| `docs/SECURITY_CUTOVER.md` | `docs/` |

Delete from the repo: `db/099_rls_and_auth.sql.pending` (old plan, conflicts)
and `ChangePassword.md` (old method).

Wait for Vercel to finish deploying (about a minute).

## 5 · Sign in as owner

Open the app → accept the **update** prompt (or close it fully and reopen).
Username `shriviswath` + your one-time code → the app asks you to choose your
password (8+ characters, not your username) → you are in.
User menu (tap your name) now shows **Change password** and **Members**.

## 6 · Invite the others and move every phone over

User menu → **Members** → Add a person → username, name, role → **INVITE**.
The panel shows a one-time password — give it to that person. Do this for
`kalimuthu`, `kumutha`, `nithin` (role **owner**) and any staff (role **staff**).

On **every phone**: update the app (prompt, or close and reopen), sign in with
the username + one-time password, choose a password. Check each phone shows no
**"unsent"** badge. Members shows everyone as **active**.

> A phone still on the old app cannot send anything after step 7.

## 7 · Lock the database

SQL Editor → paste all of `db/stage2_lock.sql` → **Run**.

- It refuses to run if no owner has signed in (so you cannot lock yourself out).
- The **Messages** tab may list old views/functions it closed — the app uses none.
  If it says the **guard was not installed**, the lock still works; just never
  run `004_grants.sql` / `apply_all.sql` (they now refuse anyway).
- The results show every table as **locked = true** and the member list.
  Check the member list is exactly the people you invited.

## 8 · Check it worked (2 minutes)

- The app still works on every phone: open a page, save something small, it syncs.
- Sign out and back in once.
- Optional: in a private browser window, open the site without signing in — the
  sign-in screen appears and no data loads.

---

## Day to day after this

| Need | Where |
|---|---|
| New person | Members → Add a person |
| Forgot password | Owner: Members → **Reset** → give them the new one-time password |
| Someone leaves | Members → **Remove** (access ends at once; their past entries stay) |
| Change your own password | User menu → Change password |
| Who changed what | Every edit/delete keeps a before-copy. SQL: `select * from mf_auth.history order by id desc limit 50;` |

**What staff can and cannot do.** The app hides owner pages (P&L, drawings,
activity log, Members). The database keeps drawings and the activity log
owners-only, lets only owners delete records permanently, and lets only owners
change a **locked** shift. Other records (shifts, credit, stock, salaries) are
readable by every member, and a staff member can soft-delete an unlocked record —
recorded with their name and fully restorable from the history.

## If something goes wrong

- **"Server not set up for the new sign-in yet"** — step 1 was not run.
- **"Supabase is asking for e-mail confirmation"** — step 2; then re-invite that person.
- **"An account with this username already exists…"** — owner re-invites them
  (this also removes an account someone else registered with that name).
- **Orange "unsent" badge that stays** — tap it. Entries refused for sign-in
  reasons are kept, never dropped; sign out and in again.
- **Emergency — the app cannot sync at all after step 7:** run
  `db/stage2_unlock.sql` (the database is open again, like today; accounts are
  kept), then tell Claude what the Sync Health screen says. Re-run
  `stage2_lock.sql` once fixed.
- **Never** run `004_grants.sql` or `apply_all.sql` after the lock.
