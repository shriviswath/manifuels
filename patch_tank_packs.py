#!/usr/bin/env python3
"""
MF_TANK_PACK_V1 — live tank stock reads wrong; 40 ml packs opened mid-shift.

1) LIVE TANK STOCK (MSD + HSD)
   Cause A — opening stock had no date. The card says "petrol in the tank right
     now", but bookStock() subtracted EVERY shift ever recorded from it,
     including all the shifts before the day it was measured. Book stock went
     negative and the dashboard clamped it to "0.0 L / 0%" with no reason given.
   Cause B — tankers were placed at the start of their day (rank 1). Tankers
     arrive in daylight = the Night shift (D 9 AM - 6 PM). With a Shift-change
     dip that day, the load counted as "before the dip" and vanished from the
     book for good (and the next dip showed a fake OVER of a whole tanker).
   Cause C — the dashboard hid negative/over-capacity figures instead of
     saying what was wrong.

   T1 bookStock   : opening stock gets an "as of" date and acts like a dip at
                    the start of that date; shifts before it are not subtracted.
   T2 _tankMovement: tanker counts during the day shift (rank 1.5).
   T3 dashboard   : real figure, the working (opening + in - out + test), and a
                    plain-language warning when it is < 0 or > capacity.
   T4-T8          : "OPENING AS OF" date on the Fuel Loads opening card, synced
                    through app_settings.config (no schema change), restored at
                    boot, locked with the opening lock once set, logged.
   T9 forecast    : note still fires for a dated opening.

2) 40 ML PACKS — 6 units per box, 40 packs per unit
   P1 shift entry : "Units opened (40 packs each)" + live working line.
   P2 helpers     : PACK40_PER_UNIT / PACK40_UNITS_PER_BOX, _pack40Added(),
                    _pack40Hint(), _lastPackClose().
   P3 calc() and getCalcVals(): sold = opening + units x 40 - closing.
   P4-P6 save     : pack_prev / pack_cur / pack_units ride in `meters` (jsonb,
                    no schema change); units box cleared after save.
   P7 carry fwd   : last shift's closing packs -> this shift's opening.
   P8 stock hint  : "after this shift" figure includes units opened.
   P9 history     : shift detail shows "1 unit opened".
   P10 register   : purchase preview shows boxes / units for 40 ml.

   Opening a unit only moves packs from the box to the counter. It is NOT a
   sale and does not touch the Pack Register balance; only packs sold do.

Usage:  python3 patch_tank_packs.py [path/to/index.html]
Idempotent: re-running reports every hunk as already applied.
"""
import shutil, subprocess, sys, re, os, tempfile

PATH = sys.argv[1] if len(sys.argv) > 1 else "index.html"
SENTINEL = "MF_TANK_PACK_V1"

# (name, old, new[, expected_count])
HUNKS = [
# ───────────────────────────── TANK ─────────────────────────────
("T1 bookStock: dated opening acts as an anchor",
"""function bookStock(type,date,slot){
  var rank=_slotRank(slot);
  var anchor=_anchorDip(type,date,rank);""",
"""// MF_TANK_PACK_V1: opening stock is a measurement taken at a point in time,
// exactly like a dip. Without that point every shift ever recorded was taken
// off it — including the ones before it was measured — and the tank read
// negative. Stored as a date; the stock is as at the start of that date's
// Morning shift (6 PM the evening before).
function _openingAsOf(){
  var d=localStorage.getItem('fuelOpeningAsOf')||'';
  return /^\\d{4}-\\d{2}-\\d{2}$/.test(d)?d:'';
}
function bookStock(type,date,slot){
  var rank=_slotRank(slot);
  var anchor=_anchorDip(type,date,rank);
  var _asOf=_openingAsOf();
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
  }"""),

("T2 _tankMovement: tanker lands in the day shift",
"""    // A tanker has no clock time, so it counts from the first shift of its day.
    var lr=1;""",
"""    // MF_TANK_PACK_V1: a tanker has no clock time. Tankers come in daylight,
    // which at this station is the Night shift (D 9 AM - 6 PM). At rank 1 a
    // load after a Shift-change dip counted as before it and was lost from the
    // book for good. 1.5 = during the day shift.
    var lr=1.5;"""),

("T3 dashboard: real figure, working and warning",
"""  const bMSD = tankLevel('MSD'), bHSD = tankLevel('HSD');
  const liveMSD = Math.max(0, bMSD.book);
  const liveHSD = Math.max(0, bHSD.book);

  const pctMSD = CAP_MSD ? Math.min(100,(liveMSD/CAP_MSD)*100) : 0;
  const pctHSD = CAP_HSD ? Math.min(100,(liveHSD/CAP_HSD)*100) : 0;

  document.getElementById('dashFuelTanks').innerHTML = `
    <div class="fuel-tank">
      <div class="fuel-tank-top">
        <span class="fuel-tank-name" style="color:var(--petrol)">● MSD (Petrol)</span>
        <span class="fuel-tank-vol" style="color:var(--petrol)">${liveMSD.toFixed(1)} L</span>
      </div>
      <div class="fuel-tank-bar"><div class="fuel-tank-fill msd" style="width:${pctMSD}%"></div></div>
      <div style="font-family:'JetBrains Mono',monospace;font-size:9px;color:var(--muted);margin-top:4px">${pctMSD.toFixed(0)}% of ${CAP_MSD}L • today ${dispMSD.toFixed(1)}L • since ${bMSD.since}</div>
    </div>
    <div class="fuel-tank">
      <div class="fuel-tank-top">
        <span class="fuel-tank-name" style="color:var(--diesel)">● HSD (Diesel)</span>
        <span class="fuel-tank-vol" style="color:var(--diesel)">${liveHSD.toFixed(1)} L</span>
      </div>
      <div class="fuel-tank-bar"><div class="fuel-tank-fill hsd" style="width:${pctHSD}%"></div></div>
      <div style="font-family:'JetBrains Mono',monospace;font-size:9px;color:var(--muted);margin-top:4px">${pctHSD.toFixed(0)}% of ${CAP_HSD}L • today ${dispHSD.toFixed(1)}L • since ${bHSD.since}</div>
    </div>
  `;""",
"""  const bMSD = tankLevel('MSD'), bHSD = tankLevel('HSD');
  // MF_TANK_PACK_V1: show the real book figure. Clamping a negative to 0 hid
  // the fault — the card read "0.0 L" with nothing to say why.
  const firstShift = records.reduce((m,r)=>(r.date&&(!m||String(r.date)<m))?String(r.date):m,'');
  const nf = (n,d)=>Number(n||0).toLocaleString('en-IN',{maximumFractionDigits:d||0});
  const tankRow = (name,col,cls,b,cap,disp)=>{
    const lvl=b.book, pct=cap?Math.min(100,Math.max(0,(lvl/cap)*100)):0;
    const bad = lvl<0 || (cap>0 && lvl>cap*1.02);
    let warn='';
    if(bad){
      const why = lvl<0
        ? (b.since==='opening stock'
            ? 'The opening figure has no date, so every shift since '+(firstShift||'the first record')+
              ' is being taken off it. Set “Opening as of” on Fuel Loads, or record a dip.'
            : 'More fuel metered out than the book holds — a tanker is missing from Fuel Loads, or the '+
              b.since+' figure is wrong.')
        : 'Above tank capacity — a load entered twice, or the '+b.since+' figure is too high.';
      warn='<div style="font-size:10px;color:var(--red);margin-top:4px;line-height:1.5">⚠ '+_esc(why)+'</div>';
    }
    return `
    <div class="fuel-tank">
      <div class="fuel-tank-top">
        <span class="fuel-tank-name" style="color:${col}">● ${name}</span>
        <span class="fuel-tank-vol" style="color:${bad?'var(--red)':col}">${nf(lvl,1)} L</span>
      </div>
      <div class="fuel-tank-bar"><div class="fuel-tank-fill ${cls}" style="width:${pct}%"></div></div>
      <div style="font-family:'JetBrains Mono',monospace;font-size:9px;color:var(--muted);margin-top:4px;line-height:1.6">${pct.toFixed(0)}% of ${nf(cap)} L • today ${nf(disp,1)} L<br>${_esc(b.since)}: ${nf(b.open)} + in ${nf(b.loaded)} − out ${nf(b.sold)}${b.tested?' + test '+nf(b.tested,1):''}</div>
      ${warn}
    </div>`;
  };
  document.getElementById('dashFuelTanks').innerHTML =
    tankRow('MSD (Petrol)','var(--petrol)','msd',bMSD,CAP_MSD,dispMSD)+
    tankRow('HSD (Diesel)','var(--diesel)','hsd',bHSD,CAP_HSD,dispHSD);"""),

("T4 opening card: 'as of' date input",
"""        <div style="font-size:10px;color:var(--muted);margin-top:3px">What that diesel cost you, per litre</div>
      </div>
    </div>""",
"""        <div style="font-size:10px;color:var(--muted);margin-top:3px">What that diesel cost you, per litre</div>
      </div>
    </div>
    <!-- MF_TANK_PACK_V1 -->
    <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:8px">
      <div class="flabel" style="margin:0;color:var(--petrol)">OPENING AS OF</div>
      <input type="date" id="opening_asof" onchange="setOpeningAsOf(this.value)" style="width:170px">
      <div style="font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--muted);flex:1;min-width:220px;line-height:1.5">
        The date those litres were measured — stock at the start of that date's Morning shift (6 PM the evening before).
        Shifts dated before it are not taken off the tank again. A dip taken later always overrides this.
      </div>
    </div>"""),

("T4b opening card: labels",
"""<div style="font-size:10px;color:var(--muted);margin-top:3px">Petrol in the tank right now</div>""",
"""<div style="font-size:10px;color:var(--muted);margin-top:3px">Petrol in the tank on the “as of” date</div>"""),

("T4c opening card: labels",
"""<div style="font-size:10px;color:var(--muted);margin-top:3px">Diesel in the tank right now</div>""",
"""<div style="font-size:10px;color:var(--muted);margin-top:3px">Diesel in the tank on the “as of” date</div>"""),

("T5 setOpeningAsOf()",
"""function saveOpeningNow(){""",
"""// MF_TANK_PACK_V1: date the opening stock. Setting it the first time is
// allowed while locked (it only fixes a missing fact); changing it after that
// moves every tank figure, so it needs the owner unlock like the volume does.
function setOpeningAsOf(val){
  var cur=_openingAsOf();
  var e=document.getElementById('opening_asof');
  if(openingLocked()&&cur){
    showToast('🔒 Unlock the opening stock to change its date');
    if(e)e.value=cur; return;
  }
  var d=/^\\d{4}-\\d{2}-\\d{2}$/.test(val||'')?val:'';
  if(d===cur)return;
  localStorage.setItem('fuelOpeningAsOf',d);
  if(typeof logActivity==='function')logActivity('opening_asof','settings','opening',
    'Opening stock dated '+(d||'(cleared)')+(cur?' (was '+cur+')':''));
  saveOpeningNow();
  applyOpeningLock();
  if(typeof renderFuelLoads==='function')renderFuelLoads();
  if(typeof renderDashTanks==='function'&&document.getElementById('dashFuelTanks'))renderDashTanks();
  showToast(d?'✓ Opening stock dated '+d:'Opening date cleared');
}
function saveOpeningNow(){"""),

("T6 applyOpeningLock: lock the date once set",
"""  const b=document.getElementById('opening_lock_badge');
  if(b){
    b.textContent=locked?'🔒 LOCKED':'✎ EDITABLE';""",
"""  const _ao=document.getElementById('opening_asof');   // MF_TANK_PACK_V1
  if(_ao){
    const _lk=locked&&(typeof _openingAsOf==='function')&&!!_openingAsOf();
    _ao.disabled=_lk; _ao.style.opacity=_lk?'.55':'';
    _ao.title=_lk?'Locked. An owner can unlock it.':'';
  }
  const b=document.getElementById('opening_lock_badge');
  if(b){
    b.textContent=locked?'🔒 LOCKED':'✎ EDITABLE';"""),

("T7 _deviceConfig: sync the date",
"""    openingLocked: localStorage.getItem('fuelOpeningLocked')==='1',""",
"""    openingLocked: localStorage.getItem('fuelOpeningLocked')==='1',
    openingAsOf: localStorage.getItem('fuelOpeningAsOf')||'',   // MF_TANK_PACK_V1"""),

("T7b _applyDeviceConfig: receive the date",
"""  if(cfg.openingLocked!=null){
    localStorage.setItem('fuelOpeningLocked',cfg.openingLocked?'1':'0');""",
"""  if(cfg.openingAsOf!=null){   // MF_TANK_PACK_V1 — absent from older devices: keep ours
    localStorage.setItem('fuelOpeningAsOf',cfg.openingAsOf||'');
    _setInputIfIdle('opening_asof',cfg.openingAsOf||'');
  }
  if(cfg.openingLocked!=null){
    localStorage.setItem('fuelOpeningLocked',cfg.openingLocked?'1':'0');"""),

("T8 boot: restore the date",
"""if(_hsdC&&parseFloat(_hsdC)>0)document.getElementById('hsd_opening_cost').value=_hsdC;""",
"""if(_hsdC&&parseFloat(_hsdC)>0)document.getElementById('hsd_opening_cost').value=_hsdC;
{ const _ao=localStorage.getItem('fuelOpeningAsOf'), _ae=document.getElementById('opening_asof');   // MF_TANK_PACK_V1
  if(_ae&&_ao)_ae.value=_ao; }"""),

("T9 forecast note: dated opening",
"""  if(f.since && f.since==='opening stock'){""",
"""  if(f.since && /^opening/.test(f.since)){   // MF_TANK_PACK_V1"""),

# ───────────────────────────── 40 ML PACKS ─────────────────────────────
("P1 shift entry: units opened",
"""            <div><label>CLOSING (packs)</label><input type="number" id="pack_cur" placeholder="0" oninput="calc()"></div>
          </div>
          <div class="frow"><span class="flabel">Rate (₹/pack)</span>""",
"""            <div><label>CLOSING (packs)</label><input type="number" id="pack_cur" placeholder="0" oninput="calc()"></div>
          </div>
          <!-- MF_TANK_PACK_V1 -->
          <div class="frow"><span class="flabel">Units opened (40 packs each)</span><input type="number" id="pack_units" min="0" step="1" placeholder="0" inputmode="numeric" oninput="calc()"></div>
          <div id="pack_units_hint" style="font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--muted);margin:2px 0 6px;line-height:1.5"></div>
          <div class="frow"><span class="flabel">Rate (₹/pack)</span>"""),

("P2 helpers",
"""function setEl(id,val,cls){""",
"""// MF_TANK_PACK_V1 — 40 ml packs come 6 units to a box, 40 packs to a unit.
// When the counter runs low mid-shift a unit is opened and its 40 packs join
// the counter. Sold = opening + units opened × 40 − closing. Without the units
// the closing count came out higher than the opening and the sale clamped to 0.
// Opening a unit is a move from box to counter, not a sale: the Pack Register
// balance is untouched by it.
var PACK40_PER_UNIT=40, PACK40_UNITS_PER_BOX=6;
function _vn(id){var e=document.getElementById(id);return e&&e.value!==''?(parseFloat(e.value)||0):null;}
function _pack40Added(){
  var u=Math.max(0,Math.round(v('pack_units')));
  return {units:u,packs:u*PACK40_PER_UNIT};
}
function _pack40Hint(){
  var h=document.getElementById('pack_units_hint'); if(!h)return;
  var a=_vn('pack_prev'), b=_vn('pack_cur'), add=_pack40Added();
  if(a==null&&b==null&&!add.units){h.textContent='';return;}
  var avail=(a||0)+add.packs;
  if(b!=null&&b>avail){
    var need=Math.ceil((b-avail)/PACK40_PER_UNIT);
    h.style.color='var(--red)';
    h.textContent='⚠ Closing '+b+' is more than the '+avail+' available. If a unit was opened, '+
      (add.units?'enter '+(add.units+need)+' units':'enter '+need+' above')+' (1 unit = '+PACK40_PER_UNIT+' packs).';
    return;
  }
  h.style.color='var(--muted)';
  h.textContent='Opening '+(a||0)+(add.units?' + '+add.units+' unit'+(add.units>1?'s':'')+' ('+add.packs+' packs)':'')+
    ' = '+avail+' available'+(b!=null?' − closing '+b+' = '+(avail-b)+' sold':'');
}
// Closing packs of the shift before this one, for the carry-forward.
function _lastPackClose(){
  const d=document.getElementById('shiftDate')?.value||'';
  const prior=records.filter(r=>r.meters&&r.meters.pack_cur!=null&&
      (r.date<d||(r.date===d&&r.shift!==shift)))
    .sort((a,b)=>String(b.date).localeCompare(String(a.date))||
      (b.shift==='night'?1:-1)-(a.shift==='night'?1:-1));
  return prior.length?prior[0]:null;
}
function setEl(id,val,cls){"""),

("P3 calc()/getCalcVals(): sold includes units opened",
"""  const ps=Math.max(0,v('pack_prev')-v('pack_cur'));""",
"""  const ps=Math.max(0,v('pack_prev')+_pack40Added().packs-v('pack_cur'));   // MF_TANK_PACK_V1""",
2),

("P3b calc(): working line",
"""setEl('pack_sold',ps+' packs','b');setEl('pack_val',fmt(pv),'b');""",
"""setEl('pack_sold',ps+' packs','b');setEl('pack_val',fmt(pv),'b');_pack40Hint();"""),

("P4 getCalcVals(): return units",
"""    bottlesOpened, looseOpened:looseAdded.items, looseCost:looseAdded.cost,""",
"""    bottlesOpened, looseOpened:looseAdded.items, looseCost:looseAdded.cost,
    packUnits:_pack40Added().units,   // MF_TANK_PACK_V1"""),

("P5 save: pack readings ride in meters",
"""            ps:c.ps||0, os:c.os||0, handover:_r2(c.handover||0), looseOpened:c.looseOpened||[],""",
"""            ps:c.ps||0, os:c.os||0, handover:_r2(c.handover||0), looseOpened:c.looseOpened||[],
            // MF_TANK_PACK_V1: 40 ml counter readings, so the next shift can
            // carry the closing forward and History can show units opened.
            pack_prev:_vn('pack_prev'), pack_cur:_vn('pack_cur'), pack_units:c.packUnits||0,"""),

("P6 save: clear units box",
"""   'pack_prev','pack_cur','oil_prev','oil_cur',""",
"""   'pack_prev','pack_cur','pack_units','oil_prev','oil_cur',"""),

("P7 carry forward: last closing packs",
"""  if(n){calc(); if(!silent)showToast('✓ Opening readings carried from '+prev.id);}""",
"""  // MF_TANK_PACK_V1: 40 ml counter starts where the last shift left it.
  const _pp=(typeof _lastPackClose==='function')?_lastPackClose():null;
  if(_pp){
    const _pv=parseFloat(_pp.meters.pack_cur);
    const _pe=document.getElementById('pack_prev');
    if(_pe&&isFinite(_pv)&&(silent?!_pe.value:true)){_pe.value=_pv;n++;}
  }
  if(n){calc(); if(!silent)showToast('✓ Opening readings carried from '+prev.id);}"""),

("P8 stock hint: include units opened",
"""    var now=(isFinite(a)&&isFinite(b)&&a>=b)?(a-b):0;""",
"""    var _add=(sz===40&&typeof _pack40Added==='function')?_pack40Added().packs:0;   // MF_TANK_PACK_V1
    var now=(isFinite(a)&&isFinite(b)&&a+_add>=b)?(a+_add-b):0;"""),

("P8b stock hint: re-run on units input",
"""  if(/^pack\\d*_(prev|cur)$/.test(id))renderPackStockHint();""",
"""  if(/^pack\\d*_(prev|cur|units)$/.test(id))renderPackStockHint();   // MF_TANK_PACK_V1"""),

("P9 shift detail: units opened",
"""      if(p.n>0)parts.push(_sL(p.n,0)+' × 40 ml'+(p.est?' (count estimated)':''));""",
"""      if(p.n>0)parts.push(_sL(p.n,0)+' × 40 ml'+(p.est?' (count estimated)':'')+
        ((r.meters&&r.meters.pack_units>0)?' ('+r.meters.pack_units+' unit'+(r.meters.pack_units>1?'s':'')+' opened)':''));   // MF_TANK_PACK_V1"""),

("P10 pack register: boxes / units preview",
"""  if(prev)prev.textContent=qty&&cost?'Total cost: ₹'+(qty*cost).toLocaleString('en-IN',{minimumFractionDigits:2}):'';""",
"""  // MF_TANK_PACK_V1: 1 box = 6 units = 240 packs of 40 ml
  const _sz=(document.getElementById('pr_size')||{}).value;
  const _per=(typeof PACK40_PER_UNIT!=='undefined')?PACK40_PER_UNIT:40, _upb=(typeof PACK40_UNITS_PER_BOX!=='undefined')?PACK40_UNITS_PER_BOX:6;
  const _bx=(String(_sz)==='40'&&qty>0)?' · = '+(+(qty/(_per*_upb)).toFixed(2))+' box / '+(+(qty/_per).toFixed(2))+' units':'';
  if(prev)prev.textContent=(qty&&cost?'Total cost: ₹'+(qty*cost).toLocaleString('en-IN',{minimumFractionDigits:2}):'')+_bx;"""),
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
        print(f"  ✓ {name}" + (f" (×{want})" if want > 1 else ""))

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
