#!/usr/bin/env python3
"""
MF_OPENING_SLOT_V1 — opening stock "as of" needs a time of day; pack openings
carry forward for every pack size.

Problem 1 — Live tank stock
  MF_TANK_PACK_V1 dated the opening stock at the START of the day (before the
  Morning shift). Measured on 28-09 after the Morning shift had closed, the
  dashboard still took that Morning shift (MSD 409 L, HSD 643 L) off the
  figure you measured: 5,915 − 409 = 5,505. Nothing moves again until the
  next shift is saved, so it looked stuck on the wrong number.
  Fix: an "at" selector next to the date, the same three points the Dip page
  uses: before the Morning shift (6 PM the day before) / after the Morning
  shift (9 AM) / after the Night shift (6 PM).

  O1 bookStock      : use the chosen point instead of always "start of day".
  O2 UI             : "at" select beside OPENING AS OF.
  O3 setOpeningAsOfSlot(): first set allowed while locked (like the date),
                      changing it later needs the owner unlock; logged.
  O4 lock / sync / boot restore for the new setting (app_settings.config,
                      no schema change).

Problem 2 — CARRY OPENING for pack oil
  The 40 ml opening only carries from a shift saved with the new build (older
  shifts never stored the closing count), and 20 / 30 ml etc. never carried.
  P1 save           : every enabled pack size's opening/closing rides in
                      meters.packs (jsonb).
  P2 carry forward  : fills each pack size's opening from its last closing.
  P3 continuity     : warns on save when a pack opening does not match the
                      last closing (missing packs show up here).

Usage:  python3 patch_opening_slot_packs.py [path/to/index.html]
Idempotent: re-running reports every hunk as already applied.
"""
import shutil, subprocess, sys, re, os, tempfile

PATH = sys.argv[1] if len(sys.argv) > 1 else "index.html"
SENTINEL = "MF_OPENING_SLOT_V1"

HUNKS = [
("O1 bookStock: opening at a chosen point in the day",
"""  var _asOf=_openingAsOf();
  if(_asOf){
    var _opV=(type==='MSD'?(fuelOpeningMSD||0):(fuelOpeningHSD||0));
    var _opP={date:_asOf,rank:0};
    // The opening measurement wins over any dip taken before it.
    if(_posCmp(_asOf,0,date,rank)<0 &&
       (!anchor||_posCmp(_asOf,0,anchor.date,_slotRank(anchor.slot))>0)){
      var _mo=_tankMovement(type,_opP,{date:date,rank:rank});
      return {open:_opV,loaded:_mo.loaded,sold:_mo.sold,tested:_mo.tested,
              book:_opV+_mo.loaded-_mo.sold+_mo.tested,anchor:null,since:'opening '+_asOf};
    }
    if(!anchor){
      // A point at or before the opening date: count backwards from it.
      var _mb=_tankMovement(type,{date:date,rank:rank},_opP);
      return {open:_opV,loaded:-_mb.loaded,sold:-_mb.sold,tested:-_mb.tested,
              book:_opV-_mb.loaded+_mb.sold-_mb.tested,anchor:null,since:'opening '+_asOf};
    }
  }""",
"""  var _asOf=_openingAsOf();
  if(_asOf){
    var _opV=(type==='MSD'?(fuelOpeningMSD||0):(fuelOpeningHSD||0));
    // MF_OPENING_SLOT_V1: the opening sits at the point in the day it was
    // measured, not always before the Morning shift.
    var _opS=_openingAsOfSlot(), _opR=_slotRank(_opS);
    var _opP={date:_asOf,rank:_opR};
    var _opL='opening '+_asOf+(_opS==='mid'?' 9 AM':(_opS==='close'?' 6 PM':''));
    // The opening measurement wins over any dip taken before it.
    if(_posCmp(_asOf,_opR,date,rank)<0 &&
       (!anchor||_posCmp(_asOf,_opR,anchor.date,_slotRank(anchor.slot))>0)){
      var _mo=_tankMovement(type,_opP,{date:date,rank:rank});
      return {open:_opV,loaded:_mo.loaded,sold:_mo.sold,tested:_mo.tested,
              book:_opV+_mo.loaded-_mo.sold+_mo.tested,anchor:null,since:_opL};
    }
    if(!anchor){
      // A point at or before the opening: count backwards from it.
      var _mb=_tankMovement(type,{date:date,rank:rank},_opP);
      return {open:_opV,loaded:-_mb.loaded,sold:-_mb.sold,tested:-_mb.tested,
              book:_opV-_mb.loaded+_mb.sold-_mb.tested,anchor:null,since:_opL};
    }
  }"""),

("O1b _openingAsOfSlot()",
"""function _openingAsOf(){
  var d=localStorage.getItem('fuelOpeningAsOf')||'';
  return /^\\d{4}-\\d{2}-\\d{2}$/.test(d)?d:'';
}""",
"""function _openingAsOf(){
  var d=localStorage.getItem('fuelOpeningAsOf')||'';
  return /^\\d{4}-\\d{2}-\\d{2}$/.test(d)?d:'';
}
// MF_OPENING_SLOT_V1: open = before the Morning shift (6 PM the day before),
// mid = after the Morning shift (9 AM), close = after the Night shift (6 PM).
function _openingAsOfSlot(){
  var s=localStorage.getItem('fuelOpeningAsOfSlot')||'open';
  return (s==='mid'||s==='close')?s:'open';
}"""),

("O2 UI: 'at' selector",
"""      <input type="date" id="opening_asof" onchange="setOpeningAsOf(this.value)" style="width:170px">""",
"""      <input type="date" id="opening_asof" onchange="setOpeningAsOf(this.value)" style="width:170px">
      <!-- MF_OPENING_SLOT_V1 -->
      <select id="opening_asof_slot" onchange="setOpeningAsOfSlot(this.value)" style="width:auto;padding:5px 9px;background:var(--bg);border:1px solid var(--border);border-radius:4px;color:var(--text);font-family:'JetBrains Mono',monospace;font-size:12px">
        <option value="open">before Morning shift (6 PM, day before)</option>
        <option value="mid">after Morning shift (9 AM)</option>
        <option value="close">after Night shift (6 PM)</option>
      </select>"""),

("O2b UI: help text",
"""        The date those litres were measured — stock at the start of that date's Morning shift (6 PM the evening before).
        Shifts dated before it are not taken off the tank again. A dip taken later always overrides this.""",
"""        When those litres were measured. Only shifts saved after that point are taken off the tank.
        Measured in the afternoon? Pick “after Morning shift”. A dip taken later always overrides this."""),

("O3 setOpeningAsOfSlot()",
"""function saveOpeningNow(){""",
"""// MF_OPENING_SLOT_V1: same rule as the date — the first set is allowed while
// locked, changing it afterwards needs the owner unlock.
function setOpeningAsOfSlot(val){
  var had=localStorage.getItem('fuelOpeningAsOfSlot')!=null, cur=_openingAsOfSlot();
  var e=document.getElementById('opening_asof_slot');
  var s=(val==='mid'||val==='close')?val:'open';
  if(s===cur&&had)return;
  if(openingLocked()&&had){
    showToast('🔒 Unlock the opening stock to change when it was measured');
    if(e)e.value=cur; return;
  }
  localStorage.setItem('fuelOpeningAsOfSlot',s);
  var lbl={open:'before Morning shift',mid:'after Morning shift (9 AM)',close:'after Night shift (6 PM)'};
  if(typeof logActivity==='function')logActivity('opening_asof','settings','opening',
    'Opening stock measured '+lbl[s]+(had?' (was '+lbl[cur]+')':''));
  saveOpeningNow();
  applyOpeningLock();
  if(typeof renderFuelLoads==='function')renderFuelLoads();
  if(typeof renderDashTanks==='function'&&document.getElementById('dashFuelTanks'))renderDashTanks();
  showToast('✓ Opening stock measured '+lbl[s]);
}
function saveOpeningNow(){"""),

("O4 lock: slot selector",
"""    _ao.title=_lk?'Locked. An owner can unlock it.':'';
  }""",
"""    _ao.title=_lk?'Locked. An owner can unlock it.':'';
  }
  const _as=document.getElementById('opening_asof_slot');   // MF_OPENING_SLOT_V1
  if(_as){
    const _lk2=locked&&localStorage.getItem('fuelOpeningAsOfSlot')!=null;
    _as.disabled=_lk2; _as.style.opacity=_lk2?'.55':'';
    _as.title=_lk2?'Locked. An owner can unlock it.':'';
  }"""),

("O4b sync out",
"""    openingAsOf: localStorage.getItem('fuelOpeningAsOf')||'',   // MF_TANK_PACK_V1""",
"""    openingAsOf: localStorage.getItem('fuelOpeningAsOf')||'',   // MF_TANK_PACK_V1
    openingAsOfSlot: localStorage.getItem('fuelOpeningAsOfSlot'),   // MF_OPENING_SLOT_V1 (null = never set)"""),

("O4c sync in",
"""    _setInputIfIdle('opening_asof',cfg.openingAsOf||'');
  }""",
"""    _setInputIfIdle('opening_asof',cfg.openingAsOf||'');
  }
  if(cfg.openingAsOfSlot!=null){   // MF_OPENING_SLOT_V1
    localStorage.setItem('fuelOpeningAsOfSlot',cfg.openingAsOfSlot);
    _setInputIfIdle('opening_asof_slot',cfg.openingAsOfSlot);
  }"""),

("O4d boot restore",
"""  if(_ae&&_ao)_ae.value=_ao; }""",
"""  if(_ae&&_ao)_ae.value=_ao;
  const _se=document.getElementById('opening_asof_slot');   // MF_OPENING_SLOT_V1
  if(_se)_se.value=(typeof _openingAsOfSlot==='function')?_openingAsOfSlot():(localStorage.getItem('fuelOpeningAsOfSlot')||'open'); }"""),

# ───────────── pack oil carry-forward ─────────────
("P1 save: every pack size's readings",
"""            pack_prev:_vn('pack_prev'), pack_cur:_vn('pack_cur'), pack_units:c.packUnits||0,""",
"""            pack_prev:_vn('pack_prev'), pack_cur:_vn('pack_cur'), pack_units:c.packUnits||0,
            packs:_packExtraReadings(),   // MF_OPENING_SLOT_V1: 20 / 30 ml … by size"""),

("P1b helpers",
"""// Closing packs of the shift before this one, for the carry-forward.
function _lastPackClose(){""",
"""// MF_OPENING_SLOT_V1: opening/closing for every enabled extra pack size.
function _packExtraReadings(){
  var o={};
  (typeof packSizesConfig!=='undefined'?packSizesConfig:[]).filter(function(p){return p.enabled;}).forEach(function(p){
    var a=_vn('pack'+p.size+'_prev'), b=_vn('pack'+p.size+'_cur');
    if(a!=null||b!=null)o[p.size]={prev:a,cur:b};
  });
  return o;
}
// Last saved closing count for one extra pack size.
function _lastPackCloseFor(size){
  const d=document.getElementById('shiftDate')?.value||'';
  const prior=records.filter(r=>r.meters&&r.meters.packs&&r.meters.packs[size]&&r.meters.packs[size].cur!=null&&
      (r.date<d||(r.date===d&&r.shift!==shift)))
    .sort((a,b)=>String(b.date).localeCompare(String(a.date))||
      (b.shift==='night'?1:-1)-(a.shift==='night'?1:-1));
  return prior.length?parseFloat(prior[0].meters.packs[size].cur):null;
}
// Closing packs of the shift before this one, for the carry-forward.
function _lastPackClose(){"""),

("P2 carry forward: all pack sizes",
"""    if(_pe&&isFinite(_pv)&&(silent?!_pe.value:true)){_pe.value=_pv;n++;}
  }""",
"""    if(_pe&&isFinite(_pv)&&(silent?!_pe.value:true)){_pe.value=_pv;n++;}
  }
  // MF_OPENING_SLOT_V1: the other pack sizes too.
  (typeof packSizesConfig!=='undefined'?packSizesConfig:[]).filter(function(p){return p.enabled;}).forEach(function(p){
    const cv=_lastPackCloseFor(p.size), el=document.getElementById('pack'+p.size+'_prev');
    if(el&&cv!=null&&isFinite(cv)&&(silent?!el.value:true)){el.value=cv;n++;}
  });"""),

("P3 continuity: pack openings",
"""  return issues;
}

// Pull last shift's closing readings into this shift's opening fields.""",
"""  // MF_OPENING_SLOT_V1: packs on the counter should carry over exactly too —
  // a gap here is packs that left without being sold.
  const _chk=function(label,expected,entered){
    if(expected==null||!isFinite(expected)||entered==null)return;
    const gap=entered-expected;
    if(Math.abs(gap)>=1)issues.push({level:'warn',machine:label,
      msg:'Opening '+entered+' packs does not follow the last closing '+expected+' ('+(gap>0?'+':'')+gap+' packs)'});
  };
  const _p40=(typeof _lastPackClose==='function')?_lastPackClose():null;
  if(_p40)_chk('40 ml packs',parseFloat(_p40.meters.pack_cur),_vn('pack_prev'));
  (typeof packSizesConfig!=='undefined'?packSizesConfig:[]).filter(function(p){return p.enabled;}).forEach(function(p){
    _chk(p.size+' ml packs',_lastPackCloseFor(p.size),_vn('pack'+p.size+'_prev'));
  });
  return issues;
}

// Pull last shift's closing readings into this shift's opening fields."""),
]


def main():
    if not os.path.exists(PATH):
        sys.exit(f"✗ {PATH} not found")
    src = open(PATH, encoding="utf-8").read()
    if "MF_TANK_PACK_V1" not in src:
        sys.exit("✗ Apply patch_tank_packs.py (MF_TANK_PACK_V1) first. Nothing written.")
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
