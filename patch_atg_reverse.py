#!/usr/bin/env python3
"""
MF_ATG_REVERSE_V1 — daily ATG stock, payment reversal, dip accuracy.

1) DAILY TANK STOCK FROM THE ATG (Bahwan CyberTek TANK STATUS screen)
   A1 Dip page     : "Daily tank stock" card — one entry for both tanks: net
                     volume, dip mm, water, temperature, ATG today's sale.
                     Saved as a dip per tank (same table, no schema change;
                     the extra ATG figures ride in the notes and are parsed
                     back), so every reading re-bases the tank level and the
                     Order Advisor forecasts from what is really in the tank.
   A2 Daily list   : last 14 days — MS / HSD litres, live variation, water.
   A3 Alert        : "Today's tank stock not entered" after 10 AM; red alert
                     if the ATG shows water in a tank.

2) REVERSE A PAYMENT (credit ledger)
   R1 Payment history gets a REVERSE button (owner / manager).
   R2 reversePayment(): takes the amount back off exactly the bills that
      payment cleared, removes the advance it created (refused if that
      advance has been drawn against), deletes the payment record, stamps
      each bill's notes and writes the reason to the activity log. Shift
      collections are refused: delete and re-enter that shift instead,
      so the shift's cash tally stays right.

3) DIP ACCURACY
   V1 Variation is recalculated from the CURRENT book every time it is shown,
      not the figure saved on the day (which went stale when the opening was
      re-dated).
   V2 Dips before the opening point are left out of totals and alerts.
   V3 Losses are valued at landed cost (weighted average), not selling price —
      the same basis the weekly money-leak check already uses.
   V4 _dipAlerts used `level:` but the alert list reads `type:`, so its colour
      never applied; it now also looks at the last 30 days, not all history.
   V5 Book stock exactly at the opening point uses the opening, even when an
      older dip exists.
   V6 Dashboard tank card: "≈ N days left · order by dd/mm" from the forecast.

Usage:  python3 patch_atg_reverse.py [path/to/index.html]
Idempotent. Requires MF_DIP_SYNC_V1.
"""
import shutil, subprocess, sys, re, os, tempfile

PATH = sys.argv[1] if len(sys.argv) > 1 else "index.html"
SENTINEL = "MF_ATG_REVERSE_V1"

ATG_CARD = """    <!-- MF_ATG_REVERSE_V1: daily stock from the ATG screen -->
    <div class="dash-card" style="margin-bottom:12px;border-color:rgba(0,212,160,.35)" id="atg_card">
      <div class="dash-card-head">
        <div class="dash-card-title">📟 DAILY TANK STOCK — FROM THE ATG SCREEN</div>
        <span class="chip" id="atg_hint">—</span>
      </div>
      <div style="font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--muted);margin-bottom:10px;line-height:1.5">
        Copy the figures from the tank gauge (TANK STATUS) once a day. Each reading re-bases the tank level,
        so the dashboard and the Order Advisor work from what is really in the tank.
      </div>
      <div class="rg" style="grid-template-columns:repeat(auto-fit,minmax(150px,1fr));margin-bottom:8px">
        <div><label>DATE</label><input type="date" id="atg_date"></div>
        <div><label>WHEN</label>
          <select id="atg_slot" style="width:100%;padding:5px 9px;background:var(--bg);border:1px solid var(--border);border-radius:4px;color:var(--text);font-family:'JetBrains Mono',monospace;font-size:12px">
            <option value="open">Before Morning shift (6 PM, day before)</option>
            <option value="mid">Shift change (9 AM)</option>
            <option value="close">After Night shift (6 PM)</option>
          </select></div>
      </div>
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:10px">
        <div style="border:1px solid var(--border);border-radius:6px;padding:8px">
          <div style="font-family:'Syne',sans-serif;font-weight:700;font-size:11px;letter-spacing:1px;color:var(--petrol);margin-bottom:6px">MS — PETROL</div>
          <div class="rg" style="grid-template-columns:repeat(auto-fit,minmax(110px,1fr))">
            <div><label>NET VOLUME (L)</label><input type="number" step="0.01" inputmode="decimal" id="atg_ms_vol" placeholder="5914.72"></div>
            <div><label>DIP (mm)</label><input type="number" step="0.01" inputmode="decimal" id="atg_ms_mm" placeholder="746.20"></div>
            <div><label>WATER (L)</label><input type="number" step="0.01" inputmode="decimal" id="atg_ms_water" placeholder="0.00"></div>
            <div><label>TEMP (°C)</label><input type="number" step="0.1" inputmode="decimal" id="atg_ms_temp" placeholder="30.2"></div>
            <div><label>TODAY'S SALE (L)</label><input type="number" step="0.01" inputmode="decimal" id="atg_ms_sale" placeholder="227.05"></div>
          </div>
        </div>
        <div style="border:1px solid var(--border);border-radius:6px;padding:8px">
          <div style="font-family:'Syne',sans-serif;font-weight:700;font-size:11px;letter-spacing:1px;color:var(--diesel);margin-bottom:6px">HSD — DIESEL</div>
          <div class="rg" style="grid-template-columns:repeat(auto-fit,minmax(110px,1fr))">
            <div><label>NET VOLUME (L)</label><input type="number" step="0.01" inputmode="decimal" id="atg_hsd_vol" placeholder="8023.83"></div>
            <div><label>DIP (mm)</label><input type="number" step="0.01" inputmode="decimal" id="atg_hsd_mm" placeholder="805.10"></div>
            <div><label>WATER (L)</label><input type="number" step="0.01" inputmode="decimal" id="atg_hsd_water" placeholder="0.00"></div>
            <div><label>TEMP (°C)</label><input type="number" step="0.1" inputmode="decimal" id="atg_hsd_temp" placeholder="31.3"></div>
            <div><label>TODAY'S SALE (L)</label><input type="number" step="0.01" inputmode="decimal" id="atg_hsd_sale" placeholder="496.46"></div>
          </div>
        </div>
      </div>
      <div style="display:flex;gap:8px;align-items:center;margin-top:10px;flex-wrap:wrap">
        <button class="save-btn" style="max-width:260px" onclick="submitAtg()">SAVE TANK STOCK</button>
        <span id="atg_msg" style="font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--muted)"></span>
      </div>
      <div style="font-family:'Syne',sans-serif;font-weight:700;font-size:10px;letter-spacing:1.5px;color:var(--muted);margin:14px 0 6px">DAILY STOCK LIST — LAST 14 DAYS</div>
      <div id="atg_list" style="overflow-x:auto"></div>
    </div>

"""

HUNKS = [
# ───────── 1. ATG ─────────
("A1 Dip page: ATG card",
"""    <div class="dash-card" style="margin-bottom:12px">
      <div class="dash-card-head">
        <div class="dash-card-title">📏 RECORD A DIP</div>""",
ATG_CARD + """    <div class="dash-card" style="margin-bottom:12px">
      <div class="dash-card-head">
        <div class="dash-card-title">📏 RECORD A DIP</div>"""),

("A1b+V1 helpers: ATG save, daily list, live variation",
"""function renderDip(){
  var cfg=tankCfg();""",
"""// MF_ATG_REVERSE_V1 ──────────────────────────────────────────────────────
// Variation against the book as it stands NOW. The figure saved with a dip
// was measured against the book of that day and goes stale whenever the
// opening, a load or a shift before it is corrected.
function _dipLive(r){
  var b=bookStock(r.type,r.date,r.slot);
  var o=Object.assign({},r);
  o.book=_r2(b.book); o.variation=_r2((parseFloat(r.observed)||0)-b.book);
  o.unused=(typeof _dipBeforeOpening==='function')&&_dipBeforeOpening(r);
  return o;
}
function _dipSortedLive(){ return _dipSorted().map(_dipLive); }
function _dipLiveVar(r){ return _dipLive(r).variation; }

// ATG figures ride in the notes (dip_readings has no columns for them), so
// they survive the sync and are read back from there.
function _atgNote(a){
  return 'ATG · '+a.mm+' mm · '+a.temp+'°C · water '+a.water+' L'+(a.sale!=null?' · ATG sale '+a.sale+' L':'');
}
function _atgFromNotes(n){
  var m=/ATG · ([\\d.]+) mm · ([\\d.-]+)°C · water ([\\d.]+) L(?: · ATG sale ([\\d.]+) L)?/.exec(String(n||''));
  return m?{mm:+m[1],temp:+m[2],water:+m[3],sale:m[4]!=null?+m[4]:null}:null;
}
function _atgVal(id){ var e=document.getElementById(id); return e&&e.value!==''?parseFloat(e.value):null; }

function submitAtg(){
  var date=(document.getElementById('atg_date')||{}).value||_isoLocal();
  var slot=(document.getElementById('atg_slot')||{}).value||_dipDefaultSlot();
  var cfg=tankCfg(), made=[], errs=[], water=[];
  [['MSD','ms',cfg.capMSD],['HSD','hsd',cfg.capHSD]].forEach(function(t){
    var vol=_atgVal('atg_'+t[1]+'_vol'); if(vol==null)return;
    if(!(vol>=0)){errs.push(t[0]+' volume');return;}
    if(vol>t[2]){errs.push(t[0]+' '+vol+' L is more than the '+t[2]+' L tank');return;}
    var a={mm:_atgVal('atg_'+t[1]+'_mm'), temp:_atgVal('atg_'+t[1]+'_temp'),
           water:_atgVal('atg_'+t[1]+'_water')||0, sale:_atgVal('atg_'+t[1]+'_sale')};
    if(a.mm==null)a.mm=0; if(a.temp==null)a.temp=0;
    if(a.water>0)water.push(t[0]+' '+a.water+' L');
    made.push({type:t[0],vol:vol,a:a});
  });
  if(errs.length){showToast('Check: '+errs.join(', '));return;}
  if(!made.length){showToast('Enter the net volume for at least one tank');return;}
  var dups=made.filter(function(m){return dipReadings.some(function(d){return d.date===date&&d.slot===slot&&d.type===m.type;});});
  if(dups.length&&!confirm('A reading for '+dups.map(function(m){return m.type;}).join(' & ')+' on '+date+
     ' ('+_DIP_SLOT_LBL[slot]+') already exists. Replace it?'))return;
  made.forEach(function(m){
    var dup=dipReadings.find(function(d){return d.date===date&&d.slot===slot&&d.type===m.type;});
    var b=bookStock(m.type,date,slot);
    var rec={id:dup?dup.id:_newId(),date:date,slot:slot,type:m.type,
      dipCm:m.a.mm?_r2(m.a.mm/10):null,observed:_r2(m.vol),
      book:_r2(b.book),variation:_r2(m.vol-b.book),
      openingL:_r2(b.open),loadedL:_r2(b.loaded),soldL:_r2(b.sold),testedL:_r2(b.tested),
      notes:_atgNote(m.a),atg:m.a,source:'atg',
      recordedBy:_currentUser?_currentUser.username:'',savedAt:new Date().toISOString()};
    if(dup)dipReadings[dipReadings.indexOf(dup)]=rec; else dipReadings.push(rec);
    if(_currentUser&&typeof sbSaveDip==='function')sbSaveDip(rec).catch(console.error);
    if(typeof logActivity==='function')logActivity('atg_stock','dip_reading',rec.id,
      m.type+' '+date+' '+slot+' • ATG '+m.vol+' L • book '+rec.book.toFixed(0)+' L • var '+
      (rec.variation>=0?'+':'')+rec.variation.toFixed(1)+' L');
  });
  saveDipsLS();
  ['ms','hsd'].forEach(function(k){['vol','mm','water','temp','sale'].forEach(function(f){
    var e=document.getElementById('atg_'+k+'_'+f); if(e)e.value='';});});
  renderDip();
  if(typeof renderDashTanks==='function'&&document.getElementById('dashFuelTanks'))renderDashTanks();
  showToast(water.length?'⚠ Saved — WATER in tank: '+water.join(', '):'✓ Tank stock saved for '+date);
}

function _renderAtgList(){
  var el=document.getElementById('atg_list'); if(!el)return;
  var ad=document.getElementById('atg_date'), as=document.getElementById('atg_slot');
  if(ad&&!ad.value){ ad.value=_isoLocal(); if(as)as.value=_dipDefaultSlot(); }
  var rows=_dipSortedLive(), byDate={};
  rows.forEach(function(r){ (byDate[r.date]=byDate[r.date]||{})[r.type]=r; });   // sorted: last point of the day wins
  var dates=Object.keys(byDate).sort().reverse().slice(0,14);
  var hint=document.getElementById('atg_hint');
  if(hint)hint.textContent=byDate[_isoLocal()]?'✓ today entered':'today not entered yet';
  if(!dates.length){el.innerHTML='<div style="font-size:11px;color:var(--muted)">No readings yet.</div>';return;}
  var tol=tankCfg().tol;
  var cell=function(r){
    if(!r)return '<td style="color:var(--muted)">—</td><td></td>';
    var a=r.atg||_atgFromNotes(r.notes), vc=r.unused?'var(--muted)':(Math.abs(r.variation)<=tol?'var(--green)':(r.variation<0?'var(--red)':'var(--diesel)'));
    return '<td>'+Number(r.observed||0).toLocaleString('en-IN',{maximumFractionDigits:2})+
      (a&&a.water>0?' <span style="color:var(--red)">💧'+a.water+'</span>':'')+'</td>'+
      '<td style="color:'+vc+'">'+(r.unused?'not used':(r.variation>=0?'+':'')+r.variation.toFixed(1))+'</td>';
  };
  var h='<table class="data-tbl" style="min-width:560px"><thead><tr><th>DATE</th><th>WHEN</th>'+
        '<th style="color:var(--petrol)">MS (L)</th><th>MS VAR</th><th style="color:var(--diesel)">HSD (L)</th><th>HSD VAR</th><th>SOURCE</th></tr></thead><tbody>';
  dates.forEach(function(d){
    var m=byDate[d].MSD, s=byDate[d].HSD, any=m||s;
    var src=(m&&(m.atg||_atgFromNotes(m.notes)))||(s&&(s.atg||_atgFromNotes(s.notes)))?'ATG':'dip';
    h+='<tr><td>'+_esc(d)+'</td><td style="font-size:10px;color:var(--muted)">'+_esc(_DIP_SLOT_LBL[any.slot]||any.slot)+'</td>'+
       cell(m)+cell(s)+'<td style="font-size:10px;color:var(--muted)">'+src+'</td></tr>';
  });
  el.innerHTML=h+'</tbody></table>';
}

function renderDip(){
  var cfg=tankCfg();
  try{ _renderAtgList(); }catch(e){ console.warn('ATG list:',e); }"""),

# ───────── 3. dip accuracy ─────────
("V1 renderDip: live variation, skip unused",
"""  var rows=_dipSorted();
  var tb=document.getElementById('dip_body');""",
"""  var rows=_dipSortedLive();   // MF_ATG_REVERSE_V1: variation against today's book
  var tb=document.getElementById('dip_body');"""),

("V2 renderDip: running total skips dips before the opening",
"""    cum[r.type]=(cum[r.type]||0)+(r.variation||0);
    var vc=Math.abs(r.variation)<=cfg.tol?'var(--green)':(r.variation<0?'var(--red)':'var(--diesel)');""",
"""    if(!r.unused)cum[r.type]=(cum[r.type]||0)+(r.variation||0);   // MF_ATG_REVERSE_V1
    var vc=r.unused?'var(--muted)':(Math.abs(r.variation)<=cfg.tol?'var(--green)':(r.variation<0?'var(--red)':'var(--diesel)'));"""),

("V3 renderDip KPI: cost basis, used dips only",
"""    var mine=rows.filter(function(r){return r.type===t;});
    if(!mine.length)return;
    var total=mine.reduce(function(a,r){return a+(r.variation||0);},0);
    var rate=parseFloat(t==='MSD'?rates.msd:rates.hsd)||0;
    var last=mine[mine.length-1];""",
"""    var mine=rows.filter(function(r){return r.type===t&&!r.unused;});   // MF_ATG_REVERSE_V1
    if(!mine.length)return;
    var total=mine.reduce(function(a,r){return a+(r.variation||0);},0);
    // What the missing litres cost you, not what they would have sold for.
    var rate=(typeof _fuelWAC==='function'?_fuelWAC(t):0)||parseFloat(t==='MSD'?rates.msd:rates.hsd)||0;
    var last=mine[mine.length-1];"""),

("V1b CSV export: live figures",
"""  var rows=_dipSorted();
  if(!rows.length){showToast('Nothing to export');return;}""",
"""  var rows=_dipSortedLive();   // MF_ATG_REVERSE_V1
  if(!rows.length){showToast('Nothing to export');return;}"""),

("V4+A3 _dipAlerts: type, 30 days, cost, ATG reminders",
"""function _dipAlerts(){
  if(typeof dipReadings==='undefined'||!dipReadings.length)return [];
  var cfg=tankCfg(), out=[];
  ['MSD','HSD'].forEach(function(t){
    var mine=dipReadings.filter(function(r){return r.type===t;});
    if(!mine.length)return;
    var total=mine.reduce(function(a,r){return a+(r.variation||0);},0);
    if(Math.abs(total)<=cfg.tol)return;
    var rates=JSON.parse(localStorage.getItem('fuelRates')||'{}');
    var rate=parseFloat(t==='MSD'?rates.msd:rates.hsd)||0;
    out.push({level:total<0?'danger':'warn',icon:'📏',
      title:t+' stock variation '+(total>=0?'+':'')+total.toFixed(1)+' L',
      desc:(total<0?'Physical stock is short of book':'Physical stock exceeds book')+
        (rate>0?' — worth '+fmt(Math.abs(total)*rate):''),
      action:'DIP →',page:'dip'});
  });
  return out;
}""",
"""function _dipAlerts(){
  // MF_ATG_REVERSE_V1: the alert list reads `type`, not `level`; last 30 days
  // only; variation against today's book; valued at landed cost.
  var out=[], today=_isoLocal();
  var hasToday=(typeof dipReadings!=='undefined')&&dipReadings.some(function(r){return r.date===today;});
  if(!hasToday&&new Date().getHours()>=10)
    out.push({type:'warn',icon:'📟',title:"Today's tank stock not entered",
      desc:'Copy the ATG reading into the Dip page so the Order Advisor works from the real tank level',
      action:'ENTER →',page:'dip'});
  if(typeof dipReadings==='undefined'||!dipReadings.length)return out;
  var cfg=tankCfg();
  var from=(function(){var d=new Date();d.setDate(d.getDate()-30);return _isoLocal(d);})();
  ['MSD','HSD'].forEach(function(t){
    var mine=_dipSortedLive().filter(function(r){return r.type===t&&!r.unused&&r.date>=from;});
    if(!mine.length)return;
    var last=mine[mine.length-1], a=last.atg||_atgFromNotes(last.notes);
    if(a&&a.water>0)out.push({type:'danger',icon:'💧',title:'Water in the '+t+' tank: '+a.water+' L',
      desc:'ATG reading of '+last.date+' — get it checked before it reaches the dispensers',action:'DIP →',page:'dip'});
    var total=mine.reduce(function(s,r){return s+(r.variation||0);},0);
    if(Math.abs(total)<=cfg.tol)return;
    var rate=(typeof _fuelWAC==='function'?_fuelWAC(t):0);
    out.push({type:total<0?'danger':'warn',icon:'📏',
      title:t+' stock variation '+(total>=0?'+':'')+total.toFixed(1)+' L (30 days)',
      desc:(total<0?'Physical stock is short of book':'Physical stock exceeds book')+
        (rate>0?' — worth '+fmt(Math.abs(total)*rate)+' at cost':''),
      action:'DIP →',page:'dip'});
  });
  return out;
}"""),

("V2b weekly leak check: live variation, used dips",
"""const v=dipReadings.filter(x=>x.type===t&&x.date>=w0&&x.date<=lastDay).reduce((s,x)=>s+(x.variation||0),0);""",
"""const v=dipReadings.filter(x=>x.type===t&&x.date>=w0&&x.date<=lastDay&&!(typeof _dipBeforeOpening==='function'&&_dipBeforeOpening(x))).reduce((s,x)=>s+(typeof _dipLiveVar==='function'?_dipLiveVar(x):(x.variation||0)),0);   // MF_ATG_REVERSE_V1"""),

("V5 bookStock: exactly at the opening point uses the opening",
"""    if(_posCmp(_asOf,_opR,date,rank)<0 &&""",
"""    if(_posCmp(_asOf,_opR,date,rank)<=0 &&   // MF_ATG_REVERSE_V1: <= so the opening point itself reads the opening"""),

("V6 dashboard: days left / order by",
"""• today ${nf(disp,1)} L<br>${_esc(b.since)}:""",
"""• today ${nf(disp,1)} L${_tankEta(cls==='msd'?'MSD':'HSD')}<br>${_esc(b.since)}:"""),

("V6b dashboard helper",
"""  const tankRow = (name,col,cls,b,cap,disp)=>{""",
"""  // MF_ATG_REVERSE_V1: the Order Advisor's forecast, on the card itself.
  const _tankEta = (t)=>{ try{ const f=fuelForecast(t); if(f.daysLeft==null)return '';
      const ob=f.orderBy?' · order by '+f.orderBy.slice(8,10)+'/'+f.orderBy.slice(5,7):'';
      return ' • <span style="color:'+(f.orderInDays<=1?'var(--red)':'var(--text)')+'">≈'+f.daysLeft+' day'+(f.daysLeft!==1?'s':'')+' left'+ob+'</span>';
    }catch(e){ return ''; } };
  const tankRow = (name,col,cls,b,cap,disp)=>{"""),

# ───────── 2. payment reversal ─────────
("R1 payment history: REVERSE column",
"""        '<th>DATE</th><th>AMOUNT</th><th>MODE</th><th>APPLIED TO</th><th>REF</th><th>NOTE</th>'+""",
"""        '<th>DATE</th><th>AMOUNT</th><th>MODE</th><th>APPLIED TO</th><th>REF</th><th>NOTE</th><th></th>'+"""),

("R1b payment history: group key",
"""    if(!groups[k])groups[k]={ref:p.ref,date:p.date,mode:p.mode,note:p.note,""",
"""    if(!groups[k])groups[k]={key:k,ref:p.ref,date:p.date,mode:p.mode,note:p.note,"""),

("R1c payment history: REVERSE button",
"""       '<td style="font-size:11px;color:var(--muted)">'+_esc(String(g.note||''))+'</td></tr>';""",
"""       '<td style="font-size:11px;color:var(--muted)">'+_esc(String(g.note||''))+'</td>'+
       // MF_ATG_REVERSE_V1
       '<td>'+(g.source==='shift'?'':'<button class="btn btn-g" style="padding:2px 8px;font-size:10px" '+
         'onclick="reversePayment(\\''+_esc(String(g.key)).replace(/'/g,'')+'\\')">↶ REVERSE</button>')+'</td></tr>';"""),

("R2 reversePayment()",
"""function deleteCustomer(name){""",
"""// MF_ATG_REVERSE_V1 — take back a payment entered by mistake. It undoes exactly
// what the payment did: its amount comes back off the bills it cleared (by
// the per-bill split recorded when it was taken), and the advance it created
// goes. The payment record is removed so reports stop counting it on its date;
// the activity log keeps the full detail and the reason.
function reversePayment(key){
  var name=currentLedgerCustomer; if(!name)return;
  var role=(_currentUser&&_currentUser.role)||'';
  if(!(_isOwner||role==='manager')){showToast('🔒 Only an owner or manager can reverse a payment');return;}
  var pays=ledgerPayments.filter(function(p){return p.customer===name&&(p.ref||('id:'+p.id))===key;});
  if(!pays.length){showToast('Payment not found');return;}
  if(pays.some(function(p){return p.source==='shift';})){
    showToast('Collected in a shift — delete and re-enter that shift to correct it');return;}
  var ref=pays[0].ref||'', date=pays[0].date||'', mode=pays[0].mode||'';
  var total=_r2(pays.reduce(function(s,p){return s+(+p.amount||0);},0));
  var billPays=pays.filter(function(p){return p.kind!=='advance'&&p.ledgerId!=null;});
  var advAmt=_r2(pays.filter(function(p){return p.kind==='advance';}).reduce(function(s,p){return s+(+p.amount||0);},0));
  var advRows=(ref&&advAmt>0)?ledger.filter(function(e){
    return e.customer===name&&(e.amount||0)<0&&String(e.notes||'').indexOf(ref+':')===0;}):[];
  if(advRows.some(function(e){return (e.paidBack||0)>0.005;})){
    showToast('The advance from this payment has already been used — reverse that first');return;}
  var bills=billPays.map(function(p){
    return {p:p,bill:ledger.find(function(e){return String(_intId(e.id))===String(_intId(p.ledgerId));})};
  });
  var missing=bills.filter(function(x){return !x.bill;}).length;
  var msg='Reverse '+fmt(total)+' received from '+name+' on '+date+' ('+mode+')?\\n\\n'+
    '• '+bills.length+' bill(s) go back to unpaid by what this payment cleared'+
    (advAmt>0?'\\n• the '+fmt(advAmt)+' advance it created is removed':'')+
    (missing?'\\n• '+missing+' bill(s) no longer exist and are skipped':'')+
    '\\n\\nOnly for a payment entered by mistake. Type the reason:';
  var reason=prompt(msg,'Entered by mistake');
  if(reason===null)return;
  reason=_clean(String(reason).trim())||'Entered by mistake';
  var today=_isoLocal();
  bills.forEach(function(x){
    if(!x.bill)return;
    x.bill.paidBack=_r2(Math.max(0,(x.bill.paidBack||0)-(+x.p.amount||0)));
    x.bill.notes=((x.bill.notes?x.bill.notes+' | ':'')+'REVERSED '+(ref||key)+': −'+fmt(+x.p.amount||0)+' '+today).slice(0,480);
    _touch(x.bill);
    if(_currentUser)sbSaveLedgerEntry(x.bill).catch(console.error);
  });
  if(advRows.length){
    var drop=new Set(advRows.map(function(e){return String(e.id);}));
    ledger=ledger.filter(function(e){return !drop.has(String(e.id));});
    if(_currentUser)drop.forEach(function(i){sbDeleteLedgerEntry(i).catch(console.error);});
  }
  var pid=new Set(pays.map(function(p){return String(p.id);}));
  ledgerPayments=ledgerPayments.filter(function(p){return !pid.has(String(p.id));});
  savePaymentsLS();
  if(_currentUser&&MF_PAYTBL_OK)pays.forEach(function(p){sbDelete('ledger_payments',_intId(p.id)).catch(console.error);});
  saveLedger();
  if(typeof logActivity==='function')logActivity('reverse_payment','ledger',ref||key,
    name+' • reversed '+fmt(total)+' ('+mode+', '+date+') • '+bills.length+' bill(s)'+
    (advAmt>0?' + '+fmt(advAmt)+' advance':'')+' • reason: '+reason);
  refreshCreditSelects();refreshCredBackSelects();
  openLedgerDetail(name);
  showToast('↶ '+fmt(total)+' reversed — bills are back to unpaid');
}
function deleteCustomer(name){"""),
]


def main():
    if not os.path.exists(PATH):
        sys.exit(f"✗ {PATH} not found")
    src = open(PATH, encoding="utf-8").read()
    if "MF_DIP_SYNC_V1" not in src:
        sys.exit("✗ Apply patch_dip_sync.py (MF_DIP_SYNC_V1) first. Nothing written.")
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
