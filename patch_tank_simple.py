#!/usr/bin/env python3
"""
MF_TANK_SIMPLE_V1 — tank stock: just the dip and the litres; live stock that
says which shifts it has counted.

1 FORM  The "Daily tank stock — from the ATG screen" card asked for seven
        figures per tank (net, gross, dip, water, temp, today's sale, month
        till date) and its boxes overflowed their grid. The Order Advisor and
        the live stock need one thing: litres in the tank at a point in time.
        Now: DATE, WHEN, and per tank DIP (mm) + OBSERVED (L), with the book
        figure and the variation shown as you type. A saved tank chart fills
        the litres from the dip. The separate "Record a dip" card did the same
        job one tank at a time; it is hidden so there is one place to enter.
        Old readings with ATG details keep them.

2 LIVE  The dashboard tank figure = last reading + loads − metered sales of
        every shift saved AFTER that reading + testing. It only moves when a
        shift is saved on this phone. Each tank card now lists the shifts it
        counted since the reading with their litres, flags a shift that has
        0 L of this fuel while the other fuel sold, and names the shifts that
        have ended but are not saved yet.

Usage:  python3 patch_tank_simple.py [path/to/index.html]   (idempotent)
Requires MF_ATG_REVERSE_V1 and MF_DIPORDER_V1.
"""
import shutil, subprocess, sys, re, os, tempfile

PATH = sys.argv[1] if len(sys.argv) > 1 else "index.html"
SENTINEL = "MF_TANK_SIMPLE_V1"

FORM_HTML = r"""    <!-- MF_ATG_REVERSE_V1: daily stock from the ATG screen -->
    <!-- MF_TANK_SIMPLE_V1: the dip and the litres, both tanks on one form -->
    <style>
      .ts-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:8px}
      .ts-grid>div{min-width:0}
      .ts-grid input,.ts-grid select{width:100%;box-sizing:border-box}
      .ts-grid label{display:block;font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--muted);margin-bottom:3px}
      .ts-grid input[type=date]{background:var(--bg);border:1px solid var(--border);border-radius:4px;color:var(--text);padding:5px 9px;font-family:'JetBrains Mono',monospace;font-size:12px;color-scheme:dark}
      .ts-tanks{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:10px}
      .ts-tank{border:1px solid var(--border);border-radius:6px;padding:10px;min-width:0}
      .ts-name{font-family:'Syne',sans-serif;font-weight:700;font-size:11px;letter-spacing:1px;margin-bottom:6px}
      .ts-prev{font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--muted);line-height:1.6;min-height:16px}
    </style>
    <div class="dash-card" style="margin-bottom:12px;border-color:rgba(0,212,160,.35)" id="atg_card">
      <div class="dash-card-head">
        <div class="dash-card-title">📏 TANK STOCK — DIP READING</div>
        <span class="chip" id="atg_hint">—</span>
      </div>
      <div style="font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--muted);margin-bottom:10px;line-height:1.5">
        Once a day: the dip and the litres in each tank. The dashboard and the Order Advisor count forward from the last reading.
      </div>
      <div class="ts-grid">
        <div><label>DATE</label><input type="date" id="atg_date" onchange="atgPreview()"></div>
        <div><label>WHEN</label>
          <select id="atg_slot" onchange="atgPreview()">
            <option value="open">Before Morning shift (6 PM, day before)</option>
            <option value="mid">Shift change (9 AM)</option>
            <option value="close">After Night shift (6 PM)</option>
          </select></div>
      </div>
      <div class="ts-tanks">
        <div class="ts-tank">
          <div class="ts-name" style="color:var(--petrol)">MS — PETROL</div>
          <div class="ts-grid">
            <div><label>DIP (mm)</label><input type="number" step="0.01" inputmode="decimal" id="atg_ms_mm" placeholder="e.g. 746.20" oninput="atgFromChart('MSD')"></div>
            <div><label>OBSERVED (L)</label><input type="number" step="0.01" inputmode="decimal" id="atg_ms_vol" placeholder="e.g. 5914.72" oninput="this.dataset.auto='';atgPreview()"></div>
          </div>
          <div class="ts-prev" id="atg_ms_prev"></div>
        </div>
        <div class="ts-tank">
          <div class="ts-name" style="color:var(--diesel)">HSD — DIESEL</div>
          <div class="ts-grid">
            <div><label>DIP (mm)</label><input type="number" step="0.01" inputmode="decimal" id="atg_hsd_mm" placeholder="e.g. 805.10" oninput="atgFromChart('HSD')"></div>
            <div><label>OBSERVED (L)</label><input type="number" step="0.01" inputmode="decimal" id="atg_hsd_vol" placeholder="e.g. 8023.83" oninput="this.dataset.auto='';atgPreview()"></div>
          </div>
          <div class="ts-prev" id="atg_hsd_prev"></div>
        </div>
      </div>
      <div style="display:flex;gap:8px;align-items:center;margin-top:10px;flex-wrap:wrap">
        <button class="save-btn" style="max-width:260px" onclick="submitAtg()">SAVE TANK STOCK</button>
        <span id="atg_msg" style="font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--muted)"></span>
      </div>
      <div style="font-family:'Syne',sans-serif;font-weight:700;font-size:10px;letter-spacing:1.5px;color:var(--muted);margin:14px 0 6px">READINGS — LAST 14 DAYS</div>
      <div id="atg_list" style="overflow-x:auto"></div>
    </div>

"""

SUBMIT_JS = r"""function submitAtg(){
  // MF_TANK_SIMPLE_V1: the dip and the litres for each tank — nothing else.
  var date=(document.getElementById('atg_date')||{}).value||_isoLocal();
  var slot=(document.getElementById('atg_slot')||{}).value||_dipDefaultSlot();
  var cfg=tankCfg(), made=[], errs=[];
  [['MSD','ms',cfg.capMSD],['HSD','hsd',cfg.capHSD]].forEach(function(t){
    var vol=_atgVal('atg_'+t[1]+'_vol'), mm=_atgVal('atg_'+t[1]+'_mm');
    if(vol==null){ if(mm!=null)errs.push(t[0]+': enter the litres for the '+mm+' mm dip'); return; }
    if(!(vol>=0)){errs.push(t[0]+' litres');return;}
    if(vol>t[2]){errs.push(t[0]+' '+vol+' L is more than the '+t[2]+' L tank');return;}
    if(mm!=null&&!(mm>=0)){errs.push(t[0]+' dip');return;}
    made.push({type:t[0],vol:vol,mm:mm});
  });
  if(errs.length){showToast('Check: '+errs.join(', '));return;}
  if(!made.length){showToast('Enter the litres for at least one tank');return;}
  var dups=made.filter(function(m){return dipReadings.some(function(d){return d.date===date&&d.slot===slot&&d.type===m.type;});});
  if(dups.length&&!confirm('A reading for '+dups.map(function(m){return m.type;}).join(' & ')+' on '+date+
     ' ('+_DIP_SLOT_LBL[slot]+') already exists. Replace it?'))return;
  var said=[];
  made.forEach(function(m){
    var dup=dipReadings.find(function(d){return d.date===date&&d.slot===slot&&d.type===m.type;});
    var b=bookStock(m.type,date,slot);
    var rec={id:dup?dup.id:_newId(),date:date,slot:slot,type:m.type,
      dipCm:m.mm!=null?_r2(m.mm/10):null,observed:_r2(m.vol),
      book:_r2(b.book),variation:_r2(m.vol-b.book),
      openingL:_r2(b.open),loadedL:_r2(b.loaded),soldL:_r2(b.sold),testedL:_r2(b.tested),
      notes:(m.mm!=null?'dip '+m.mm+' mm':''),source:'dip',
      recordedBy:_currentUser?_currentUser.username:'',savedAt:new Date().toISOString()};
    if(dup)dipReadings[dipReadings.indexOf(dup)]=rec; else dipReadings.push(rec);
    if(_currentUser&&typeof sbSaveDip==='function')sbSaveDip(rec).catch(console.error);
    if(typeof logActivity==='function')logActivity('atg_stock','dip_reading',rec.id,
      m.type+' '+date+' '+slot+' • '+m.vol+' L'+(m.mm!=null?' ('+m.mm+' mm)':'')+' • book '+rec.book.toFixed(0)+' L • var '+
      (rec.variation>=0?'+':'')+rec.variation.toFixed(1)+' L');
    said.push(m.type+' '+(rec.variation>=0?'+':'')+rec.variation.toFixed(1)+' L');
  });
  saveDipsLS();
  ['ms','hsd'].forEach(function(k){['vol','mm'].forEach(function(f){
    var e=document.getElementById('atg_'+k+'_'+f); if(e){e.value='';e.dataset.auto='';}});
    var p=document.getElementById('atg_'+k+'_prev'); if(p)p.dataset.chart='';});
  renderDip();
  if(typeof renderDashTanks==='function'&&document.getElementById('dashFuelTanks'))renderDashTanks();
  showToast('✓ Tank stock saved for '+date+' — variation '+said.join(', '));
}
// Book figure and variation under each tank while typing.
function atgPreview(){
  var date=(document.getElementById('atg_date')||{}).value||_isoLocal();
  var slot=(document.getElementById('atg_slot')||{}).value||_dipDefaultSlot();
  var early=(typeof _dipBeforeOpening==='function')&&_dipBeforeOpening({date:date,slot:slot});
  [['MSD','ms'],['HSD','hsd']].forEach(function(t){
    var el=document.getElementById('atg_'+t[1]+'_prev'); if(!el)return;
    var b=bookStock(t[0],date,slot), vol=_atgVal('atg_'+t[1]+'_vol');
    var txt='Book at this point: <b style="color:var(--text)">'+Math.round(b.book).toLocaleString('en-IN')+' L</b>';
    if(vol!=null&&isFinite(vol)){
      var vr=vol-b.book, tol=(typeof _dipTolBook==='function')?_dipTolBook(b):tankCfg().tol;
      var c=Math.abs(vr)<=tol?'var(--green)':(vr<0?'var(--red)':'var(--diesel)');
      txt+=' · variation <b style="color:'+c+'">'+(vr>=0?'+':'')+vr.toFixed(1)+' L</b>'+(Math.abs(vr)<=tol?' ✓':'');
    }
    if(early)txt='<span style="color:var(--diesel)">⚠ Timed before the opening stock — it will not be used. Pick a later WHEN.</span>';
    if(el.dataset.chart)txt+='<br>'+el.dataset.chart;
    el.innerHTML=txt;
  });
}
// A saved tank chart (cm → litres) turns the dip into litres.
function atgFromChart(type){
  var k=type==='MSD'?'ms':'hsd', mmEl=document.getElementById('atg_'+k+'_mm'), lEl=document.getElementById('atg_'+k+'_vol');
  var pv=document.getElementById('atg_'+k+'_prev'); if(!mmEl||!lEl||!pv)return;
  var mm=parseFloat(mmEl.value), L=(isFinite(mm)&&typeof _chartLitres==='function')?_chartLitres(type,mm/10):null;
  if(L!=null&&(lEl.value===''||lEl.dataset.auto==='1')){ lEl.value=L; lEl.dataset.auto='1'; }
  else if(L==null&&lEl.dataset.auto==='1'){ lEl.value=''; lEl.dataset.auto=''; }
  pv.dataset.chart=L!=null?'Tank chart: '+mm+' mm = '+L.toLocaleString('en-IN')+' L'+(lEl.dataset.auto==='1'?'':' (litres typed by hand kept)'):'';
  atgPreview();
}

"""

LIST_JS = r"""function _renderAtgList(){
  var el=document.getElementById('atg_list'); if(!el)return;
  var ad=document.getElementById('atg_date'), as=document.getElementById('atg_slot');
  if(ad&&!ad.value){ ad.value=_isoLocal(); if(as)as.value=_dipDefaultSlot(); }
  var rows=_dipSortedLive(), byDate={};
  rows.forEach(function(r){ (byDate[r.date]=byDate[r.date]||{})[r.type]=r; });   // sorted: last point of the day wins
  var dates=Object.keys(byDate).sort().reverse().slice(0,14);
  var hint=document.getElementById('atg_hint');
  if(hint)hint.textContent=byDate[_isoLocal()]?'✓ today entered':'today not entered yet';
  try{ atgPreview(); }catch(e){}   // MF_TANK_SIMPLE_V1
  if(!dates.length){el.innerHTML='<div style="font-size:11px;color:var(--muted)">No readings yet.</div>';return;}
  var tol=tankCfg().tol;
  var cell=function(r){
    if(!r)return '<td style="color:var(--muted)">—</td><td></td><td></td>';
    var a=r.atg||_atgFromNotes(r.notes), vc=r.unused?'var(--muted)':((r.explained||Math.abs(r.variation)<=(r.tol!=null?r.tol:tol))?'var(--green)':(r.variation<0?'var(--red)':'var(--diesel)'));
    var mm=r.dipCm!=null?_r2(r.dipCm*10):null;
    return '<td style="color:var(--muted)">'+(mm!=null&&mm>0?mm:'—')+'</td><td>'+Number(r.observed||0).toLocaleString('en-IN',{maximumFractionDigits:2})+
      (a&&a.water>0?' <span style="color:var(--red)">💧'+a.water+'</span>':'')+'</td>'+
      '<td style="color:'+vc+'">'+(r.unused?'not used':(r.variation>=0?'+':'')+r.variation.toFixed(1))+'</td>';
  };
  // MF_TANK_SIMPLE_V1: dip, litres, variation — the gauge extras are gone
  var h='<table class="data-tbl" style="min-width:600px"><thead><tr><th>DATE</th><th>WHEN</th>'+
        '<th style="color:var(--petrol)">MS DIP mm</th><th style="color:var(--petrol)">MS (L)</th><th>MS VAR</th>'+
        '<th style="color:var(--diesel)">HSD DIP mm</th><th style="color:var(--diesel)">HSD (L)</th><th>HSD VAR</th></tr></thead><tbody>';
  dates.forEach(function(d){
    var m=byDate[d].MSD, s=byDate[d].HSD, any=m||s;
    h+='<tr><td>'+_esc(d)+'</td><td style="font-size:10px;color:var(--muted)">'+_esc(_DIP_SLOT_LBL[any.slot]||any.slot)+'</td>'+
       cell(m)+cell(s)+'</tr>';
  });
  el.innerHTML=h+'</tbody></table>';
}

"""

TRAIL_JS = r"""// MF_TANK_SIMPLE_V1 ── which shifts the live figure has counted ──────────
function _tsAddDay(d,n){ var t=new Date(d+'T00:00:00'); t.setDate(t.getDate()+n);
  var z=function(x){return String(x).padStart(2,'0');}; return t.getFullYear()+'-'+z(t.getMonth()+1)+'-'+z(t.getDate()); }
function _tsDM(d){ return String(d).slice(8,10)+'/'+String(d).slice(5,7); }
// The point the live figure counts forward from: the last reading, or the opening.
function _tankFromPoint(b){
  if(b.anchor)return {date:b.anchor.date,rank:_slotRank(b.anchor.slot)};
  var asOf=(typeof _openingAsOf==='function')?_openingAsOf():'';
  if(asOf&&/^opening/.test(String(b.since||'')))return {date:asOf,rank:_slotRank(_openingAsOfSlot())};
  return null;
}
// Shifts saved after that point (with this fuel's litres), and the shifts that
// have ended by now but are not saved on this phone.
function _tankTrail(type,b,now){
  var p=_tankFromPoint(b); if(!p)return null;
  var key=type==='MSD'?'msdT':'hsdT', other=type==='MSD'?'hsdT':'msdT';
  var done=records.filter(function(r){ return r.date&&_posCmp(r.date,_shiftRank(r.shift),p.date,p.rank)>0; })
    .sort(function(a,c){ return _posCmp(a.date,_shiftRank(a.shift),c.date,_shiftRank(c.shift)); })
    .map(function(r){ var L=+r[key]||0; return {r:r,L:L,zero:L<=0&&(+r[other]||0)>0}; });
  now=now||new Date();
  var today=_isoLocal(now), h=now.getHours();
  // Morning of D ends 9 AM on D, Night of D ends 6 PM on D.
  var last=h>=18?{date:today,rank:2}:(h>=9?{date:today,rank:1}:{date:_tsAddDay(today,-1),rank:2});
  var cur=p.rank===0?{date:p.date,rank:1}:(p.rank===1?{date:p.date,rank:2}:{date:_tsAddDay(p.date,1),rank:1});
  var missing=[], guard=0;
  while(_posCmp(cur.date,cur.rank,last.date,last.rank)<=0&&guard++<62){
    var c=cur; if(!records.some(function(r){return r.date===c.date&&_shiftRank(r.shift)===c.rank;}))
      missing.push({date:c.date,shift:c.rank===2?'night':'morning'});
    cur=c.rank===1?{date:c.date,rank:2}:{date:_tsAddDay(c.date,1),rank:1};
  }
  return {from:p,done:done,missing:missing};
}
function _tankTrailHtml(type,b){
  var t; try{ t=_tankTrail(type,b); }catch(e){ return ''; } if(!t)return '';
  var sl=function(d,sh){ return _tsDM(d)+' '+(sh==='night'?'NIGHT':'MORN'); };
  var bits=t.done.slice(-4).map(function(x){
    return x.zero?'<span style="color:var(--red)">'+sl(x.r.date,x.r.shift)+' 0 L ⚠</span>'
                 :sl(x.r.date,x.r.shift)+' −'+Math.round(x.L).toLocaleString('en-IN');
  });
  if(t.done.length>4)bits.unshift('+'+(t.done.length-4)+' earlier');
  t.missing.slice(-3).forEach(function(m){ bits.push('<span style="color:var(--diesel)">'+sl(m.date,m.shift)+' not saved</span>'); });
  if(t.missing.length>3)bits.push('<span style="color:var(--diesel)">+'+(t.missing.length-3)+' more not saved</span>');
  var fromTxt=_tsDM(t.from.date)+' '+(['6 PM (eve)','9 AM','6 PM'][t.from.rank]||'');
  var h='<div style="font-family:\'JetBrains Mono\',monospace;font-size:9px;color:var(--muted);margin-top:2px;line-height:1.6">Shifts counted since the '+fromTxt+' reading: '+
        (bits.length?bits.join(' · '):'none yet')+'</div>';
  var z=t.done.filter(function(x){return x.zero;});
  if(z.length)h+='<div style="font-family:\'JetBrains Mono\',monospace;font-size:10px;color:var(--red);margin-top:3px;line-height:1.5">⚠ '+
    z.map(function(x){return sl(x.r.date,x.r.shift);}).join(', ')+' saved 0 L of '+type+' while the other fuel sold — open '+
    (z.length>1?'those shifts':'that shift')+' in History and check the '+type+' meter readings. The live stock is too high until it is fixed.</div>';
  else if(t.missing.length)h+='<div style="font-family:\'JetBrains Mono\',monospace;font-size:10px;color:var(--diesel);margin-top:3px;line-height:1.5">The live stock drops when a shift is saved — '+
    t.missing.length+' shift'+(t.missing.length!==1?'s have':' has')+' ended but '+(t.missing.length!==1?'are':'is')+' not saved on this phone yet.</div>';
  return h;
}

"""

HUNKS = [
("1 form: dip + litres per tank", "span",
 "    <!-- MF_ATG_REVERSE_V1: daily stock from the ATG screen -->\n",
 "    <div class=\"dash-card\" style=\"margin-bottom:12px\">\n      <div class=\"dash-card-head\">\n        <div class=\"dash-card-title\">📏 RECORD A DIP</div>",
 FORM_HTML),

("2 hide the one-tank dip card (same job, one place to enter)",
 "    <div class=\"dash-card\" style=\"margin-bottom:12px\">\n      <div class=\"dash-card-head\">\n        <div class=\"dash-card-title\">📏 RECORD A DIP</div>",
 "    <div class=\"dash-card\" style=\"margin-bottom:12px;display:none\" id=\"dip_manual_card\"><!-- MF_TANK_SIMPLE_V1: replaced by the tank stock form above -->\n      <div class=\"dash-card-head\">\n        <div class=\"dash-card-title\">📏 RECORD A DIP</div>"),

("3 submit: dip + litres only", "span",
 "function submitAtg(){\n",
 "// MF_FIVE_V1 — gauge vs meters.",
 SUBMIT_JS),

("4 readings list without the gauge extras", "span",
 "function _renderAtgList(){\n",
 "function renderDip(){\n",
 LIST_JS),

("5 trail helpers",
 "function renderDashTanks(){\n",
 TRAIL_JS + "function renderDashTanks(){\n"),

("6 trail on each tank card",
 "<br>${_esc(b.since)}: ${nf(b.open)} + in ${nf(b.loaded)} − out ${nf(b.sold)}${b.tested?' + test '+nf(b.tested,1):''}</div>\n      ${warn}",
 "<br>${_esc(b.since)}: ${nf(b.open)} + in ${nf(b.loaded)} − out ${nf(b.sold)}${b.tested?' + test '+nf(b.tested,1):''}</div>\n      ${_tankTrailHtml(cls==='msd'?'MSD':'HSD',b)}\n      ${warn}"),
]


def main():
    if not os.path.exists(PATH):
        sys.exit(f"✗ {PATH} not found")
    src = open(PATH, encoding="utf-8").read()
    for need in ("MF_ATG_REVERSE_V1", "MF_DIPORDER_V1"):
        if need not in src:
            sys.exit(f"✗ {need} is not in {PATH} — apply that patch first. Nothing written.")
    out = src
    applied = 0
    for h in HUNKS:
        name = h[0]
        if len(h) == 5 and h[1] == "span":
            start, end, new = h[2], h[3], h[4]
            if new in out:
                print(f"  = {name}: already applied"); continue
            if out.count(start) != 1 or out.count(end) != 1:
                sys.exit(f"✗ {name}: markers found {out.count(start)}/{out.count(end)} times (expected 1/1). Nothing written.")
            i, j = out.index(start), out.index(end)
            if j <= i:
                sys.exit(f"✗ {name}: end marker before start. Nothing written.")
            out = out[:i] + new + out[j:]
        else:
            old, new = h[1], h[2]
            want = h[3] if len(h) > 3 else 1
            if new in out and old not in out.replace(new, ""):
                print(f"  = {name}: already applied"); continue
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
