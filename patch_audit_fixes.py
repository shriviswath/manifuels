#!/usr/bin/env python3
"""
MF_AUDIT_FIX_V1 — fixes found in the full-app audit (27 Sep 2026).

 1. Deleting a shift did not undo the credit collected in it. The payment
    stayed on the customer's bills, so re-entering the shift applied it a
    second time (a ₹4,000 payment reduced the balance by ₹8,000).
    -> one routine (_shiftUndoPlan / _applyShiftUndo) undoes everything a save
       did: stock, packs, loose oil, credit given, credit collected, advances
       created, and the payment history rows.
 2. Re-saving an already-saved shift overwrote the shift's numbers but left
    the old credit rows and stock untouched (shift said ₹5,000 credit, ledger
    kept ₹2,000). -> the old entry is undone first, after a confirmation, then
    the new one is applied. Refused, with the reason, if money has since moved
    against the old entry's credit or advance.
 3. Background sync refreshed the dashboard only while the ENTRY page was
    open, so the dashboard showed stale figures; the Reports page never
    refreshed (it called a function that does not exist).
    -> dashboard / reports re-render after every sync, and once after sign-in.
 4. If Chart.js could not load (offline before it was ever cached), the whole
    Reports page, P&L included, crashed. -> charts become optional.

Usage:  python3 patch_audit_fixes.py [path/to/index.html]   (idempotent)
"""
import re, os, sys, shutil, subprocess, tempfile

PATH = sys.argv[1] if len(sys.argv) > 1 else "index.html"
SENTINEL = "MF_AUDIT_FIX_V1"

UNDO_FUNCS = r"""// ── MF_AUDIT_FIX_V1 — undo exactly what a saved shift did ─────────────────
// Credit collected in the shift is found by the ref it was saved with
// (SHIFT-<id>-…) or, for shifts saved before that, by date + "<SHIFT> shift
// collection", which is how every shift collection has always been written.
function _shiftPays(rec){
  const legacyNote=String(rec.shift||'').toUpperCase()+' shift collection';
  return (ledgerPayments||[]).filter(function(p){
    if(!p||p.source!=='shift')return false;
    const ref=String(p.ref||'');
    if(ref.indexOf('SHIFT-'+rec.id+'-')===0)return true;
    return ref.indexOf('SHIFT-')!==0 && p.date===rec.date && p.note===legacyNote;
  });
}
function _shiftUndoPlan(rec){
  const id=rec.id;
  const pays=_shiftPays(rec);
  const own=ledger.filter(function(e){return e.shiftId===id;});
  const credits=own.filter(function(e){return (e.amount||0)>0;});
  const settled=credits.filter(function(e){return (e.paidBack||0)>0.005;});
  const freeCredits=credits.filter(function(e){return !((e.paidBack||0)>0.005);});
  // Advances this shift created: tagged with the shift id, or (older saves)
  // the matching "Excess payment" row for the same customer, date and shift.
  const advRows=[];
  pays.filter(function(p){return p.kind==='advance';}).forEach(function(p){
    const a=ledger.find(function(e){
      if(advRows.indexOf(e)>=0||!((e.amount||0)<0)||e.customer!==p.customer)return false;
      if(e.shiftId===id)return true;
      return !e.shiftId&&e.date===rec.date&&e.shift===rec.shift&&
             Math.abs((e.amount||0)+(p.amount||0))<0.01&&/Excess payment/.test(e.notes||'');
    });
    if(a)advRows.push(a);
  });
  own.filter(function(e){return (e.amount||0)<0;}).forEach(function(e){if(advRows.indexOf(e)<0)advRows.push(e);});
  const usedAdv=advRows.filter(function(e){return (e.paidBack||0)>0.005;});
  const billPays=pays.filter(function(p){return p.kind!=='advance'&&p.ledgerId!=null;});
  const payTotal=pays.reduce(function(s,p){return s+(p.amount||0);},0);
  const lines=[], blocked=[];
  if(rec.stockSold&&rec.stockSold.length)lines.push(rec.stockSold.length+' stock line(s) returned to inventory');
  if(rec.ps)lines.push(rec.ps+' pack(s) returned');
  if(Array.isArray(rec.looseOpened)&&rec.looseOpened.length)
    lines.push(rec.looseOpened.map(function(o){return o.qty+' × '+o.name;}).join(', ')+' returned to stock');
  else if(rec.looseOilUnits)lines.push(rec.looseOilUnits+' loose-oil bottle(s) returned to stock');
  if(freeCredits.length)lines.push(freeCredits.length+' credit entry(ies) removed ('+
    fmt(freeCredits.reduce(function(s,e){return s+(e.amount||0);},0))+')');
  if(pays.length)lines.push('credit collected in this shift ('+fmt(payTotal)+') taken back off the customers\' bills');
  settled.forEach(function(e){blocked.push('credit of '+fmt(e.amount)+' to '+e.customer+' has already been paid '+fmt(e.paidBack));});
  usedAdv.forEach(function(e){blocked.push('advance of '+fmt(Math.abs(e.amount))+' from '+e.customer+' has already been used');});
  return {rec:rec, pays:pays, billPays:billPays, freeCredits:freeCredits,
          advRows:advRows.filter(function(e){return usedAdv.indexOf(e)<0;}), lines:lines, blocked:blocked};
}
function _applyShiftUndo(plan){
  const rec=plan.rec;
  // 1. counter stock back
  (rec.stockSold||[]).forEach(function(it){
    const item=stock.find(x=>String(x.id)===String(it.id));
    if(item)item.qty=Math.round((item.qty+(parseFloat(it.qty)||0))*1000)/1000;
  });
  // 2. 40 ml packs back
  if(rec.ps>0){
    const pouch40=stock.find(x=>x.name.toLowerCase().includes('40')&&x.name.toLowerCase().includes('ml')&&
      (x.name.toLowerCase().includes('pouch')||x.name.toLowerCase().includes('pack')));
    if(pouch40)pouch40.qty=Math.round((pouch40.qty+rec.ps)*1000)/1000;
  }
  // 3. loose oil back — each bottle onto the shelf it came off
  if(Array.isArray(rec.looseOpened)&&rec.looseOpened.length){
    rec.looseOpened.forEach(function(o){
      const src=stock.find(x=>String(x.id)===String(o.id));
      if(src)src.qty=Math.max(0,Math.round(src.qty)+Math.round(o.qty||0));
    });
  } else if(rec.os>0&&rec.looseOilUnits>0){
    const cfg=_looseOilCfg();
    const src=cfg.stockId?stock.find(x=>String(x.id)===cfg.stockId):null;
    if(src)src.qty=Math.max(0,Math.round(src.qty)+Math.round(rec.looseOilUnits));
  }
  if(rec.stockSold||rec.ps||rec.os)saveStockLS();
  // 4. credit collected in the shift comes back off the bills it settled
  let billsTouched=0;
  plan.billPays.forEach(function(p){
    const bill=ledger.find(function(e){return String(_intId(e.id))===String(_intId(p.ledgerId));});
    if(!bill)return;
    bill.paidBack=_r2(Math.max(0,(bill.paidBack||0)-(p.amount||0)));
    billsTouched++;
    if(_currentUser)sbSaveLedgerEntry(bill).catch(console.error);
  });
  // 5. credit given in the shift, and advances it created
  const drop=new Set(plan.freeCredits.concat(plan.advRows).map(function(e){return String(e.id);}));
  if(drop.size){
    ledger=ledger.filter(function(e){return !drop.has(String(e.id));});
    if(_currentUser)drop.forEach(function(i){sbDeleteLedgerEntry(i).catch(console.error);});
  }
  // 6. the payment history rows go too
  if(plan.pays.length){
    const pid=new Set(plan.pays.map(function(p){return String(p.id);}));
    ledgerPayments=ledgerPayments.filter(function(p){return !pid.has(String(p.id));});
    savePaymentsLS();
    if(_currentUser&&MF_PAYTBL_OK)plan.pays.forEach(function(p){sbDelete('ledger_payments',_intId(p.id)).catch(console.error);});
  }
  if(billsTouched||drop.size)saveLedger();
  refreshCreditSelects();refreshCredBackSelects();
  return {ledgerRemoved:drop.size, billsTouched:billsTouched, pays:plan.pays.length};
}
function delRec(id){"""

DELREC_OLD_START = "  // Everything the save did has to be undone, or stock stays deducted and the\n  // customer still owes money for a shift that no longer exists.\n"
DELREC_OLD_END = "    refreshCreditSelects();refreshCredBackSelects();\n  }\n\n  records=records.filter(r=>r.id!==id);"
DELREC_NEW = """  // MF_AUDIT_FIX_V1 — one routine undoes everything the save did, including the
  // credit collected in the shift. That used to stay on the bills, so entering
  // the shift again applied the same payment twice.
  const _up=_shiftUndoPlan(rec);
  const lines=_up.lines.concat(_up.blocked.map(function(b){return '⚠ '+b+' — left as it is';}));
  if(lines.length&&!confirm('Deleting '+id+' will also:\\n\\n• '+lines.join('\\n• ')+'\\n\\nContinue?'))return;
  const _res=_applyShiftUndo(_up);

  records=records.filter(r=>r.id!==id);"""

HUNKS = [
 ("save: undo the old entry before re-saving",
  "  const _isResave=records.findIndex(r=>r.id===_shiftIdStr)>=0;\n",
  """  // MF_AUDIT_FIX_V1 — re-saving a saved shift used to overwrite its numbers
  // while its old credit rows and stock deductions stayed, so the shift and the
  // ledger disagreed. The old entry is now undone first, then this one applied.
  const _prevRec=records.find(r=>r.id===_shiftIdStr);
  if(_prevRec){
    const _up=_shiftUndoPlan(_prevRec);
    if(_up.blocked.length){
      alert(_shiftIdStr+' is already saved and cannot be replaced, because money has moved since:\\n\\n• '+
        _up.blocked.join('\\n• ')+'\\n\\nCorrect it in the Credit Ledger instead, or delete the shift in History first.');
      return;
    }
    if(!confirm(_shiftIdStr+' is already saved.\\n\\nReplace it with what is on screen now? The saved entry is undone first:\\n\\n• '+
      (_up.lines.length?_up.lines.join('\\n• '):'(nothing else to undo)')+'\\n\\nthen this entry is applied as new.'))return;
    _applyShiftUndo(_up);
  }
  const _isResave=false;   // the old entry's effects were undone above
"""),
 ("save: tag shift collections with the shift id",
  "note:shift.toUpperCase()+' shift collection', ref:'PAY-'+_newId(), source:'shift'});",
  "note:shift.toUpperCase()+' shift collection', ref:'SHIFT-'+_shiftIdStr+'-'+_newId(), source:'shift'});"),
 ("save: tag advances with the shift id",
  "          notes:'Excess payment carried forward as advance'};",
  "          notes:'Excess payment carried forward as advance',shiftId:_shiftIdStr};"),
 ("delRec: activity log uses the undo result",
  "'Deleted shift + reversed '+((rec.stockSold||[]).length)+' stock line(s), '+removable.length+' ledger row(s)');",
  "'Deleted shift + reversed '+((rec.stockSold||[]).length)+' stock line(s), '+_res.ledgerRemoved+' ledger row(s), '+_res.pays+' collection(s)');"),
 ("sync: refresh the dashboard (was keyed to the entry page)",
  "      if(pid==='entry'   && typeof renderDashboard==='function')  renderDashboard();",
  "      if(pid==='dashboard' && typeof renderDashboard==='function') renderDashboard();   // MF_AUDIT_FIX_V1: was 'entry'"),
 ("sync: refresh reports (called a function that does not exist)",
  "      if(pid==='report'  && typeof renderReport==='function')     renderReport();",
  "      if(pid==='report'  && typeof genReport==='function' && (document.getElementById('rep_from')||{}).value) genReport();"),
 ("sign-in: draw the dashboard once the first sync lands",
  "loadAllFromSupabase().then(function(){ if(typeof initMultiDeviceSync==='function') initMultiDeviceSync(); });",
  "loadAllFromSupabase().then(function(){ if(typeof initMultiDeviceSync==='function') initMultiDeviceSync(); if(typeof renderDashboard==='function'&&document.getElementById('page-dashboard')&&document.getElementById('page-dashboard').classList.contains('active')) renderDashboard(); });"),
 ("charts optional when Chart.js failed to load",
  "<script>\nvar _currentUser=null,_isOwner=false,_supa=null,_syncInProgress=false;",
  "<script>\n// MF_AUDIT_FIX_V1: Chart.js comes from a CDN. If it never loaded (offline before\n// it was cached) every page that draws a chart crashed, the P&L included.\nif(typeof Chart==='undefined'){window.Chart=function(){return {destroy:function(){},update:function(){},resize:function(){}};};window.Chart.__stub=true;}\nvar _currentUser=null,_isOwner=false,_supa=null,_syncInProgress=false;"),
]


def main():
    src = open(PATH, encoding="utf-8").read()
    if SENTINEL in src and "function _shiftUndoPlan" in src:
        print("Nothing to do — MF_AUDIT_FIX_V1 already applied."); return
    out = src
    # delRec body + new functions
    if out.count("function delRec(id){") != 1: sys.exit("✗ delRec not found once")
    a = out.find(DELREC_OLD_START); b = out.find(DELREC_OLD_END)
    if a < 0 or b < 0 or b < a: sys.exit("✗ delRec body anchors not found — nothing written")
    out = out[:a] + DELREC_NEW + out[b + len(DELREC_OLD_END):]
    out = out.replace("function delRec(id){", UNDO_FUNCS, 1)
    print("  ✓ delRec: full undo incl. credit collected; undo routine added")
    for name, old, new in HUNKS:
        n = out.count(old)
        if n != 1: sys.exit(f"✗ {name}: anchor found {n} times — nothing written")
        out = out.replace(old, new); print("  ✓", name)
    scripts = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", out, flags=re.S | re.I)
    with tempfile.TemporaryDirectory() as td:
        for i, js in enumerate(scripts):
            p = os.path.join(td, f"s{i}.js"); open(p, "w", encoding="utf-8").write(js)
            r = subprocess.run(["node", "--check", p], capture_output=True, text=True)
            if r.returncode: sys.exit(f"✗ node --check failed on script #{i}:\n{r.stderr}\nNothing written.")
    shutil.copyfile(PATH, PATH + ".bak")
    open(PATH, "w", encoding="utf-8").write(out)
    print(f"✓ {SENTINEL} applied; node --check passed on {len(scripts)} script(s); backup {PATH}.bak")


if __name__ == "__main__":
    main()
