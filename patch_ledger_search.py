#!/usr/bin/env python3
"""
MF_LEDGER_SEARCH_V1 — credit ledger search and A–Z order.

Cause (search): the search box and the "hide settled" tick box call
  renderLedger(), which returns straight away while any input on the ledger
  page has focus (_ledgerBusy — meant to stop a background sync wiping a form
  being typed in). The box you are typing in IS such an input, so the list
  never redrew. The two filter controls are now exempt; open forms still block.
Order: customers were sorted by who owes most. Now a SORT selector —
  A–Z (default), owes most, oldest unpaid — remembered on the device.
  Search ignores case and spaces ("ravi t" finds "Ravi Transport").
  Customer drop-downs in shift entry sorted A–Z ignoring case too
  (plain .sort() put "Zed" before "arun").

Usage:  python3 patch_ledger_search.py [path/to/index.html]   (idempotent)
Requires MF_LEDGER_V1.
"""
import shutil, subprocess, sys, re, os, tempfile

PATH = sys.argv[1] if len(sys.argv) > 1 else "index.html"
SENTINEL = "MF_LEDGER_SEARCH_V1"

HUNKS = [
("S1 filter controls are not 'busy'",
r"""  if(open)return true;
  const a=document.activeElement;
  return !!(a&&(a.tagName==='INPUT'||a.tagName==='SELECT'||a.tagName==='TEXTAREA')&&""",
r"""  if(open)return true;
  const a=document.activeElement;
  // MF_LEDGER_SEARCH_V1: the list's own filters must redraw it while focused.
  if(a&&(a.id==='led_search'||a.id==='led_hide_settled'||a.id==='led_sort'))return false;
  return !!(a&&(a.tagName==='INPUT'||a.tagName==='SELECT'||a.tagName==='TEXTAREA')&&"""),

("S2 sort selector",
r"""      <input type="text" id="led_search" placeholder="Search customer…" oninput="renderLedger()"
        style="width:180px;height:32px;margin-left:auto">""",
r"""      <input type="text" id="led_search" placeholder="Search customer…" oninput="renderLedger()"
        style="width:180px;height:32px;margin-left:auto">
      <!-- MF_LEDGER_SEARCH_V1 -->
      <select id="led_sort" onchange="try{localStorage.setItem('mf_led_sort',this.value)}catch(e){};renderLedger()"
        style="height:32px;padding:4px 8px;background:var(--bg);border:1px solid var(--border);border-radius:4px;color:var(--text);font-family:'JetBrains Mono',monospace;font-size:11px">
        <option value="az">A → Z</option>
        <option value="owes">Owes most</option>
        <option value="oldest">Oldest unpaid</option>
      </select>"""),

("S3 sort + name compare",
r"""  const names=Object.keys(customers).sort((a,b)=>_bal(b)-_bal(a)||a.localeCompare(b));""",
r"""  // MF_LEDGER_SEARCH_V1: A–Z by default; owes most / oldest unpaid on request
  const _sortEl=document.getElementById('led_sort');
  if(_sortEl&&!_sortEl.dataset.init){ _sortEl.dataset.init='1';
    try{ const _sv=localStorage.getItem('mf_led_sort'); if(_sv)_sortEl.value=_sv; }catch(e){} }
  const _sort=(_sortEl&&_sortEl.value)||'az';
  const _oldest=n=>{ const u=_custUnpaid(n); return u.length?String(u[0].date||''):'9999'; };
  const names=Object.keys(customers).sort((a,b)=>
    _sort==='owes'   ? (_bal(b)-_bal(a)||_nameCmp(a,b)) :
    _sort==='oldest' ? (_oldest(a).localeCompare(_oldest(b))||_nameCmp(a,b)) :
                       _nameCmp(a,b));"""),

("S4 search ignores case and spaces",
r"""    const _match=!_q||name.toLowerCase().indexOf(_q.toLowerCase())>=0;""",
r"""    const _match=!_q||name.toLowerCase().indexOf(_q.trim().toLowerCase())>=0||
      (typeof _normName==='function'&&_normName(name).indexOf(_normName(_q))>=0);   // MF_LEDGER_SEARCH_V1"""),

("S5 name compare helper",
r"""function _ledgerBusy(){""",
r"""// MF_LEDGER_SEARCH_V1: A–Z ignoring case and accents, numbers in order
function _nameCmp(a,b){ return String(a).localeCompare(String(b),'en',{sensitivity:'base',numeric:true}); }
function _ledgerBusy(){"""),

("S6 drop-downs A–Z",
r"""  const names=[...new Set(ledger.map(e=>e.customer))].sort();""",
r"""  const names=[...new Set(ledger.map(e=>e.customer))].sort(_nameCmp);""",
4),

("S7 all-customer list A–Z",
r"""    .filter(Boolean).sort();""",
r"""    .filter(Boolean).sort(_nameCmp);"""),
]


def main():
    if not os.path.exists(PATH):
        sys.exit(f"✗ {PATH} not found")
    src = open(PATH, encoding="utf-8").read()
    if "MF_LEDGER_V1" not in src:
        sys.exit("✗ Apply patch_ledger_hardening.py (MF_LEDGER_V1) first. Nothing written.")
    out = src
    applied = 0
    for h in HUNKS:
        name, old, new = h[0], h[1], h[2]
        want = h[3] if len(h) > 3 else 1
        if new in out and old not in out.replace(new, ""):
            print(f"  = {name}: already applied")
            continue
        n = out.count(old)
        if n != want:
            sys.exit(f"✗ {name}: anchor found {n} times (expected {want}) — file differs from the traced version. Nothing written.")
        out = out.replace(old, new)
        applied += 1
        print(f"  ✓ {name}")
    if applied == 0:
        print("Nothing to do — patch already applied.")
        return
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
