#!/usr/bin/env python3
"""
MF_LEDGER_ORDER_V1 — the customer ledger in date order.

What was wrong: the customer's bill table walked the ledger in reverse ENTRY
order, not date order. A bill typed in late (a back-dated 14/08 entered on
20/09) or a row that arrived from another phone by sync landed wherever it was
appended — so 26/09, 22/09, 14/08, 17/09 … The money itself was fine: payments
are laid across the bills oldest-DATE first, so the figures were right, only
the table read wrong.

NOW
  • Bills sort by date, then shift (morning of a day before its night), then id
    — newest at the top.
  • A divider line per month: bills, credit given and still due in that month.
  • The same order in the full-backup PDF's ledger section (oldest first, as a
    statement reads) and in the oldest-first payment allocation's tie-break.

Usage:  python3 patch_ledger_order.py [path/to/index.html]   (idempotent)
"""
import shutil, subprocess, sys, re, os, tempfile

PATH = sys.argv[1] if len(sys.argv) > 1 else "index.html"
SENTINEL = "MF_LEDGER_ORDER_V1"

HUNKS = [
("1 sort helper",
r"""function openLedgerDetail(name){
  currentLedgerCustomer=name;""",
r"""// MF_LEDGER_ORDER_V1: a ledger row's place in time — its date, then the
// shift (morning of D runs before night of D), then the order it was made.
function _ledCmp(a,b){
  return String(a.date||'').localeCompare(String(b.date||''))||
    ((typeof _shiftRank==='function'?_shiftRank(a.shift)-_shiftRank(b.shift):0))||
    ((a.id||0)-(b.id||0));
}
function _ledMonthLabel(ym){
  const M=['JANUARY','FEBRUARY','MARCH','APRIL','MAY','JUNE','JULY','AUGUST','SEPTEMBER','OCTOBER','NOVEMBER','DECEMBER'];
  const m=parseInt(String(ym).slice(5,7),10);
  return (m>=1&&m<=12?M[m-1]+' ':'')+String(ym).slice(0,4);
}
function openLedgerDetail(name){
  currentLedgerCustomer=name;"""),

("2 detail table newest first, by date, with month lines",
r"""  const tb=document.getElementById('detail_body');tb.innerHTML='';
  entries.slice().reverse().forEach(e=>{
    const isAdvance=e.amount<0;""",
r"""  const tb=document.getElementById('detail_body');tb.innerHTML='';
  // MF_LEDGER_ORDER_V1: newest first by the bill's own date and shift — not by
  // the order rows were typed in or arrived by sync — with a line per month.
  const _sorted=entries.slice().sort((a,b)=>_ledCmp(b,a));
  const _mTot={};
  _sorted.forEach(e=>{ const k=String(e.date||'').slice(0,7), t=_mTot[k]||(_mTot[k]={n:0,given:0,due:0});
    if((e.amount||0)>0){ t.n++; t.given+=e.amount; t.due+=Math.max(0,e.amount-(e.paidBack||0)); } });
  let _lastM=null;
  _sorted.forEach(e=>{
    const _mk=String(e.date||'').slice(0,7);
    if(_mk!==_lastM){
      _lastM=_mk; const t=_mTot[_mk]||{n:0,given:0,due:0};
      const hr=document.createElement('tr'); hr.className='led-month-row';
      hr.innerHTML='<td colspan="8" style="padding:10px 8px 4px;border-bottom:1px solid var(--border);font-family:\'JetBrains Mono\',monospace;font-size:10px;letter-spacing:1px;color:var(--muted)">'+
        '<b style="color:var(--text)">'+_ledMonthLabel(_mk)+'</b>'+
        (t.n?' &middot; '+t.n+' bill'+(t.n!==1?'s':'')+' &middot; &#8377;'+Math.round(t.given).toLocaleString('en-IN')+' given &middot; '+
          (t.due>0.5?'<span style="color:var(--red)">&#8377;'+Math.round(t.due).toLocaleString('en-IN')+' due</span>':'<span style="color:var(--green)">settled</span>'):'')+
        '</td>';
      tb.appendChild(hr);
    }
    const isAdvance=e.amount<0;"""),

("3 backup PDF ledger section oldest first",
r"""      const entries=ledger.filter(e=>e.customer===name);
      const given=entries.reduce((s,e)=>s+e.amount,0);""",
r"""      const entries=ledger.filter(e=>e.customer===name).sort(_ledCmp);   // MF_LEDGER_ORDER_V1
      const given=entries.reduce((s,e)=>s+e.amount,0);"""),

("4 oldest-first allocation tie-break by shift",
r"""  }).sort(function(a,b){
    return String(a.date||'').localeCompare(String(b.date||'')) || ((a.id||0)-(b.id||0));
  });
}
function _custPosition(name){""",
r"""  }).sort(_ledCmp);   // MF_LEDGER_ORDER_V1: same date → morning bill before night
}
function _custPosition(name){"""),
]


def main():
    if not os.path.exists(PATH):
        sys.exit(f"✗ {PATH} not found")
    src = open(PATH, encoding="utf-8").read()
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
