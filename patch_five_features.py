#!/usr/bin/env python3
"""
MF_FIVE_V1 — five features on top of MF_ATG_REVERSE_V1.

1) GAUGE vs METER (month to date)
   G1 ATG card: "MONTH TILL DATE (L)" per tank, kept in the dip notes.
   G2 _atgMeterCheck(): between two gauge readings in the same month, what
      the gauge says was sold vs what the meters billed (minus testing
      returned). Same points on the timeline, so the 6 PM / midnight
      mismatch between shifts and the gauge's day does not come into it.
      Deliveries do not come into it either, so a load entered wrongly
      cannot hide a meter problem the way it can in the dip variation.
   G3 Shown under the daily stock list; alert beyond 0.5 % (min 30 L).

2) CREDIT LIMITS
   C1 Ledger: CREDIT LIMIT badge + panel — ₹ limit and max days unpaid.
      Stored in customer_profiles.billing (jsonb, already synced).
   C2 saveCustBilling kept the limit (it used to replace the whole block).
   C3 Shift entry: each credit row says when this credit takes the customer
      over the limit, or when their oldest bill is past the allowed days.
   C4 Save confirmation lists the same warnings.
   C5 Dashboard alert: customers over limit / past their days.

3) TANKER DELIVERY CHECK
   T1 Each fuel load gets a "📏 DELIVERY CHECK": gauge litres before and
      after unloading, litres sold while unloading, density measured.
      Received = after − before + sold while unloading; compared with the
      invoice volume (flag beyond 0.2 %, min 10 L) and the challan density
      (flag beyond 3 kg/m³).
   T2 Synced in fuel_loads.receipt (jsonb) — run db/017_five_features.sql.
      Until then it stays on the device that entered it, no error.
   T3 Dashboard alert for short deliveries in the last 60 days.

4) DAILY SUMMARY — already sent by db/015 (evening report once the night
   shift is saved). db/017 adds tank stock, days left and water to it.

5) CASH SHORTAGES BY STAFF
   S1 Staff → payroll page: last 30 days, each short shift (≥ ₹50) split
      between the staff marked on duty. Shifts worked, short shifts, share.

Usage:  python3 patch_five_features.py [path/to/index.html]
Idempotent. Requires MF_ATG_REVERSE_V1.
"""
import shutil, subprocess, sys, re, os, tempfile

PATH = sys.argv[1] if len(sys.argv) > 1 else "index.html"
SENTINEL = "MF_FIVE_V1"

HUNKS = [
# ═════════ 1. gauge vs meter ═════════
("G1a ATG card: MS month-till-date",
r"""<div><label>TODAY'S SALE (L)</label><input type="number" step="0.01" inputmode="decimal" id="atg_ms_sale" placeholder="227.05"></div>""",
r"""<div><label>TODAY'S SALE (L)</label><input type="number" step="0.01" inputmode="decimal" id="atg_ms_sale" placeholder="227.05"></div>
            <div><label>MONTH TILL DATE (L)</label><input type="number" step="0.01" inputmode="decimal" id="atg_ms_mtd" placeholder="27755.70"></div>"""),

("G1b ATG card: HSD month-till-date",
r"""<div><label>TODAY'S SALE (L)</label><input type="number" step="0.01" inputmode="decimal" id="atg_hsd_sale" placeholder="496.46"></div>""",
r"""<div><label>TODAY'S SALE (L)</label><input type="number" step="0.01" inputmode="decimal" id="atg_hsd_sale" placeholder="496.46"></div>
            <div><label>MONTH TILL DATE (L)</label><input type="number" step="0.01" inputmode="decimal" id="atg_hsd_mtd" placeholder="29328.32"></div>"""),

("G1c notes: write month-till-date",
r"""  return 'ATG · '+a.mm+' mm · '+a.temp+'°C · water '+a.water+' L'+(a.sale!=null?' · ATG sale '+a.sale+' L':'');""",
r"""  return 'ATG · '+a.mm+' mm · '+a.temp+'°C · water '+a.water+' L'+(a.sale!=null?' · ATG sale '+a.sale+' L':'')+
    (a.mtd!=null?' · MTD '+a.mtd+' L':'');   // MF_FIVE_V1"""),

("G1d notes: read month-till-date",
r"""  var m=/ATG · ([\d.]+) mm · ([\d.-]+)°C · water ([\d.]+) L(?: · ATG sale ([\d.]+) L)?/.exec(String(n||''));
  return m?{mm:+m[1],temp:+m[2],water:+m[3],sale:m[4]!=null?+m[4]:null}:null;""",
r"""  var m=/ATG · ([\d.]+) mm · ([\d.-]+)°C · water ([\d.]+) L(?: · ATG sale ([\d.]+) L)?(?: · MTD ([\d.]+) L)?/.exec(String(n||''));
  return m?{mm:+m[1],temp:+m[2],water:+m[3],sale:m[4]!=null?+m[4]:null,mtd:m[5]!=null?+m[5]:null}:null;   // MF_FIVE_V1"""),

("G1e submitAtg: capture month-till-date",
r"""           water:_atgVal('atg_'+t[1]+'_water')||0, sale:_atgVal('atg_'+t[1]+'_sale')};""",
r"""           water:_atgVal('atg_'+t[1]+'_water')||0, sale:_atgVal('atg_'+t[1]+'_sale'),
           mtd:_atgVal('atg_'+t[1]+'_mtd')};   // MF_FIVE_V1"""),

("G1f submitAtg: clear month-till-date",
r"""['vol','mm','water','temp','sale'].forEach(function(f){""",
r"""['vol','mm','water','temp','sale','mtd'].forEach(function(f){"""),

("G2 _atgMeterCheck()",
r"""function _renderAtgList(){""",
r"""// MF_FIVE_V1 — gauge vs meters. Between two gauge readings in the same month
// the gauge's month-till-date counter moved by what left the tank as sales;
// the meters for the same stretch, less the test fuel poured back, should
// match it. The gauge's own day (midnight) never has to line up with shifts.
function _atgMeterCheck(type,month){
  month=month||_isoLocal().slice(0,7);
  var rs=_dipSorted().filter(function(r){
    if(r.type!==type||String(r.date).slice(0,7)!==month)return false;
    var a=r.atg||_atgFromNotes(r.notes); return a&&a.mtd!=null;
  });
  var out={type:type,month:month,atg:0,meter:0,pairs:0,readings:rs.length};
  for(var i=1;i<rs.length;i++){
    var a0=rs[i-1].atg||_atgFromNotes(rs[i-1].notes), a1=rs[i].atg||_atgFromNotes(rs[i].notes);
    var d=a1.mtd-a0.mtd; if(!(d>=0))continue;          // counter reset or typo: skip the pair
    var mv=_tankMovement(type,{date:rs[i-1].date,rank:_slotRank(rs[i-1].slot)},
                              {date:rs[i].date,rank:_slotRank(rs[i].slot)});
    out.atg+=d; out.meter+=(mv.sold-mv.tested); out.pairs++;
  }
  out.atg=_r2(out.atg); out.meter=_r2(out.meter); out.gap=_r2(out.meter-out.atg);
  out.tol=Math.max(30,out.atg*0.005);
  out.pct=out.atg>0?out.gap/out.atg*100:0;
  out.bad=out.pairs>0&&Math.abs(out.gap)>out.tol;
  return out;
}
function _renderAtgList(){"""),

("G3 daily list: gauge vs meter line",
r"""       cell(m)+cell(s)+'<td style="font-size:10px;color:var(--muted)">'+src+'</td></tr>';
  });
  el.innerHTML=h+'</tbody></table>';""",
r"""       cell(m)+cell(s)+'<td style="font-size:10px;color:var(--muted)">'+src+'</td></tr>';
  });
  // MF_FIVE_V1: gauge vs meters, this month
  var gm=['MSD','HSD'].map(function(t){
    var c=_atgMeterCheck(t); if(!c.pairs)return '<span style="color:var(--muted)">'+t+': needs two readings with month-till-date this month</span>';
    return '<span style="color:'+(c.bad?(c.gap<0?'var(--red)':'var(--diesel)'):'var(--green)')+'">'+t+': gauge sold '+
      c.atg.toLocaleString('en-IN',{maximumFractionDigits:0})+' L · meters '+c.meter.toLocaleString('en-IN',{maximumFractionDigits:0})+
      ' L · gap '+(c.gap>=0?'+':'')+c.gap.toFixed(1)+' L ('+(c.pct>=0?'+':'')+c.pct.toFixed(2)+'%)</span>';
  });
  h+='</tbody></table><div style="font-family:\'JetBrains Mono\',monospace;font-size:10px;margin-top:8px;line-height:1.7">'+
     '<b style="color:var(--muted)">GAUGE vs METERS THIS MONTH</b><br>'+gm.join('<br>')+'</div>';
  el.innerHTML=h;"""),

("G3b alerts: gauge vs meter",
r"""  var cfg=tankCfg();
  var from=(function(){var d=new Date();d.setDate(d.getDate()-30);return _isoLocal(d);})();""",
r"""  var cfg=tankCfg();
  // MF_FIVE_V1: gauge vs meters
  ['MSD','HSD'].forEach(function(t){
    var c=_atgMeterCheck(t); if(!c.bad)return;
    out.push(c.gap<0
      ? {type:'danger',icon:'⛽',title:t+': '+Math.abs(c.gap).toFixed(0)+' L left the tank without being billed',
         desc:'Gauge sold '+c.atg.toFixed(0)+' L this month, meters '+c.meter.toFixed(0)+' L. Check dispenser calibration and unrecorded sales.',action:'DIP →',page:'dip'}
      : {type:'warn',icon:'⛽',title:t+': meters '+c.gap.toFixed(0)+' L above what left the tank',
         desc:'Meters '+c.meter.toFixed(0)+' L vs gauge '+c.atg.toFixed(0)+' L this month. Dispensers may be over-registering — customers get less than billed.',action:'DIP →',page:'dip'});
  });
  var from=(function(){var d=new Date();d.setDate(d.getDate()-30);return _isoLocal(d);})();"""),

# ═════════ 2. credit limits ═════════
("C1a ledger header: limit badge",
r"""        <button onclick="editCustDiscount()" style="font-family:'Syne',sans-serif;font-size:10px;background:transparent;border:1px solid var(--border2);color:var(--muted);padding:2px 8px;border-radius:3px;cursor:pointer;font-weight:700">EDIT</button>
      </div>""",
r"""        <button onclick="editCustDiscount()" style="font-family:'Syne',sans-serif;font-size:10px;background:transparent;border:1px solid var(--border2);color:var(--muted);padding:2px 8px;border-radius:3px;cursor:pointer;font-weight:700">EDIT</button>
      </div>
      <!-- MF_FIVE_V1: credit limit badge -->
      <div style="display:flex;align-items:center;gap:6px;background:var(--s3);border:1px solid var(--border2);border-radius:6px;padding:5px 10px">
        <span style="font-family:'Syne',sans-serif;font-weight:700;font-size:10px;letter-spacing:1px;color:var(--muted)">CREDIT LIMIT</span>
        <span id="cust_limit_display" style="font-family:'JetBrains Mono',monospace;font-size:12px;font-weight:700;color:var(--text)">none</span>
        <button onclick="editCustLimit()" style="font-family:'Syne',sans-serif;font-size:10px;background:transparent;border:1px solid var(--border2);color:var(--muted);padding:2px 8px;border-radius:3px;cursor:pointer;font-weight:700">EDIT</button>
      </div>"""),

("C1b ledger: limit panel",
r"""    <!-- Move an amount between two customer accounts. Both sides are written. -->""",
r"""    <!-- MF_FIVE_V1: credit limit panel -->
    <div id="cust_limit_panel" style="display:none;margin-bottom:12px">
      <div class="card" style="border-color:var(--blue);max-width:520px">
        <div class="card-head" style="color:var(--blue)">CREDIT LIMIT — <span id="limit_panel_name"></span></div>
        <div style="display:flex;gap:10px;align-items:flex-end;flex-wrap:wrap">
          <div><div class="flabel" style="margin-bottom:4px">MAX OUTSTANDING (₹)</div>
            <input type="number" id="limit_amt_inp" placeholder="e.g. 50000" step="100" min="0" style="width:150px"></div>
          <div><div class="flabel" style="margin-bottom:4px">MAX DAYS UNPAID</div>
            <input type="number" id="limit_days_inp" placeholder="e.g. 30" step="1" min="0" style="width:110px"></div>
          <button class="save-btn" style="padding:6px 16px" onclick="saveCustLimit()">&#10003; SAVE</button>
          <button class="btn btn-g" onclick="document.getElementById('cust_limit_panel').style.display='none'">&#10005;</button>
        </div>
        <div id="limit_preview" style="margin-top:8px;font-family:'JetBrains Mono',monospace;font-size:11px;color:var(--muted);line-height:1.5">
          Leave a box empty or 0 for no limit. Staff are warned when entering credit in a shift; owners get a dashboard alert.</div>
      </div>
    </div>
    <!-- Move an amount between two customer accounts. Both sides are written. -->"""),

("C1c open detail: show limit",
r"""  document.getElementById('cust_disc_display').textContent=discRate>0?'₹'+discRate.toFixed(2)+'/L':'₹0/L';""",
r"""  document.getElementById('cust_disc_display').textContent=discRate>0?'₹'+discRate.toFixed(2)+'/L':'₹0/L';
  if(typeof _renderCustLimitBadge==='function')_renderCustLimitBadge(name);   // MF_FIVE_V1
  var _lp=document.getElementById('cust_limit_panel'); if(_lp)_lp.style.display='none';"""),

("C1d limit functions",
r"""function saveCustDiscountRate(){""",
r"""// MF_FIVE_V1 ── credit limits ───────────────────────────────────────────
function _custLimit(name){
  var b=(customerProfiles[name]&&customerProfiles[name].billing)||{};
  return {limit:parseFloat(b.creditLimit)||0, days:parseInt(b.creditDays,10)||0};
}
// Where the customer would stand with `adding` more credit on top.
function _custLimitState(name,adding){
  var L=_custLimit(name); if(!(L.limit>0)&&!(L.days>0))return null;
  var pos=_custPosition(name), exp=_r2(pos.net+(adding||0));
  var un=_custUnpaid(name), oldest=un.length?un[0].date:null;
  var age=oldest?Math.floor((Date.parse(_isoLocal())-Date.parse(oldest))/86400000):0;
  return {L:L, exposure:exp, over:L.limit>0&&exp>L.limit+0.5, late:L.days>0&&age>L.days, age:age, oldest:oldest};
}
function _custLimitMsg(name,st){
  var m=[];
  if(st.over)m.push('over limit — owes '+fmt(st.exposure)+' with this (limit '+fmt(st.L.limit)+')');
  if(st.late)m.push('oldest unpaid bill '+st.age+' days old (allowed '+st.L.days+')');
  return m.join('; ');
}
function _renderCustLimitBadge(name){
  var el=document.getElementById('cust_limit_display'); if(!el)return;
  var L=_custLimit(name);
  if(!(L.limit>0)&&!(L.days>0)){el.textContent='none';el.style.color='var(--muted)';return;}
  var st=_custLimitState(name,0);
  el.textContent=(L.limit>0?fmt(L.limit):'no ₹ cap')+(L.days>0?' · '+L.days+'d':'');
  el.style.color=(st&&(st.over||st.late))?'var(--red)':'var(--text)';
  el.title=st&&(st.over||st.late)?_custLimitMsg(name,st):'';
}
function editCustLimit(){
  var name=currentLedgerCustomer; if(!name)return;
  var p=document.getElementById('cust_limit_panel'); if(!p)return;
  var L=_custLimit(name);
  document.getElementById('limit_panel_name').textContent=name;
  document.getElementById('limit_amt_inp').value=L.limit||'';
  document.getElementById('limit_days_inp').value=L.days||'';
  p.style.display=p.style.display==='none'?'block':'none';
}
function saveCustLimit(){
  var name=currentLedgerCustomer; if(!name)return;
  var role=(_currentUser&&_currentUser.role)||'';
  if(_currentUser&&!(_isOwner||role==='manager')){showToast('🔒 Only an owner or manager can set credit limits');return;}
  var lim=Math.max(0,parseFloat(document.getElementById('limit_amt_inp').value)||0);
  var days=Math.max(0,parseInt(document.getElementById('limit_days_inp').value,10)||0);
  if(!customerProfiles[name])customerProfiles[name]={};
  customerProfiles[name].billing=Object.assign({},customerProfiles[name].billing||{},{creditLimit:lim,creditDays:days});
  saveCustProfiles();
  if(_currentUser&&typeof sbSaveCustProfile==='function')sbSaveCustProfile(name).catch(console.error);
  if(typeof logActivity==='function')logActivity('set_limit','customer',name,
    'Credit limit '+(lim?fmt(lim):'none')+', max '+(days?days+' days':'no day limit'));
  document.getElementById('cust_limit_panel').style.display='none';
  _renderCustLimitBadge(name);
  showToast('Credit limit saved for '+name);
}
// Credit rows in the shift being entered, summed per customer.
function _shiftCreditByCustomer(){
  var by={};
  document.querySelectorAll('#cred_list .cred-row').forEach(function(row){
    var sel=row.querySelector('.cred-name-sel'), inp=row.querySelector('.cred-new-name');
    var name=(sel&&sel.style.display!=='none'&&sel.value!=='__new__')?sel.value:(inp?_clean(inp.value.trim()):'');
    var amt=parseFloat((row.querySelector('.cred-amt')||{}).value)||0;
    if(!name)return;
    (by[name]=by[name]||{amt:0,rows:[]}).amt+=amt; by[name].rows.push(row);
  });
  return by;
}
function _credLimitHints(){
  var by=_shiftCreditByCustomer();
  document.querySelectorAll('#cred_list .cred-limit-hint').forEach(function(h){h.textContent='';});
  Object.keys(by).forEach(function(name){
    var st=_custLimitState(name,by[name].amt); if(!st||!(st.over||st.late))return;
    var h=by[name].rows[by[name].rows.length-1].querySelector('.cred-limit-hint');
    if(h){h.style.color='var(--red)';h.textContent='⚠ '+name+': '+_custLimitMsg(name,st);}
  });
}
function _credLimitIssues(){
  var by=_shiftCreditByCustomer(), out=[];
  Object.keys(by).forEach(function(name){
    var st=_custLimitState(name,by[name].amt);
    if(st&&(st.over||st.late))out.push({level:'warn',machine:'Credit — '+name,msg:_custLimitMsg(name,st)});
  });
  return out;
}
function _creditLimitAlerts(){
  var names=[...new Set(ledger.map(function(e){return e.customer;}))], over=[];
  names.forEach(function(n){ var st=_custLimitState(n,0); if(st&&(st.over||st.late))over.push({n:n,st:st}); });
  if(!over.length)return [];
  return [{type:'danger',icon:'🚫',title:over.length+' customer'+(over.length>1?'s':'')+' past their credit limit',
    desc:over.slice(0,3).map(function(o){return o.n+' ('+(o.st.over?fmt(o.st.exposure):o.st.age+'d')+')';}).join(', ')+(over.length>3?'…':''),
    action:'LEDGER',page:'ledger'}];
}
document.addEventListener('change',function(e){
  if(e.target&&e.target.classList&&e.target.classList.contains('cred-name-sel'))_credLimitHints();
});
document.addEventListener('input',function(e){
  if(e.target&&e.target.classList&&e.target.classList.contains('cred-new-name'))_credLimitHints();
});
function saveCustDiscountRate(){"""),

("C2 billing save keeps the limit",
r"""  customerProfiles[name].billing={company:g('cb_company')||name,gstin:g('cb_gstin'),
    address:g('cb_address'),phone:g('cb_phone'),email:g('cb_email')};""",
r"""  // MF_FIVE_V1: merge, so the credit limit kept in the same block survives.
  customerProfiles[name].billing=Object.assign({},customerProfiles[name].billing||{},
    {company:g('cb_company')||name,gstin:g('cb_gstin'),
     address:g('cb_address'),phone:g('cb_phone'),email:g('cb_email')});"""),

("C3a shift credit row: hint line",
r"""    <button class="rm-btn" onclick="document.getElementById('cr_${id}').remove();calc()">\u2715</button>`;
  document.getElementById('cred_list').appendChild(d);""",
r"""    <button class="rm-btn" onclick="document.getElementById('cr_${id}').remove();calc()">\u2715</button>
    <div class="cred-limit-hint" style="grid-column:1/-1;font-family:'JetBrains Mono',monospace;font-size:10px;line-height:1.4"></div>`;
  document.getElementById('cred_list').appendChild(d);"""),

("C3b calc(): refresh credit hints",
r"""  _syncTestingFuel();
  const gpay=v('p_gpay'),paytm=v('p_paytm'),cash=v('p_cash');""",
r"""  _syncTestingFuel();
  try{ if(typeof _credLimitHints==='function')_credLimitHints(); }catch(e){}   // MF_FIVE_V1
  const gpay=v('p_gpay'),paytm=v('p_paytm'),cash=v('p_cash');"""),

("C4 save confirmation: credit warnings",
r"""  Array.prototype.push.apply(_extra, validateContinuity());""",
r"""  Array.prototype.push.apply(_extra, validateContinuity());
  if(typeof _credLimitIssues==='function')Array.prototype.push.apply(_extra, _credLimitIssues());   // MF_FIVE_V1"""),

("C5+T3 dashboard alerts",
r"""  if(typeof _dipAlerts==='function')Array.prototype.push.apply(alerts,_dipAlerts());""",
r"""  if(typeof _dipAlerts==='function')Array.prototype.push.apply(alerts,_dipAlerts());
  try{ if(typeof _creditLimitAlerts==='function')Array.prototype.push.apply(alerts,_creditLimitAlerts()); }catch(e){}   // MF_FIVE_V1
  try{ if(typeof _receiptAlerts==='function')Array.prototype.push.apply(alerts,_receiptAlerts()); }catch(e){}"""),

# ═════════ 3. tanker delivery check ═════════
("T1a load card: delivery check block",
r"""          :'<span class="badge bg_" style="margin-left:auto">&#10003; FULLY PAID</span>'}
      </div>`;""",
r"""          :'<span class="badge bg_" style="margin-left:auto">&#10003; FULLY PAID</span>'}
      </div>
      ${typeof _flReceiptHtml==='function'?_flReceiptHtml(l):''}`;"""),

("T1b delivery check functions",
r"""function renderFuelLoads(){""",
r"""// MF_FIVE_V1 ── tanker delivery check ───────────────────────────────────
var MF_RECEIPT_COL=null;   // false once fuel_loads is proven to have no receipt column
function _normDensity(d){ d=parseFloat(d); if(!(d>0))return null; return d>2?d/1000:d; }   // 745 → 0.745
function _receiptEval(l){
  var r=l&&l.receipt; if(!r||r.before==null||r.after==null)return null;
  var inv=parseFloat(l.vol)||0;
  var got=_r2((+r.after)-(+r.before)+(+r.soldDuring||0));
  var diff=_r2(got-inv);                               // negative = short
  var tol=Math.max(10,inv*0.002);
  var dc=_normDensity(l.density), dobs=_normDensity(r.density);
  var dd=(dc&&dobs)?Math.round((dobs-dc)*1000*10)/10:null;   // kg/m³
  return {got:got,inv:inv,diff:diff,tol:tol,short:diff<-tol,over:diff>tol,
          pct:inv>0?diff/inv*100:0,dd:dd,dBad:dd!=null&&Math.abs(dd)>3};
}
function _flReceiptHtml(l){
  var e=_receiptEval(l), r=l.receipt||{};
  var sum=e
    ? '<span style="color:'+(e.short?'var(--red)':e.over?'var(--diesel)':'var(--green)')+'">Received '+e.got.toFixed(0)+' L vs invoice '+e.inv.toFixed(0)+' L — '+
        (e.short?'SHORT '+Math.abs(e.diff).toFixed(1)+' L':e.over?'over by '+e.diff.toFixed(1)+' L':'OK ('+(e.diff>=0?'+':'')+e.diff.toFixed(1)+' L)')+
        ' ('+(e.pct>=0?'+':'')+e.pct.toFixed(2)+'%)</span>'+
      (e.dd!=null?' · <span style="color:'+(e.dBad?'var(--red)':'var(--green)')+'">density '+(e.dd>=0?'+':'')+e.dd+' kg/m³ vs challan</span>':'')+
      (r.by?' <span style="color:var(--muted)">('+_esc(String(r.by))+')</span>':'')
    : '<span style="color:var(--muted)">Not checked — gauge litres before and after unloading tell you what really arrived.</span>';
  var v=function(x){return x!=null&&x!==''?x:'';};
  return '<div style="margin-top:8px;background:var(--s3);padding:10px;border-radius:6px;font-family:\'JetBrains Mono\',monospace;font-size:11px">'+
    '<div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap"><b style="font-family:\'Syne\',sans-serif;font-size:10px;letter-spacing:1px;color:var(--muted)">📏 DELIVERY CHECK</b> '+sum+
    '<button class="btn btn-g" style="padding:3px 10px;font-size:10px;margin-left:auto" onclick="var f=document.getElementById(\'fl_rc_'+l.id+'\');f.style.display=f.style.display===\'none\'?\'flex\':\'none\'">'+(e?'EDIT':'CHECK')+'</button></div>'+
    '<div id="fl_rc_'+l.id+'" style="display:none;gap:8px;flex-wrap:wrap;align-items:flex-end;margin-top:8px">'+
      '<div><div class="flabel" style="margin-bottom:3px">GAUGE BEFORE (L)</div><input type="number" step="0.01" id="fl_rc_b_'+l.id+'" value="'+v(r.before)+'" style="width:120px"></div>'+
      '<div><div class="flabel" style="margin-bottom:3px">GAUGE AFTER (L)</div><input type="number" step="0.01" id="fl_rc_a_'+l.id+'" value="'+v(r.after)+'" style="width:120px"></div>'+
      '<div><div class="flabel" style="margin-bottom:3px">SOLD WHILE UNLOADING (L)</div><input type="number" step="0.01" id="fl_rc_s_'+l.id+'" value="'+v(r.soldDuring)+'" placeholder="0" style="width:120px"></div>'+
      '<div><div class="flabel" style="margin-bottom:3px">DENSITY MEASURED</div><input type="number" step="0.0001" id="fl_rc_d_'+l.id+'" value="'+v(r.density)+'" placeholder="'+(l.density||'0.745')+'" style="width:110px"></div>'+
      '<button class="save-btn" style="padding:6px 14px;max-width:140px" onclick="saveFuelReceipt('+l.id+')">✓ SAVE</button>'+
    '</div></div>';
}
function saveFuelReceipt(id){
  var l=fuelLoads.find(function(x){return String(x.id)===String(id);}); if(!l)return;
  var g=function(k){var e=document.getElementById('fl_rc_'+k+'_'+id);return e&&e.value!==''?parseFloat(e.value):null;};
  var b=g('b'), a=g('a');
  if(b==null||a==null){showToast('Enter the gauge litres before and after unloading');return;}
  if(a<b){showToast('After is less than before — check the readings');return;}
  var cap=l.type==='MSD'?tankCfg().capMSD:tankCfg().capHSD;
  if(a>cap){showToast('After '+a+' L is more than the '+cap+' L tank');return;}
  l.receipt={before:b,after:a,soldDuring:g('s')||0,density:g('d'),
             by:(_currentUser&&_currentUser.username)||'',at:new Date().toISOString()};
  _touch(l);
  localStorage.setItem('fuelLoads',JSON.stringify(fuelLoads));
  if(_currentUser&&typeof sbSaveFuelLoad==='function')sbSaveFuelLoad(l).catch(console.error);
  var e=_receiptEval(l);
  if(typeof logActivity==='function')logActivity('fuel_receipt','fuel_load',l.id,
    l.type+' '+l.date+' inv '+(l.inv||'')+' • received '+e.got.toFixed(1)+' L vs '+e.inv.toFixed(0)+' L ('+(e.diff>=0?'+':'')+e.diff.toFixed(1)+')'+
    (e.dd!=null?' • density '+(e.dd>=0?'+':'')+e.dd+' kg/m³':''));
  renderFuelLoads();
  showToast(e.short?'⚠ SHORT DELIVERY: '+Math.abs(e.diff).toFixed(1)+' L — raise it with the supplier':
            e.dBad?'⚠ Density off by '+e.dd+' kg/m³ against the challan':'✓ Delivery checked');
}
function _receiptAlerts(){
  var from=(function(){var d=new Date();d.setDate(d.getDate()-60);return _isoLocal(d);})();
  var bad=fuelLoads.filter(function(l){ if(String(l.date)<from)return false;
    var e=_receiptEval(l); return e&&(e.short||e.dBad); });
  if(!bad.length)return [];
  var litres=bad.reduce(function(s,l){var e=_receiptEval(l);return s+(e.short?-e.diff:0);},0);
  return [{type:'danger',icon:'🚛',title:bad.length+' tanker delivery problem'+(bad.length>1?'s':'')+' (60 days)',
    desc:(litres>0?litres.toFixed(0)+' L short in total':'')+(litres>0&&bad.some(function(l){return _receiptEval(l).dBad;})?' · ':'')+
         (bad.some(function(l){return _receiptEval(l).dBad;})?'density off the challan':'')+' — raise it with the supplier',
    action:'LOADS',page:'fuelload'}];
}
function renderFuelLoads(){"""),

("T2a save: receipt column with fallback",
r"""async function sbSaveFuelLoad(load) {
  if (!_currentUser) return;   // no _supa: _sbUpsert queues it
  try {
  await _sbUpsert('fuel_loads', {""",
r"""async function sbSaveFuelLoad(load) {
  if (!_currentUser) return;   // no _supa: _sbUpsert queues it
  try {
  const _row = {"""),

("T2b save: receipt column with fallback (tail)",
r"""    locked: load.locked||false,
    updated_at: _touch(load).updatedAt
  });
  } catch(e){ console.error('Save fuel load failed:',e.message); }""",
r"""    locked: load.locked||false,
    updated_at: _touch(load).updatedAt
  };
  // MF_FIVE_V1: delivery check rides in fuel_loads.receipt (db/017). Without the
  // column the row would be rejected whole, so try once and fall back.
  if (load.receipt && MF_RECEIPT_COL !== false) {
    _row.receipt = load.receipt;
    if (_supa && !(typeof navigator !== 'undefined' && navigator.onLine === false)) {
      const r = await _supa.from('fuel_loads').upsert(_row, { onConflict: 'id' });
      if (!r.error) { MF_RECEIPT_COL = true; return; }
      if (_isMissingCol(r.error.message) || /receipt/i.test(String(r.error.message))) {
        MF_RECEIPT_COL = false; delete _row.receipt;
        console.warn('fuel_loads has no receipt column — apply db/017_five_features.sql. Delivery checks stay on this device until then.');
      }
    }
  }
  await _sbUpsert('fuel_loads', _row);
  } catch(e){ console.error('Save fuel load failed:',e.message); }"""),

("T2c load: read receipt",
r"""        locked: l.locked||false, updatedAt: l.updated_at
      }));""",
r"""        locked: l.locked||false, updatedAt: l.updated_at,
        // MF_FIVE_V1: keep this device's check when the server has no column yet
        receipt: ('receipt' in l) ? (l.receipt||null)
                 : ((fuelLoads.find(function(x){return String(x.id)===String(l.id);})||{}).receipt||null)
      }));"""),

# ═════════ 5. staff shortages ═════════
("S1a staff page: container",
r"""    <div id="payroll_notes" style="display:flex;flex-direction:column;gap:6px;margin-top:12px"></div>""",
r"""    <div id="payroll_notes" style="display:flex;flex-direction:column;gap:6px;margin-top:12px"></div>
    <!-- MF_FIVE_V1: cash shortages by staff on duty -->
    <div id="staff_short_wrap" style="margin-top:16px"></div>"""),

("S1b staff report: render shortages",
r"""function renderStaffReport(){
  var mEl=document.getElementById('pay_month');""",
r"""// MF_FIVE_V1 — cash shortages by who was on duty. One short shift says little;
// the same name on most of them is a pattern worth a conversation.
function _staffShortRows(days){
  days=days||30;
  var from=(function(){var d=new Date();d.setDate(d.getDate()-days);return _isoLocal(d);})();
  var recs=records.filter(function(r){return String(r.date)>=from;});
  var by={}, unassigned={n:0,amt:0};
  var who=function(r){return (typeof staffAttendance!=='undefined'?staffAttendance:[]).filter(function(a){
    return a.date===r.date&&a.shift===r.shift&&(a.status==='present'||a.status==='half');}).map(function(a){return a.staffId;});};
  recs.forEach(function(r){
    var ids=who(r), short=(r.bal||0)<-50;
    if(short&&!ids.length){unassigned.n++;unassigned.amt+=-r.bal;}
    ids.forEach(function(id){
      var o=by[id]=by[id]||{id:id,worked:0,shortN:0,share:0,total:0};
      o.worked++;
      if(short){o.shortN++;o.total+=-r.bal;o.share+=-r.bal/ids.length;}
    });
  });
  var rows=Object.keys(by).map(function(k){
    var o=by[k], s=(typeof staffList!=='undefined'?staffList:[]).find(function(x){return String(x.id)===String(k);});
    o.name=s?s.name:('Staff '+k); o.rate=o.worked?o.shortN/o.worked:0;
    o.flag=o.shortN>=3&&o.rate>=0.4; return o;
  }).sort(function(a,b){return b.share-a.share;});
  return {rows:rows,unassigned:unassigned,from:from,shifts:recs.length,
          shortShifts:recs.filter(function(r){return (r.bal||0)<-50;}).length};
}
function renderStaffShortages(){
  var el=document.getElementById('staff_short_wrap'); if(!el)return;
  var R=_staffShortRows(30);
  var h='<div class="sec" style="margin-bottom:8px"><span class="dot dr"></span>CASH SHORTAGES BY STAFF ON DUTY — LAST 30 DAYS</div>'+
        '<div style="font-family:\'JetBrains Mono\',monospace;font-size:10px;color:var(--muted);margin-bottom:8px;line-height:1.5">'+
        R.shortShifts+' of '+R.shifts+' shifts short by ₹50 or more. Each shortage is split between everyone marked present on that shift. '+
        'A pattern, not proof — use it to decide who to watch or retrain.</div>';
  if(!R.rows.length){el.innerHTML=h+'<div style="font-size:11px;color:var(--muted)">No attendance marked in this period.</div>';return;}
  h+='<div style="overflow-x:auto"><table class="data-tbl" style="min-width:520px"><thead><tr><th>STAFF</th><th>SHIFTS WORKED</th>'+
     '<th>SHORT SHIFTS</th><th>% SHORT</th><th>SHARE OF SHORTAGE</th><th>TOTAL ON THEIR SHIFTS</th></tr></thead><tbody>';
  R.rows.forEach(function(o){
    h+='<tr><td><b>'+_esc(o.name)+'</b>'+(o.flag?' <span style="color:var(--red);font-size:10px">⚠ pattern</span>':'')+'</td>'+
       '<td>'+o.worked+'</td><td style="color:'+(o.shortN?'var(--red)':'var(--muted)')+'">'+o.shortN+'</td>'+
       '<td style="color:'+(o.rate>=0.4?'var(--red)':'var(--text)')+'">'+Math.round(o.rate*100)+'%</td>'+
       '<td style="font-weight:700">'+fmt(o.share)+'</td><td style="color:var(--muted)">'+fmt(o.total)+'</td></tr>';
  });
  h+='</tbody></table></div>';
  if(R.unassigned.n)h+='<div style="font-size:10px;color:var(--diesel);margin-top:6px">'+R.unassigned.n+
     ' short shift(s), '+fmt(R.unassigned.amt)+', had nobody marked on duty — mark attendance in the shift entry.</div>';
  el.innerHTML=h;
}
function renderStaffReport(){
  try{ renderStaffShortages(); }catch(e){ console.warn('staff shortages:',e); }   // MF_FIVE_V1
  var mEl=document.getElementById('pay_month');"""),
]


def main():
    if not os.path.exists(PATH):
        sys.exit(f"✗ {PATH} not found")
    src = open(PATH, encoding="utf-8").read()
    if "MF_ATG_REVERSE_V1" not in src:
        sys.exit("✗ Apply patch_atg_reverse.py (MF_ATG_REVERSE_V1) first. Nothing written.")
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
