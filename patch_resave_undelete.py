#!/usr/bin/env python3
"""
MF_RESAVE_UNDELETE_V1 — a shift re-saved after a delete vanishes from History.

Cause
  Shift ids are date+shift (20260925_MORNING). Deleting a shift soft-deletes the
  server row (deleted_at set) and tombstones the id on the device. Saving the
  same shift again upserts the row but never clears deleted_at, and never clears
  the tombstone. On the next sync _sbSelectAll() treats the row as deleted and
  the merge drops the local copy -> the shift disappears from History, while the
  credit-ledger rows (new ids) and stock deductions made by the save survive.

Fix (4 hunks, index.html only)
  H1 _doSaveShift   : clear this id's tombstone when the shift is saved.
  H2 sbSaveRecord   : send deleted_at = null so the server row is live again.
  H3 _sbSelectAll   : shift row saved AFTER it was deleted (saved_at > deleted_at)
                      is live, not deleted. Also self-heals rows already hit.
  H4 _dropDeleted   : a live shift row newer than this device's tombstone wins
                      (the shift was re-saved on another phone).

Usage:  python3 patch_resave_undelete.py [path/to/index.html]
Idempotent: re-running reports every hunk as already applied.
"""
import shutil, subprocess, sys, re, os, tempfile

PATH = sys.argv[1] if len(sys.argv) > 1 else "index.html"
SENTINEL = "MF_RESAVE_UNDELETE_V1"

HUNKS = [
("H1 _doSaveShift: clear tombstone on save",
"""  localStorage.setItem('fuelRecords',JSON.stringify(records));
  if(_currentUser)sbSaveRecord(rec).catch(console.error);
  const _att=(typeof _saCommit==='function')?_saCommit(rec.date,rec.shift):null;""",
"""  localStorage.setItem('fuelRecords',JSON.stringify(records));
  // MF_RESAVE_UNDELETE_V1: this id may have been deleted earlier. Without
  // clearing the tombstone the next sync drops the shift we just saved.
  if(typeof _tombDel==='function')_tombDel('shift_records',rec.id);
  if(_currentUser)sbSaveRecord(rec).catch(console.error);
  const _att=(typeof _saCommit==='function')?_saCommit(rec.date,rec.shift):null;"""),

("H2 sbSaveRecord: send deleted_at = null",
"""    created_by: _currentUser.username, updated_by: _currentUser.username
  };
  // stock_sold is a newer column.""",
"""    created_by: _currentUser.username, updated_by: _currentUser.username
  };
  // MF_RESAVE_UNDELETE_V1: upsert only writes the columns it is given, so a
  // shift saved under an id that was deleted before stayed deleted on the server.
  if (typeof MF_SOFT_DEL === 'undefined' || MF_SOFT_DEL['shift_records'] !== false) base.deleted_at = null;
  // stock_sold is a newer column."""),

("H2b sbSaveRecord: fallback when deleted_at column is absent",
"""    console.warn('shift_records rejected full row, retrying without stock_sold:', e.message);
    try { await _sbUpsert('shift_records', base); }""",
"""    console.warn('shift_records rejected full row, retrying without stock_sold:', e.message);
    if (/deleted_at/.test(String(e && e.message || ''))) {   // MF_RESAVE_UNDELETE_V1
      delete base.deleted_at;
      if (typeof MF_SOFT_DEL !== 'undefined') MF_SOFT_DEL['shift_records'] = false;
    }
    try { await _sbUpsert('shift_records', base); }"""),

("H3 _sbSelectAll: re-saved shift is live",
"""  const live=[];
  all.forEach(function(r){
    if(r&&r.deleted_at){ if(r.id!=null)_tombAdd(table, r.id); }
    else live.push(r);
  });""",
"""  const live=[];
  all.forEach(function(r){
    // MF_RESAVE_UNDELETE_V1: a shift saved again after it was deleted is live.
    // saved_at is only written by a save (a delete never touches it), so it is
    // a clean comparison. Scoped to shift_records: other tables bump
    // updated_at on the delete itself, which would resurrect real deletes.
    if(r&&r.deleted_at&&table==='shift_records'&&r.saved_at&&
       (Date.parse(r.saved_at)||0)>(Date.parse(r.deleted_at)||0)){
      if(r.id!=null)_tombDel(table, r.id);
      live.push(r); return;
    }
    if(r&&r.deleted_at){ if(r.id!=null)_tombAdd(table, r.id); }
    else live.push(r);
  });"""),

("H4 _dropDeleted: newer save beats older tombstone",
"""    if(_tombHas(table,r.id))resend.push(r.id); else kept.push(r);""",
"""    if(_tombHas(table,r.id)){
      // MF_RESAVE_UNDELETE_V1: re-saved (possibly on another phone) after this
      // device recorded the delete — the newer save wins.
      if(table==='shift_records'){
        var _tt=(_tombRead()[table]||{})[_tombKey(r.id)]||0;
        var _rt=Date.parse(r.savedAt||'')||0;
        if(_rt>_tt){ _tombDel(table,r.id); kept.push(r); return; }
      }
      resend.push(r.id);
    } else kept.push(r);"""),
]


def main():
    if not os.path.exists(PATH):
        sys.exit(f"✗ {PATH} not found")
    src = open(PATH, encoding="utf-8").read()
    out = src
    applied = 0
    for name, old, new in HUNKS:
        if new in out:
            print(f"  = {name}: already applied")
            continue
        n = out.count(old)
        if n != 1:
            sys.exit(f"✗ {name}: anchor found {n} times (expected 1) — file differs from the traced version. Nothing written.")
        out = out.replace(old, new, 1)
        applied += 1
        print(f"  ✓ {name}")

    if applied == 0:
        print("Nothing to do — patch already applied.")
        return

    # Syntax-check every inline <script> before writing anything.
    scripts = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", out, flags=re.S | re.I)
    with tempfile.TemporaryDirectory() as td:
        for i, js in enumerate(scripts):
            p = os.path.join(td, f"s{i}.js")
            open(p, "w", encoding="utf-8").write(js)
            r = subprocess.run(["node", "--check", p], capture_output=True, text=True)
            if r.returncode != 0:
                sys.exit(f"✗ node --check failed on inline script #{i}:\n{r.stderr}\nNothing written.")
    print(f"  ✓ node --check passed on {len(scripts)} inline script(s)")

    shutil.copyfile(PATH, PATH + ".bak")
    open(PATH, "w", encoding="utf-8").write(out)
    print(f"✓ {applied} hunk(s) applied to {PATH} (backup: {PATH}.bak) — sentinel {SENTINEL}")


if __name__ == "__main__":
    main()
