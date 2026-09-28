#!/usr/bin/env python3
"""
MF_FUELLOAD_V1 — Fuel loads upgrade.

FIXES
  1 EDIT        Editing a load dropped its delivery check (gauge readings,
                measured density) and reset density to 0.820 — wrong for
                petrol. The check, claim and payment history now stay; the
                challan density is a field on the form (blank = not known).
                The old hard-coded 0.820 is ignored in the density check, so
                petrol loads stop showing a false "density off" alarm.
  2 LOCKED      A locked load could not be paid. Locking freezes the bill,
                not the payments.
  3 OVERPAY     An overpayment was silently cut to the due; now refused.
                Every payment goes into the activity log.
  4 DELETE      Anyone could delete an unlocked load, even with payments.
                Owner / manager only, refused while dated payments stand,
                with a reason in the log.
  5 PUMP RATE   A back-dated load changed TODAY's pump rate. Loads older
                than yesterday now ask first.
  6 COMPARISON  "Loads vs shift balance" set tanker profit against cash
                short/excess — unrelated numbers. Replaced by item 10.

NEW
  7 PAYMENTS    Dated part-payments (mode, UTR/cheque, date), reverse for
                owner/manager; older paid totals stay as one undated line.
                Statement and Dues post them on their dates.
                fuel_loads.payments — db/019 (works without it until run).
  8 DUE DATES   Supplier credit days (same ⚙ as oil bills), OVERDUE on the
                card, dashboard alert, Dues view.
  9 DUPLICATES  Same invoice + supplier asks before saving.
 10 ACTUAL      Per load: average pump rate from unloading to the next load,
                less its cost per litre, against the expected profit.
 11 HISTORY     Filters (fuel, month, supplier, unpaid / overdue / short /
                claim open / not checked) and month totals with ₹/L trend.
 12 SHORT       Short delivery → RAISE CLAIM (then CREDIT NOTE, which comes
                off the load's cost) or ACCEPT LOSS. Either way the tank then
                counts the litres actually received, and cost per litre is on
                those litres. Rides in fuel_loads.receipt (db/017).

Usage:  python3 patch_fuel_loads.py [path/to/index.html]   (idempotent)
Requires MF_FIVE_V1, MF_OIL_V1 and MF_REPORTS_V1.
"""
import shutil, subprocess, sys, re, os, tempfile

PATH = sys.argv[1] if len(sys.argv) > 1 else "index.html"
SENTINEL = "MF_FUELLOAD_V1"

MODULE = r"""// ══════════════════════════════════════════════════════════════════
// FUEL LOADS — MF_FUELLOAD_V1
//   payments      dated part-payments (fuel_loads.payments, db/019), reverse
//   due dates     supplier credit days (the same ⚙ setting as oil bills)
//   short loads   claim → credit note (comes off the load's cost), or accept
//                 the loss (the tank counts the litres actually received)
//   actual margin average pump rate from unloading to the next load, less
//                 this load's cost per litre — an estimate per tanker
//   history       filters and month totals
// ══════════════════════════════════════════════════════════════════
var MF_FLPAY_COL=null;   // false once fuel_loads is proven to have no payments column
function _flCan(){ return !_currentUser||_isOwner||(_currentUser&&_currentUser.role==='manager'); }
function _flTotal(l){ return +(l&&(l.totalCost!=null?l.totalCost:l.total_cost))||0; }
// A load paid before dates were kept: its paid total stands as one undated
// line. Once a payments list exists it is the record, even when empty (every
// payment reversed) — falling back to amountPaid then would bring it back.
function _flPaysList(l){
  if(Array.isArray(l.payments))return l.payments;
  var a=+l.amountPaid||0;
  return a>0?[{id:'legacy',date:l.date,amount:a,mode:'—',ref:'',note:'recorded before payment dates were kept',legacy:true}]:[];
}
function _flPaid(l){ return _r2(_flPaysList(l).reduce(function(s,p){ return s+(+p.amount||0); },0)); }
function _flDue(l){ return _r2(Math.max(0,_flTotal(l)-_flPaid(l))); }
function _flSave(l){
  l.amountPaid=_flPaid(l); l.amountDue=_flDue(l);
  _touch(l);
  localStorage.setItem('fuelLoads',JSON.stringify(fuelLoads));
  if(_currentUser&&typeof sbSaveFuelLoad==='function')sbSaveFuelLoad(l).catch(console.error);
}
function _flFind(id){ return fuelLoads.find(function(x){ return String(x.id)===String(id); }); }
function _flUser(){ return (_currentUser&&_currentUser.username)||''; }
function _flDueDate(l){
  var n=(typeof _supplierDays==='function')?_supplierDays(l.supplier):0; if(!n||!l.date)return null;
  var d=new Date(l.date+'T00:00:00'); d.setDate(d.getDate()+n); return _isoLocal(d);
}
function _flLate(l){
  var dd=_flDueDate(l); if(!dd||_flDue(l)<=0.5)return 0;
  return Math.max(0,Math.floor((Date.parse(_isoLocal()+'T00:00:00')-Date.parse(dd+'T00:00:00'))/86400000));
}
function _flDm(d){ return d?String(d).slice(8,10)+'/'+String(d).slice(5,7):''; }
// Litres this load put in the tank. The invoice figure, unless the delivery
// check found it short AND a decision was taken on it (claim or accept) —
// then the tank holds what actually arrived.
function _flStockL(l){
  var v=parseFloat(l&&l.vol)||0, r=l&&l.receipt;
  if(!r||!r.action||typeof _receiptEval!=='function')return v;
  var e=_receiptEval(l); return (e&&e.short&&e.got>0)?e.got:v;
}
function _flDecided(l){ var r=l&&l.receipt; return !!(r&&(r.action==='accept'||(r.claim&&r.claim.status==='settled'))); }
function _flCredit(l){ var c=l&&l.receipt&&l.receipt.claim; return (c&&c.status==='settled')?(+c.credit||0):0; }
function _flReprice(l){
  var sl=_flStockL(l), tc=_flTotal(l);
  l.buy=sl>0?tc/sl:0; l.profit=(+l.revenue||0)-tc;
}

// ── 7. payments ──────────────────────────────────────────────────────────
function payFuelLoad(id){
  var l=_flFind(id); if(!l)return;
  var g=function(k){ var e=document.getElementById('fl_'+k+'_'+id); return e?String(e.value||''):''; };
  var amt=_r2(parseFloat(g('pay'))||0);
  if(!(amt>0)){ showToast('Enter the payment amount'); return; }
  var due=_flDue(l);
  if(amt>due+0.005){ showToast('That is more than the '+fmt(due)+' due — nothing recorded'); return; }
  var date=g('pdate')||_isoLocal(), mode=g('pmode')||'Bank Transfer', ref=_clean(g('pref').trim());
  var pays=_flPaysList(l).map(function(p){ return p.legacy?Object.assign({},p,{id:_newId()}):p; });
  pays.push({id:_newId(),date:date,amount:amt,mode:mode,ref:ref,note:'',by:_flUser(),at:new Date().toISOString()});
  l.payments=pays; _flSave(l);
  if(typeof logActivity==='function')logActivity('pay_load','fuel_load',l.id,
    l.type+' '+(l.inv||'')+' • paid '+fmt(amt)+' ('+mode+(ref?' '+ref:'')+', '+date+') • due now '+fmt(_flDue(l)));
  renderFuelLoads(); showToast('✓ '+fmt(amt)+' recorded'+(_flDue(l)<=0.005?' — fully paid':' — '+fmt(_flDue(l))+' still due'));
}
function reverseFuelPayment(id,payId){
  var l=_flFind(id); if(!l)return;
  if(!_flCan()){ showToast('🔒 Only an owner or manager can reverse a payment'); return; }
  var p=(l.payments||[]).find(function(x){ return String(x.id)===String(payId); }); if(!p||p.legacy)return;
  var why=prompt('Reverse '+fmt(+p.amount||0)+' paid for '+l.type+' '+(l.inv||'')+' on '+p.date+' ('+p.mode+')?\n\nOnly for a payment entered by mistake. Reason:','Entered by mistake');
  if(why===null)return;
  l.payments=l.payments.filter(function(x){ return x!==p; }); _flSave(l);
  if(typeof logActivity==='function')logActivity('reverse_load_pay','fuel_load',l.id,
    l.type+' '+(l.inv||'')+' • reversed '+fmt(+p.amount||0)+' ('+p.mode+', '+p.date+') • '+_clean(String(why)));
  renderFuelLoads(); showToast('↶ Payment reversed');
}
function _flPayHtml(l){
  var pays=_flPaysList(l), paid=_flPaid(l), due=_flDue(l), can=_flCan(), dd=_flDueDate(l), late=_flLate(l);
  var co=_esc(l.supplier||'');
  var dueInfo=(dd&&due>0.5)
    ? (late>0?'<span style="color:var(--red);font-weight:700">OVERDUE '+late+' d</span>':'<span style="color:var(--muted)">due '+_flDm(dd)+'</span>')
    : '';
  var days='<button class="btn btn-g" style="padding:1px 6px;font-size:9px" data-co="'+co+'" onclick="setSupplierDays(this.dataset.co)" title="Credit days for this supplier">⚙ '+((typeof _supplierDays==='function'&&_supplierDays(l.supplier))||'set')+' d</button>';
  var hist=pays.length?'<div style="margin-top:8px;font-family:\'JetBrains Mono\',monospace;font-size:11px">'+pays.map(function(p){
      return '<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;padding:3px 0;border-top:1px solid var(--border)">'+
        '<span style="color:var(--muted)">'+_esc(p.legacy?'—':(p.date||''))+'</span><b style="color:var(--green)">'+fmt(+p.amount||0)+'</b>'+
        '<span>'+_esc(p.mode||'')+'</span><span style="color:var(--muted);flex:1">'+_esc([p.ref,p.note,p.by?'by '+p.by:''].filter(Boolean).join(' · '))+'</span>'+
        (can&&!p.legacy?'<button class="btn btn-g" style="padding:1px 7px;font-size:9px" onclick="reverseFuelPayment('+l.id+','+p.id+')">↶ REVERSE</button>':'')+'</div>';
    }).join('')+'</div>':'';
  var form=due>0.005
    ? '<input type="number" id="fl_pay_'+l.id+'" placeholder="Amount" inputmode="decimal" style="width:120px;padding:4px 8px;font-size:12px;margin-left:auto">'+
      '<select id="fl_pmode_'+l.id+'" style="padding:4px 6px;font-size:11px;background:var(--bg);border:1px solid var(--border);border-radius:4px;color:var(--text)">'+
        ['Bank Transfer','RTGS / NEFT','UPI','Cheque','Cash','Other'].map(function(m){ return '<option>'+m+'</option>'; }).join('')+'</select>'+
      '<input type="date" id="fl_pdate_'+l.id+'" value="'+_isoLocal()+'" style="width:130px;padding:4px 6px;font-size:11px">'+
      '<input type="text" id="fl_pref_'+l.id+'" placeholder="UTR / cheque no." style="width:130px;padding:4px 6px;font-size:11px">'+
      '<button class="btn btn-g" style="padding:4px 12px;font-size:11px" onclick="payFuelLoad('+l.id+')">RECORD PAYMENT</button>'
    : '<span class="badge bg_" style="margin-left:auto">&#10003; FULLY PAID</span>';
  return '<div style="background:var(--s3);padding:10px;border-radius:6px">'+
    '<div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">'+
      '<div style="font-size:11px;color:var(--muted)">Due to supplier:</div>'+
      '<div style="font-family:\'JetBrains Mono\',monospace;font-size:14px;font-weight:700;color:'+(due<=0.005?'var(--green)':'var(--red)')+'">'+fmt(due)+'</div>'+
      '<div style="font-size:11px;color:var(--muted)">Paid: '+fmt(paid)+'</div>'+dueInfo+days+form+
    '</div>'+hist+'</div>';
}

// ── 12. short delivery: claim or accept ──────────────────────────────────
function flShortAction(id,act){
  var l=_flFind(id); if(!l)return;
  if(!_flCan()){ showToast('🔒 Only an owner or manager can do this'); return; }
  var e=_receiptEval(l), r=l.receipt; if(!r)return;
  var shortL=e?Math.abs(e.diff):0, costL=(+l.vol||0)>0?_flTotal(l)/(+l.vol):0;
  if(act==='claim'){
    if(!e||!e.short)return;
    var amt=prompt('Claim '+shortL.toFixed(1)+' L short from '+(l.supplier||'the supplier')+'.\nAmount to claim (₹):',Math.round(shortL*costL));
    if(amt===null)return;
    var ref=prompt('Complaint / claim reference (optional):','');
    r.action='claim';
    r.claim={litres:_r2(shortL),amount:_r2(parseFloat(amt)||0),ref:_clean(String(ref||'')),status:'open',raisedAt:_isoLocal(),by:_flUser()};
  } else if(act==='accept'){
    if(!e||!e.short)return;
    if(r.claim&&r.claim.status==='settled'){ showToast('A credit note is already recorded on this load'); return; }
    var nl=_r2(_flTotal(l)/e.got);
    if(!confirm('Accept the '+shortL.toFixed(1)+' L shortfall?\n\nThe tank will count the '+e.got.toFixed(0)+' L that actually arrived, '+
      'and this load will cost ₹'+nl.toFixed(2)+'/L instead of ₹'+costL.toFixed(2)+'/L.'))return;
    r.action='accept'; r.claim=null;
  } else if(act==='undo'){
    if(r.claim&&r.claim.status==='settled'){ showToast('Undo the credit note first'); return; }
    r.action=null; r.claim=null;
  } else return;
  _flReprice(l); _flSave(l);
  if(typeof logActivity==='function')logActivity('load_short_'+act,'fuel_load',l.id,
    l.type+' '+(l.inv||'')+' • '+shortL.toFixed(1)+' L short • '+(act==='claim'?'claim '+fmt(r.claim.amount)+(r.claim.ref?' ref '+r.claim.ref:''):act==='accept'?'loss accepted':'decision undone'));
  renderFuelLoads();
  showToast(act==='claim'?'📨 Claim recorded — the tank now counts the litres received':act==='accept'?'Loss accepted — cost per litre updated':'Undone');
}
function flCreditNote(id){
  var l=_flFind(id); if(!l)return;
  if(!_flCan()){ showToast('🔒 Only an owner or manager can do this'); return; }
  var c=l.receipt&&l.receipt.claim; if(!c||c.status!=='open')return;
  var amt=prompt('Credit note received from '+(l.supplier||'the supplier')+' — amount (₹):',c.amount);
  if(amt===null)return; amt=_r2(parseFloat(amt)||0);
  if(!(amt>0)){ showToast('Enter the credit amount'); return; }
  if(amt>=_flTotal(l)){ showToast('The credit cannot be more than the bill'); return; }
  var ref=prompt('Credit note number (optional):','');
  c.status='settled'; c.credit=amt; c.creditDate=_isoLocal(); c.creditRef=_clean(String(ref||'')); c.creditBy=_flUser();
  l.totalCost=_r2(_flTotal(l)-amt); _flReprice(l);
  var over=_r2(_flPaid(l)-l.totalCost);
  _flSave(l);
  if(typeof logActivity==='function')logActivity('load_credit_note','fuel_load',l.id,
    l.type+' '+(l.inv||'')+' • credit note '+fmt(amt)+(c.creditRef?' '+c.creditRef:'')+' • load cost now '+fmt(l.totalCost));
  renderFuelLoads();
  showToast('✓ Credit '+fmt(amt)+' taken off the load'+(over>0.5?' — paid '+fmt(over)+' more than the bill now; it should come off the next one':''));
}
function flUndoCredit(id){
  var l=_flFind(id); if(!l)return;
  if(typeof _isOwner!=='undefined'&&!_isOwner){ showToast('🔒 Owner access only'); return; }
  var c=l.receipt&&l.receipt.claim; if(!c||c.status!=='settled')return;
  if(!confirm('Undo the '+fmt(+c.credit||0)+' credit note? The load goes back to its full bill.'))return;
  l.totalCost=_r2(_flTotal(l)+(+c.credit||0));
  c.status='open'; delete c.credit; delete c.creditDate; delete c.creditRef; delete c.creditBy;
  _flReprice(l); _flSave(l);
  if(typeof logActivity==='function')logActivity('load_credit_undo','fuel_load',l.id,l.type+' '+(l.inv||'')+' • credit note undone');
  renderFuelLoads(); showToast('Credit note undone');
}
function _flShortHtml(l){
  var e=(typeof _receiptEval==='function')?_receiptEval(l):null; if(!e||!e.short)return '';
  var r=l.receipt||{}, c=r.claim, can=_flCan(), shortL=Math.abs(e.diff);
  var costL=(+l.vol||0)>0?(_flTotal(l)+_flCredit(l))/(+l.vol):0;
  var b=function(txt,fn,cls){ return can?'<button class="btn '+(cls||'btn-g')+'" style="padding:3px 10px;font-size:10px" onclick="'+fn+'">'+txt+'</button>':''; };
  var body, col='var(--red)';
  if(!r.action){
    body='<b>⚠ '+shortL.toFixed(1)+' L short</b> (≈ '+fmt(shortL*costL)+' at this load’s cost). The tank still counts the invoice litres until you decide:'+
      '<div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:6px">'+b('📨 RAISE CLAIM','flShortAction('+l.id+',\'claim\')')+b('ACCEPT LOSS','flShortAction('+l.id+',\'accept\')')+'</div>';
  } else if(r.action==='claim'&&c&&c.status==='open'){
    col='var(--diesel)';
    body='<b>📨 Claim open</b> since '+_flDm(c.raisedAt)+' — '+(+c.litres||0).toFixed(1)+' L · '+fmt(+c.amount||0)+(c.ref?' · ref '+_esc(c.ref):'')+
      '. The tank counts the '+e.got.toFixed(0)+' L received.'+
      '<div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:6px">'+b('✓ CREDIT NOTE RECEIVED','flCreditNote('+l.id+')')+b('DROP CLAIM → ACCEPT LOSS','flShortAction('+l.id+',\'accept\')')+b('UNDO','flShortAction('+l.id+',\'undo\')')+'</div>';
  } else if(r.action==='claim'&&c&&c.status==='settled'){
    col='var(--green)';
    body='<b>✓ Credit note '+fmt(+c.credit||0)+'</b> received '+_flDm(c.creditDate)+(c.creditRef?' ('+_esc(c.creditRef)+')':'')+
      ' — taken off this load’s cost. The tank counts the '+e.got.toFixed(0)+' L received.'+
      (typeof _isOwner==='undefined'||_isOwner?'<div style="margin-top:6px">'+b('UNDO CREDIT NOTE','flUndoCredit('+l.id+')')+'</div>':'');
  } else {
    col='var(--muted)';
    body='<b>Loss accepted</b> — the tank counts the '+e.got.toFixed(0)+' L received; this load costs '+fmt(_flTotal(l)/e.got)+'/L.'+
      '<div style="margin-top:6px">'+b('UNDO','flShortAction('+l.id+',\'undo\')')+'</div>';
  }
  return '<div style="margin-top:8px;padding:10px;border-radius:6px;border:1px solid '+col+';font-family:\'JetBrains Mono\',monospace;font-size:11px;line-height:1.6">'+body+'</div>';
}

// ── 10. actual margin per load ───────────────────────────────────────────
function _flWindow(l){
  var t=l.type, today=_isoLocal();
  var next=fuelLoads.filter(function(x){ return x.type===t&&x.date&&x.date>l.date; })
    .sort(function(a,b){ return String(a.date).localeCompare(String(b.date)); })[0]||null;
  var end=today;
  if(next){ var d=new Date(next.date+'T00:00:00'); d.setDate(d.getDate()-1); end=_isoLocal(d); }
  if(end<l.date)end=l.date;
  var L=0,V=0,n=0;
  records.forEach(function(r){
    if(r.date<l.date||r.date>end)return;
    var T=t==='MSD'?r.msdT:r.hsdT, v=t==='MSD'?r.msdV:r.hsdV, tl=(t==='MSD'?r.testMSDL:r.testHSDL)||0;
    if(!((T||0)>0))return; var rate=(v||0)/T; L+=T-tl; V+=(v||0)-rate*tl; n++;
  });
  var sl=_flStockL(l), tc=_flTotal(l), costL=sl>0?tc/sl:0, avg=L>0?V/L:null;
  var mL=(avg!=null&&costL>0)?avg-costL:null;
  return {from:l.date,to:end,next:next,shifts:n,soldL:L,avg:avg,costL:costL,mL:mL,est:mL!=null?mL*sl:null,
          exp:+l.profit||0, expL:(+l.sell||0)>0&&(+l.vol||0)>0?(+l.sell)-tc/(+l.vol):null};
}
function _flRealHtml(l){
  var w=_flWindow(l);
  if(!w.shifts)return '<div style="margin-top:8px;font-family:\'JetBrains Mono\',monospace;font-size:10px;color:var(--muted)">📈 Actual margin: no shifts saved since this load yet.</div>';
  var d=w.est!=null?w.est-w.exp:null;
  return '<div style="margin-top:8px;background:var(--s3);padding:8px 10px;border-radius:6px;font-family:\'JetBrains Mono\',monospace;font-size:11px;line-height:1.6">'+
    '<b style="font-family:\'Syne\',sans-serif;font-size:10px;letter-spacing:1px;color:var(--muted)">📈 ACTUAL MARGIN</b> '+
    'sold '+Math.round(w.soldL).toLocaleString('en-IN')+' L at avg '+fmt(w.avg)+'/L ('+_flDm(w.from)+' → '+(w.next?_flDm(w.to):'today')+') · cost '+fmt(w.costL)+'/L · '+
    (w.mL!=null?'<b style="color:'+(w.mL>=0?'var(--green)':'var(--red)')+'">'+fmt(w.mL)+'/L ≈ '+fmt(w.est)+'</b> on this load':'cost unknown')+
    ' · expected '+fmt(w.exp)+(d!=null?' <span style="color:'+(d>=0?'var(--green)':'var(--red)')+'">('+(d>=0?'+':'−')+fmt(Math.abs(d))+')</span>':'')+
    (w.next?'':' <span style="color:var(--muted)">· still selling</span>')+'</div>';
}
function _flRenderMargins(){
  var box=document.getElementById('fl_margin_box'); if(!box)return;
  var list=fuelLoads.slice().sort(function(a,b){ return String(b.date).localeCompare(String(a.date))||(b.id-a.id); }).slice(0,15);
  if(!list.length){ box.innerHTML='<div style="color:var(--muted);font-size:11px">No loads yet.</div>'; return; }
  var tE=0,tA=0,known=0;
  var rows=list.map(function(l){
    var w=_flWindow(l); if(w.est!=null&&w.shifts){ tE+=w.exp; tA+=w.est; known++; }
    var d=(w.est!=null&&w.shifts)?w.est-w.exp:null;
    var td=function(v,c){ return '<td style="text-align:right;white-space:nowrap'+(c?';color:'+c:'')+'">'+v+'</td>'; };
    return '<tr><td style="white-space:nowrap">'+_flDm(l.date)+' <span style="color:'+(l.type==='MSD'?'var(--petrol)':'var(--diesel)')+'">'+l.type+'</span></td>'+
      '<td>'+_esc(l.inv||'—')+'</td>'+td(fmt(w.costL))+td(l.sell?fmt(+l.sell):'—')+td(w.avg!=null?fmt(w.avg):'—')+
      td(w.mL!=null?fmt(w.mL):'—',w.mL!=null?(w.mL>=0?'var(--green)':'var(--red)'):null)+
      td(w.est!=null&&w.shifts?fmt(w.est):'—')+td(fmt(w.exp))+
      td(d!=null?(d>=0?'+':'−')+fmt(Math.abs(d)):'—',d!=null?(d>=0?'var(--green)':'var(--red)'):null)+
      '<td style="color:var(--muted);white-space:nowrap">'+(w.next?'until '+_flDm(w.next.date):'still selling')+'</td></tr>';
  }).join('');
  box.innerHTML='<div style="overflow-x:auto"><table class="data-tbl" style="font-size:11px"><thead><tr><th>Load</th><th>Invoice</th>'+
    '<th style="text-align:right">Cost / L</th><th style="text-align:right">Sell at entry</th><th style="text-align:right">Avg sold</th>'+
    '<th style="text-align:right">Margin / L</th><th style="text-align:right">≈ On load</th><th style="text-align:right">Expected</th>'+
    '<th style="text-align:right">Difference</th><th>Window</th></tr></thead><tbody>'+rows+
    (known?'<tr><td colspan="6" style="font-weight:800">Total ('+known+' load'+(known!==1?'s':'')+' with sales)</td><td style="text-align:right;font-weight:800">'+fmt(tA)+'</td>'+
      '<td style="text-align:right;font-weight:800">'+fmt(tE)+'</td><td style="text-align:right;font-weight:800;color:'+(tA-tE>=0?'var(--green)':'var(--red)')+'">'+(tA-tE>=0?'+':'−')+fmt(Math.abs(tA-tE))+'</td><td></td></tr>':'')+
    '</tbody></table></div>'+
    '<div style="font-size:10px;color:var(--muted);margin-top:8px;font-family:\'JetBrains Mono\',monospace;line-height:1.6">Actual = the average pump rate from the day the load came until the next load of that fuel, less this load’s cost per litre (after any credit note, and on the litres received if a shortfall was claimed or accepted). Tankers mix in the tank, so this is an estimate per load; Reports → P&L is the exact figure for any period. Expected = the selling rate typed on the bill at the time.</div>';
}

// ── 11. history filters and month totals ─────────────────────────────────
function _flF(){ try{ return JSON.parse(localStorage.getItem('mf_fl_filter')||'{}')||{}; }catch(e){ return {}; } }
function flSetFilter(k,v){ var f=_flF(); if(v)f[k]=v; else delete f[k]; try{ localStorage.setItem('mf_fl_filter',JSON.stringify(f)); }catch(e){} renderFuelLoads(); }
function flClearFilter(){ try{ localStorage.removeItem('mf_fl_filter'); }catch(e){} renderFuelLoads(); }
function _flKey(s){ return String(s||'').trim().toLowerCase().replace(/\s+/g,' '); }
function _flFiltered(){
  var f=_flF();
  return fuelLoads.filter(function(l){
    if(f.type&&l.type!==f.type)return false;
    if(f.month&&String(l.date||'').slice(0,7)!==f.month)return false;
    if(f.sup&&_flKey(l.supplier)!==f.sup)return false;
    if(f.st){
      var e=(typeof _receiptEval==='function')?_receiptEval(l):null, c=l.receipt&&l.receipt.claim;
      if(f.st==='unpaid'&&!(_flDue(l)>0.5))return false;
      if(f.st==='overdue'&&!(_flLate(l)>0))return false;
      if(f.st==='short'&&!(e&&e.short))return false;
      if(f.st==='claim'&&!(c&&c.status==='open'))return false;
      if(f.st==='unchecked'&&e)return false;
    }
    return true;
  }).sort(function(a,b){ return String(b.date).localeCompare(String(a.date))||(b.id-a.id); });
}
function _flRenderTools(){
  var box=document.getElementById('fl_tools'); if(!box)return;
  var f=_flF(), sel='padding:5px 8px;background:var(--bg);border:1px solid var(--border);border-radius:4px;color:var(--text);font-family:\'JetBrains Mono\',monospace;font-size:11px';
  var months=[...new Set(fuelLoads.map(function(l){ return String(l.date||'').slice(0,7); }).filter(Boolean))].sort().reverse();
  var sups={}; fuelLoads.forEach(function(l){ var k=_flKey(l.supplier); if(k&&!sups[k])sups[k]=String(l.supplier).trim(); });
  var opt=function(v,t,cur){ return '<option value="'+_esc(v)+'"'+(String(cur||'')===String(v)?' selected':'')+'>'+_esc(t)+'</option>'; };
  var mn=function(ym){ var p=ym.split('-'); return new Date(+p[0],+p[1]-1,1).toLocaleDateString('en-IN',{month:'short',year:'numeric'}); };
  var shown=_flFiltered().length;
  var tools='<div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:10px">'+
    '<select style="'+sel+'" onchange="flSetFilter(\'type\',this.value)">'+opt('','All fuel',f.type)+opt('MSD','Petrol (MSD)',f.type)+opt('HSD','Diesel (HSD)',f.type)+'</select>'+
    '<select style="'+sel+'" onchange="flSetFilter(\'month\',this.value)">'+opt('','All months',f.month)+months.map(function(m){ return opt(m,mn(m),f.month); }).join('')+'</select>'+
    '<select style="'+sel+'" onchange="flSetFilter(\'sup\',this.value)">'+opt('','All suppliers',f.sup)+Object.keys(sups).sort().map(function(k){ return opt(k,sups[k],f.sup); }).join('')+'</select>'+
    '<select style="'+sel+'" onchange="flSetFilter(\'st\',this.value)">'+opt('','Any status',f.st)+opt('unpaid','Unpaid',f.st)+opt('overdue','Overdue',f.st)+
      opt('short','Short delivery',f.st)+opt('claim','Claim open',f.st)+opt('unchecked','Delivery not checked',f.st)+'</select>'+
    '<span style="font-family:\'JetBrains Mono\',monospace;font-size:11px;color:var(--muted)">showing '+shown+' of '+fuelLoads.length+'</span>'+
    (Object.keys(f).length?'<button class="btn btn-g" style="padding:4px 10px;font-size:10px" onclick="flClearFilter()">CLEAR</button>':'')+'</div>';
  // Month totals — fuel and supplier filters apply, month and status do not.
  var M={};
  fuelLoads.forEach(function(l){
    if(f.type&&l.type!==f.type)return; if(f.sup&&_flKey(l.supplier)!==f.sup)return;
    var k=String(l.date||'').slice(0,7); if(!k)return;
    var m=M[k]||(M[k]={n:0,mL:0,hL:0,mC:0,hC:0,c:0,p:0,d:0});
    var v=+l.vol||0, tc=_flTotal(l), sl=_flStockL(l);
    m.n++; m.c+=tc; m.p+=_flPaid(l); m.d+=_flDue(l);
    if(l.type==='MSD'){ m.mL+=v; if(tc>0){ m.mC+=tc; m.mS=(m.mS||0)+sl; } } else { m.hL+=v; if(tc>0){ m.hC+=tc; m.hS=(m.hS||0)+sl; } }
  });
  var ks=Object.keys(M).sort().reverse().slice(0,12);
  var td=function(v){ return '<td style="text-align:right;white-space:nowrap">'+v+'</td>'; };
  var kl=function(x){ return x>0?(x/1000).toLocaleString('en-IN',{minimumFractionDigits:3,maximumFractionDigits:3}):'—'; };
  var months_html=ks.length?'<details style="margin-bottom:12px"'+(_flF().month?'':' open')+'><summary style="cursor:pointer;font-family:\'Syne\',sans-serif;font-weight:800;font-size:10px;letter-spacing:1.5px;color:var(--muted);margin-bottom:6px">MONTH TOTALS</summary>'+
    '<div style="overflow-x:auto"><table class="data-tbl" style="font-size:11px"><thead><tr><th>Month</th><th style="text-align:right">Loads</th><th style="text-align:right">Petrol KL</th><th style="text-align:right">Diesel KL</th>'+
    '<th style="text-align:right">Cost</th><th style="text-align:right">Petrol ₹/L</th><th style="text-align:right">Diesel ₹/L</th><th style="text-align:right">Paid</th><th style="text-align:right">Due</th></tr></thead><tbody>'+
    ks.map(function(k){ var m=M[k];
      return '<tr><td style="white-space:nowrap">'+mn(k)+'</td>'+td(m.n)+td(kl(m.mL))+td(kl(m.hL))+td(fmt(m.c))+
        td(m.mS?fmt(m.mC/m.mS):'—')+td(m.hS?fmt(m.hC/m.hS):'—')+td(fmt(m.p))+
        '<td style="text-align:right;white-space:nowrap;color:'+(m.d>0.5?'var(--red)':'var(--muted)')+'">'+fmt(m.d)+'</td></tr>'; }).join('')+
    '</tbody></table></div><div style="font-size:10px;color:var(--muted);font-family:\'JetBrains Mono\',monospace;margin-top:4px">₹/L = landed cost (bill + lorry, less credit notes) ÷ litres into the tank.</div></details>':'';
  box.innerHTML=tools+months_html;
}

// ── 3/4/9. helpers used by the form ──────────────────────────────────────
function _flDup(inv,supplier,exceptId){
  var a=_flKey(inv), b=_flKey(supplier); if(!a)return null;
  return fuelLoads.find(function(l){ return String(l.id)!==String(exceptId)&&_flKey(l.inv)===a&&_flKey(l.supplier)===b; })||null;
}
function _flRateOk(date,type,sell){
  var y=new Date(); y.setDate(y.getDate()-1);
  if(date>=_isoLocal(y))return true;
  return confirm('This load is dated '+date+'.\n\nChange TODAY’s '+type+' pump rate to ₹'+sell+'?\n\nOK = change it · Cancel = keep today’s rate');
}"""

HUNKS = [
# ── form ────────────────────────────────────────────────────────────────
("F1 fuel type sets the density hint",
r"""          <select id="fl_type" style="width:100%;""",
r"""          <select id="fl_type" onchange="fl_updateType()" style="width:100%;"""),

("F2 challan density field",
r"""        <div><div class="flabel" style="margin-bottom:4px">TRANSPORT COMPANY</div>
          <input type="text" id="fl_transport" placeholder="Company name"></div>
      </div>""",
r"""        <div><div class="flabel" style="margin-bottom:4px">TRANSPORT COMPANY</div>
          <input type="text" id="fl_transport" placeholder="Company name"></div>
        <div><div class="flabel" style="margin-bottom:4px" title="Density printed on the challan / invoice — used by the delivery check">DENSITY (CHALLAN)</div>
          <input type="number" id="fl_density" step="0.0001" inputmode="decimal" placeholder="e.g. 0.745"></div><!-- MF_FUELLOAD_V1 -->
      </div>"""),

("F3 density hint, not a guessed value",
r"""  const den=document.getElementById('fl_density');
  if(den)den.value=t==='MSD'?'0.720':'0.820';""",
r"""  const den=document.getElementById('fl_density');
  if(den)den.placeholder=t==='MSD'?'e.g. 0.745':'e.g. 0.830';   // MF_FUELLOAD_V1: the challan's figure, typed — not a guess"""),

("F4 toggle form: no guessed density",
r"""    document.getElementById('fl_density').value='0.820';""",
r"""    document.getElementById('fl_density').value='';"""),

("F5 reset clears density",
r"""   'fl_vol_kl','fl_basic_price','fl_tn_vat','fl_lorry_rent','fl_sell'
  ].forEach(function(id){var e=document.getElementById(id);if(e)e.value='';});""",
r"""   'fl_vol_kl','fl_basic_price','fl_tn_vat','fl_lorry_rent','fl_sell','fl_density'
  ].forEach(function(id){var e=document.getElementById(id);if(e)e.value='';});"""),

("F6 edit loads the density back",
r"""  set('fl_sell', l.sell);
  set('fl_update_rate','no');""",
r"""  set('fl_sell', l.sell);
  set('fl_density', (l.density!=null&&Math.abs((+l.density||0)-0.82)>1e-9)?l.density:'');   // MF_FUELLOAD_V1
  set('fl_update_rate','no');"""),

("F7 duplicate check before saving",
r"""  var load={
    id:_newId(), date:date, inv:inv, supplier:supplier,""",
r"""  // MF_FUELLOAD_V1: the same bill twice puts its litres in the tank twice.
  var _dupL=(typeof _flDup==='function')?_flDup(inv,supplier,_flEditingId):null;
  if(_dupL&&!confirm('Invoice '+inv+' from '+supplier+' is already entered ('+_dupL.date+', '+_dupL.type+' '+Math.round(+_dupL.vol||0)+' L).\n\n'+
    'Save it again anyway? That adds '+Math.round(volL)+' L to the tank a second time.'))return;
  var _dIn=document.getElementById('fl_density');
  var load={
    id:_newId(), date:date, inv:inv, supplier:supplier,"""),

("F8 density from the challan",
r"""    density:0.820, buy:volL>0?totalCost/volL:0,""",
r"""    density:(typeof _normDensity==='function'&&_dIn)?_normDensity(_dIn.value):null, buy:volL>0?totalCost/volL:0,"""),

("F9 edit keeps the check, claim and payments",
r"""      var prev=fuelLoads[oldIdx];
      load.id        = prev.id;                 // keep the row, do not orphan it
      load.amountPaid= prev.amountPaid||0;      // payments already made stand
      load.amountDue = Math.max(0, load.totalCost - load.amountPaid);
      load.locked    = prev.locked||false;
      fuelLoads[oldIdx]=load;""",
r"""      var prev=fuelLoads[oldIdx];
      load.id        = prev.id;                 // keep the row, do not orphan it
      // MF_FUELLOAD_V1: what was recorded ON the load stays with it. The old
      // edit rebuilt the row from the form and the delivery check was lost.
      ['receipt','payments','createdAt'].forEach(function(k){ if(prev[k]!=null)load[k]=prev[k]; });
      if(load.density==null&&prev.density!=null&&Math.abs((+prev.density||0)-0.82)>1e-9)load.density=prev.density;
      var _crN=(typeof _flCredit==='function')?_flCredit(prev):0;
      if(_crN>0){ load.totalCost=_r2(load.totalCost-_crN); load.profit=load.revenue-load.totalCost; }
      if(typeof _flStockL==='function'){ var _sl=_flStockL(load); load.buy=_sl>0?load.totalCost/_sl:0; }
      load.amountPaid= (typeof _flPaid==='function')?_flPaid(prev):(prev.amountPaid||0);   // payments already made stand
      if(load.amountPaid>load.totalCost+0.5){
        showToast(fmt(load.amountPaid)+' is already paid — more than the corrected bill of '+fmt(load.totalCost)+'. Reverse a payment first.');
        return;
      }
      load.amountDue = Math.max(0, load.totalCost - load.amountPaid);
      load.locked    = prev.locked||false;
      fuelLoads[oldIdx]=load;"""),

("F10 back-dated load asks before moving today's pump rate",
r"""  if(updateRate&&sell>0){
    if(type==='MSD'){document.getElementById('msd_rate').value=sell;saveRates();}""",
r"""  if(updateRate&&sell>0&&(typeof _flRateOk!=='function'||_flRateOk(date,type,sell))){   // MF_FUELLOAD_V1
    if(type==='MSD'){document.getElementById('msd_rate').value=sell;saveRates();}"""),

# ── payment, delete ─────────────────────────────────────────────────────
("P1 old payment routine retired",
r"""function payFuelLoad(id){
  const load=fuelLoads.find(x=>x.id===id);if(!load)return;
  const inp=document.getElementById('fl_pay_'+id);
  const amt=parseFloat(inp?.value)||0;
  if(!amt){showToast('Enter payment amount');return;}
  load.amountPaid=Math.min(load.totalCost,load.amountPaid+amt);
  load.amountDue=load.totalCost-load.amountPaid;
  localStorage.setItem('fuelLoads',JSON.stringify(fuelLoads));
  if(_currentUser)sbSaveFuelLoad(load).catch(console.error);
  renderFuelLoads();showToast('Payment recorded!');
}""",
r"""// MF_FUELLOAD_V1: payFuelLoad() is in the FUEL LOADS block — it refused
// nothing, cut an overpayment silently and kept no date."""),

("P2 delete: owner/manager, not while paid, with a reason",
r"""function delFuelLoad(id){
  const l=fuelLoads.find(x=>x.id===id);
  if(l&&!confirm('Delete this '+(l.type||'')+' load of '+(l.vol||0)+' L?\n\n'+
    'Weighted-average cost per litre is calculated from loads, so removing this '+
    'changes COGS and every profit figure for the period.'))return;
  fuelLoads=fuelLoads.filter(x=>x.id!==id);
  localStorage.setItem('fuelLoads',JSON.stringify(fuelLoads));
  if(_currentUser)_sbRemove('fuel_loads', id, 'id');
  if(typeof logActivity==='function')logActivity('del_load','fuel_load',id,'Deleted load');
  renderFuelLoads();showToast('Load record deleted.');
}""",
r"""function delFuelLoad(id){
  const l=fuelLoads.find(x=>String(x.id)===String(id)); if(!l)return;
  // MF_FUELLOAD_V1
  if(typeof _flCan==='function'&&!_flCan()){showToast('🔒 Only an owner or manager can delete a load');return;}
  if(l.locked){showToast('Unlock this load first');return;}
  const dated=(l.payments||[]).filter(p=>!p.legacy&&(+p.amount||0)>0);
  if(dated.length){showToast('Payments of '+fmt(dated.reduce((s,p)=>s+(+p.amount||0),0))+' are recorded on this load — reverse them first');return;}
  if((+l.amountPaid||0)>0.005&&typeof _isOwner!=='undefined'&&!_isOwner){showToast('🔒 '+fmt(+l.amountPaid)+' is paid on this load — only an owner can delete it');return;}
  const why=prompt('Delete '+(l.type||'')+' '+(l.inv||'')+' — '+Math.round(+l.vol||0)+' L, '+fmt(+l.totalCost||0)+
    ((+l.amountPaid||0)>0.005?', '+fmt(+l.amountPaid)+' PAID':'')+'?\n\n'+
    'The cost per litre of every sale after it changes, and so does every profit figure.\nReason:','Entered by mistake');
  if(why===null)return;
  fuelLoads=fuelLoads.filter(x=>String(x.id)!==String(id));
  localStorage.setItem('fuelLoads',JSON.stringify(fuelLoads));
  if(_currentUser)_sbRemove('fuel_loads', l.id, 'id');
  if(typeof logActivity==='function')logActivity('del_load','fuel_load',l.id,
    'Deleted '+(l.type||'')+' '+(l.inv||'')+' '+(l.date||'')+' • '+Math.round(+l.vol||0)+' L • '+fmt(+l.totalCost||0)+' • '+_clean(String(why)));
  renderFuelLoads();showToast('Load record deleted.');
}"""),

# ── delivery check ──────────────────────────────────────────────────────
("D1 density check uses the challan figure",
r"""  var dc=_normDensity(l.density), dobs=_normDensity(r.density);""",
r"""  // MF_FUELLOAD_V1: 0.820 was written on every load by default, petrol too —
  // it is not a challan figure, so it is not compared against.
  var _ch=r.challan!=null?r.challan:((l.density!=null&&Math.abs((+l.density||0)-0.82)>1e-9)?l.density:null);
  var dc=_normDensity(_ch), dobs=_normDensity(r.density);"""),

("D2 challan density on the check form",
r"""      '<div><div class="flabel" style="margin-bottom:3px">DENSITY MEASURED</div>""",
r"""      '<div><div class="flabel" style="margin-bottom:3px">DENSITY (CHALLAN)</div><input type="number" step="0.0001" id="fl_rc_c_'+l.id+'" value="'+v(r.challan!=null?r.challan:((l.density!=null&&Math.abs((+l.density||0)-0.82)>1e-9)?l.density:''))+'" placeholder="'+(l.type==='MSD'?'0.745':'0.830')+'" style="width:110px"></div>'+
      '<div><div class="flabel" style="margin-bottom:3px">DENSITY MEASURED</div>"""),

("D3 re-checking keeps the claim",
r"""  l.receipt={before:b,after:a,soldDuring:g('s')||0,density:g('d'),
             by:(_currentUser&&_currentUser.username)||'',at:new Date().toISOString()};""",
r"""  // MF_FUELLOAD_V1: a re-check keeps any claim / decision already on it.
  l.receipt=Object.assign({},l.receipt||{},{before:b,after:a,soldDuring:g('s')||0,density:g('d'),challan:g('c'),
             by:(_currentUser&&_currentUser.username)||'',at:new Date().toISOString()});
  if(typeof _flReprice==='function')_flReprice(l);"""),

# ── card ────────────────────────────────────────────────────────────────
("C1 filtered, newest first",
r"""  const fmt=n=>'₹'+n.toLocaleString('en-IN',{minimumFractionDigits:2});

  fuelLoads.forEach(l=>{
    const typeCls=l.type==='MSD'?'var(--petrol)':'var(--diesel)';""",
r"""  const fmt=n=>'₹'+n.toLocaleString('en-IN',{minimumFractionDigits:2});

  // MF_FUELLOAD_V1: filters, newest first
  const _shown=(typeof _flFiltered==='function')?_flFiltered():fuelLoads;
  if(!_shown.length)list.innerHTML='<div style="text-align:center;padding:24px;color:var(--muted);font-family:\'JetBrains Mono\',monospace">No loads match these filters.</div>';
  _shown.forEach(l=>{
    const typeCls=l.type==='MSD'?'var(--petrol)':'var(--diesel)';"""),

("C2 tools and actual-margin table",
r"""  if(!fuelLoads.length){noEl.style.display='block';return;}
  noEl.style.display='none';""",
r"""  try{ if(typeof _flRenderTools==='function')_flRenderTools(); if(typeof _flRenderMargins==='function')_flRenderMargins(); }catch(e){ console.error('fuel load tools:',e); }   // MF_FUELLOAD_V1
  if(!fuelLoads.length){noEl.style.display='block';return;}
  noEl.style.display='none';"""),

("C3 payment block, short delivery, actual margin",
r"""      <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;background:var(--s3);padding:10px;border-radius:6px">
        <div style="font-size:11px;color:var(--muted)">Amount Due to Supplier:</div>
        <div style="font-family:'JetBrains Mono',monospace;font-size:14px;font-weight:700;color:${dueCls}">${fmt(due)}</div>
        <div style="font-size:11px;color:var(--muted);margin-left:4px">Paid: ${fmt(l.amountPaid||0)}</div>
        ${(Math.round(due*100)/100)>0&&!l.locked?`<input type="number" id="fl_pay_${l.id}" placeholder="Payment amount" style="width:150px;padding:5px 8px;font-size:12px;margin-left:auto">
          <button class="btn btn-g" style="padding:5px 14px;font-size:11px" onclick="payFuelLoad(${l.id})">RECORD PAYMENT</button>`
          :'<span class="badge bg_" style="margin-left:auto">&#10003; FULLY PAID</span>'}
      </div>
      ${typeof _flReceiptHtml==='function'?_flReceiptHtml(l):''}`;""",
r"""      ${_flPayHtml(l)}
      ${typeof _flReceiptHtml==='function'?_flReceiptHtml(l):''}${_flShortHtml(l)}${_flRealHtml(l)}`;"""),

("C4 containers: tools; margin table replaces the comparison",
r"""    <!-- Load records list -->
  <div id="fl_records_list"></div>""",
r"""    <!-- Load records list -->
  <div id="fl_tools"></div><!-- MF_FUELLOAD_V1 -->
  <div id="fl_records_list"></div>"""),

("C5 comparison card → actual margin per load",
r"""    <div class="card-head">PROFIT COMPARISON — LOADS vs SHIFT BALANCE</div>
    <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;text-align:center">
      <div style="background:var(--s3);border-radius:6px;padding:12px">
        <div style="font-size:9px;letter-spacing:2px;color:var(--muted);font-family:'Syne',sans-serif;font-weight:700;margin-bottom:6px">EXPECTED PROFIT (FROM LOADS)</div>
        <div style="font-family:'JetBrains Mono',monospace;font-size:20px;font-weight:700;color:var(--green)" id="fl_cmp_expected">&#8377;0</div></div>
      <div style="background:var(--s3);border-radius:6px;padding:12px">
        <div style="font-size:9px;letter-spacing:2px;color:var(--muted);font-family:'Syne',sans-serif;font-weight:700;margin-bottom:6px">ACTUAL BALANCE (FROM SHIFTS)</div>
        <div style="font-family:'JetBrains Mono',monospace;font-size:20px;font-weight:700" id="fl_cmp_actual" style="color:var(--text)">&#8377;0</div></div>
      <div style="background:var(--s3);border-radius:6px;padding:12px">
        <div style="font-size:9px;letter-spacing:2px;color:var(--muted);font-family:'Syne',sans-serif;font-weight:700;margin-bottom:6px">DIFFERENCE</div>
        <div style="font-family:'JetBrains Mono',monospace;font-size:20px;font-weight:700" id="fl_cmp_diff">&#8377;0</div></div>
    </div>
    <div style="font-size:10px;color:var(--muted);margin-top:8px;font-family:'JetBrains Mono',monospace" id="fl_cmp_note">—</div>""",
r"""    <div class="card-head">ACTUAL MARGIN PER LOAD — WHAT EACH TANKER EARNED VS WHAT WAS EXPECTED</div>
    <div id="fl_margin_box"></div><!-- MF_FUELLOAD_V1: replaces "loads vs shift balance" (cash short/excess is not profit) -->"""),

("C6 summary label",
r"""<div class="sb-t">Expected Profit (Loads)</div>""",
r"""<div class="sb-t">Expected Profit (at entry)</div>"""),

# ── stock litres (12) ───────────────────────────────────────────────────
("L1 WAC on litres into the tank",
r"""    const v=parseFloat(l.vol)||0;
    let c=parseFloat(l.totalCost!=null?l.totalCost:l.total_cost)||0;""",
r"""    const v=(typeof _flStockL==='function')?_flStockL(l):(parseFloat(l.vol)||0);   // MF_FUELLOAD_V1
    let c=parseFloat(l.totalCost!=null?l.totalCost:l.total_cost)||0;"""),

("L2 workings WAC table",
r"""      var v=parseFloat(l.vol)||0, c=parseFloat(l.totalCost!=null?l.totalCost:l.total_cost)||0;""",
r"""      var v=(typeof _flStockL==='function')?_flStockL(l):(parseFloat(l.vol)||0), c=parseFloat(l.totalCost!=null?l.totalCost:l.total_cost)||0;"""),

("L3 workings quantity note",
r""".reduce(function(s,l){return s+(parseFloat(l.vol)||0);},0);""",
r""".reduce(function(s,l){return s+((typeof _flStockL==='function')?_flStockL(l):(parseFloat(l.vol)||0));},0);"""),

("L4 statement stock register",
r""".reduce(function(s,l){return s+(+l.vol||0);},0);""",
r""".reduce(function(s,l){return s+((typeof _flStockL==='function')?_flStockL(l):(+l.vol||0));},0);"""),

("L5 tank book stock",
r"""    loaded+=(parseFloat(l.vol)||0);""",
r"""    loaded+=(typeof _flStockL==='function')?_flStockL(l):(parseFloat(l.vol)||0);   // MF_FUELLOAD_V1: litres received when a shortfall is settled"""),

("L6 order advisor cost",
r"""  var perL=(parseFloat(l.totalCost)||0)/(parseFloat(l.vol)||1);""",
r"""  var perL=(parseFloat(l.totalCost)||0)/(((typeof _flStockL==='function')?_flStockL(l):parseFloat(l.vol))||1);"""),

# ── statement, dues, alerts (7, 8) ──────────────────────────────────────
("S1 statement: fuel payments on their dates",
r"""  (typeof fuelLoads!=='undefined'?fuelLoads:[]).filter(function(l){return inR(l.date);}).forEach(function(l){
    var tc=+(l.totalCost!=null?l.totalCost:l.total_cost)||0, paid=Math.min(tc,+l.amountPaid||0), due=Math.max(0,tc-paid);
    rows.push({date:l.date,ord:0,ref:l.inv||'LOAD',memo:true,desc:'Fuel bill — '+(l.type||'')+' '+_sL(l.vol,0)+' L'+(l.supplier?' · '+l.supplier:'')+' · ₹'+_sN(tc),
      sub:'landed ₹'+_sN((+l.vol||0)>0?tc/l.vol:0)+'/L'+(l.billTotal?' · bill ₹'+_sN(l.billTotal):'')+(l.lorryRent?' + lorry ₹'+_sN(l.lorryRent):'')+
          (l.lorry?' · '+l.lorry:'')+' · paid ₹'+_sN(paid)+(due>0.5?' · DUE ₹'+_sN(due):'')+' · bill shown for information',warn:due>0.5});
    if(paid>0.005)rows.push({date:l.date,ord:0,ref:l.inv||'LOAD',dr:paid,desc:'Paid for fuel — '+(l.type||'')+(l.supplier?' · '+l.supplier:''),
      sub:'payment date not recorded — shown on the bill date'});
  });""",
r"""  // MF_FUELLOAD_V1: fuel payments carry dates now; older paid totals still
  // show on the bill date and say so.
  (typeof fuelLoads!=='undefined'?fuelLoads:[]).forEach(function(l){
    var tc=+(l.totalCost!=null?l.totalCost:l.total_cost)||0;
    var pays=(typeof _flPaysList==='function')?_flPaysList(l):((+l.amountPaid||0)>0?[{date:l.date,amount:+l.amountPaid,legacy:true}]:[]);
    var paid=Math.min(tc,pays.reduce(function(s,p){return s+(+p.amount||0);},0)), due=Math.max(0,tc-paid);
    if(inR(l.date))rows.push({date:l.date,ord:0,ref:l.inv||'LOAD',memo:true,desc:'Fuel bill — '+(l.type||'')+' '+_sL(l.vol,0)+' L'+(l.supplier?' · '+l.supplier:'')+' · ₹'+_sN(tc),
      sub:'landed ₹'+_sN((+l.vol||0)>0?tc/l.vol:0)+'/L'+(l.billTotal?' · bill ₹'+_sN(l.billTotal):'')+(l.lorryRent?' + lorry ₹'+_sN(l.lorryRent):'')+
          (l.lorry?' · '+l.lorry:'')+' · paid ₹'+_sN(paid)+(due>0.5?' · DUE ₹'+_sN(due):'')+' · bill shown for information',warn:due>0.5});
    pays.forEach(function(p){
      if(!inR(p.date)||!((+p.amount||0)>0))return;
      rows.push({date:p.date,ord:0,ref:l.inv||'LOAD',dr:+p.amount,desc:'Paid for fuel — '+(l.type||'')+(l.supplier?' · '+l.supplier:'')+(l.inv?' (invoice '+l.inv+')':''),
        sub:[p.mode&&p.mode!=='—'?p.mode:'',p.ref||'',p.legacy?'payment date not recorded — shown on the bill date':'',
             !p.legacy&&p.date!==l.date?'bill of '+_sD(l.date):''].filter(Boolean).join(' · ')});
    });
  });"""),

("S2 statement note",
r"""(a fuel load’s payment has no date of its own, so it shows on the bill date).""",
r"""(a payment recorded before payment dates were kept shows on its bill date)."""),

("R1 dues: fuel due dates",
r"""  (typeof fuelLoads!=='undefined'?fuelLoads:[]).forEach(function(l){
    var tc=+(l.totalCost!=null?l.totalCost:l.total_cost)||0, paid=Math.min(tc,+l.amountPaid||0), due=tc-paid; if(due<=0.5)return;
    fuelDue+=due; var age=_rvDays(l.date,today);
    P.push({late:-1,age:age,r:['Fuel',{v:l.date,s:_rvDmy(l.date)},l.supplier||'—',(l.type||'')+' '+_rvFmt(+l.vol||0,'L')+(l.inv?' · '+l.inv:''),tc,paid,due,{v:'',s:'—'},age]});
  });""",
r"""  (typeof fuelLoads!=='undefined'?fuelLoads:[]).forEach(function(l){
    var tc=+(l.totalCost!=null?l.totalCost:l.total_cost)||0, paid=Math.min(tc,(typeof _flPaid==='function')?_flPaid(l):(+l.amountPaid||0)), due=tc-paid; if(due<=0.5)return;
    fuelDue+=due; var age=_rvDays(l.date,today);
    var dd=(typeof _flDueDate==='function')?_flDueDate(l):null, late=dd?_rvDays(dd,today):-1;   // MF_FUELLOAD_V1
    if(late>0)overdue+=due;
    P.push({late:late,age:age,r:['Fuel',{v:l.date,s:_rvDmy(l.date)},l.supplier||'—',(l.type||'')+' '+_rvFmt(+l.vol||0,'L')+(l.inv?' · '+l.inv:''),tc,paid,due,
      dd?{v:dd,s:_rvDmy(dd)+(late>0?' · '+late+' d late':''),c:late>0?'var(--red)':null}:{v:'',s:'no credit days set'},age]});
  });"""),

("R2 dues card wording",
r"""'oil bills past their credit days']""",
r"""'bills past their credit days']"""),

("R3 dues note",
r"""Due dates come from each oil supplier’s credit days (⚙ on Oil Register). Fuel loads have no due date.""",
r"""Due dates come from each supplier’s credit days (⚙ on the bill, Oil Register or Fuel Loads)."""),

("A0 delivery alert stops once the shortfall is settled",
r"""    var e=_receiptEval(l); return e&&(e.short||e.dBad); });""",
r"""    var e=_receiptEval(l); return e&&((e.short&&!(typeof _flDecided==='function'&&_flDecided(l)))||e.dBad); });   // MF_FUELLOAD_V1"""),

("A1 dashboard: overdue fuel bills too",
r"""function _supplierDueAlerts(){
  var late=(typeof oilReg!=='undefined'?oilReg:[]).filter(function(inv){
    var dd=_invDueDate(inv); return dd&&(+inv.amountDue||0)>0.5&&dd<_isoLocal(); });
  if(!late.length)return [];
  var amt=late.reduce(function(s,i){return s+(+i.amountDue||0);},0);
  return [{type:'danger',icon:'🧾',title:late.length+' supplier invoice'+(late.length>1?'s':'')+' overdue — '+fmt(amt),
    desc:[...new Set(late.map(function(i){return i.company;}))].slice(0,3).join(', '),action:'REGISTER',page:'oilreg'}];
}""",
r"""function _supplierDueAlerts(){
  var out=[];
  var late=(typeof oilReg!=='undefined'?oilReg:[]).filter(function(inv){
    var dd=_invDueDate(inv); return dd&&(+inv.amountDue||0)>0.5&&dd<_isoLocal(); });
  if(late.length){
    var amt=late.reduce(function(s,i){return s+(+i.amountDue||0);},0);
    out.push({type:'danger',icon:'🧾',title:late.length+' supplier invoice'+(late.length>1?'s':'')+' overdue — '+fmt(amt),
      desc:[...new Set(late.map(function(i){return i.company;}))].slice(0,3).join(', '),action:'REGISTER',page:'oilreg'});
  }
  // MF_FUELLOAD_V1: tanker bills past their supplier's credit days
  var fl=(typeof fuelLoads!=='undefined'&&typeof _flLate==='function')?fuelLoads.filter(function(l){return _flLate(l)>0;}):[];
  if(fl.length){
    var fa=fl.reduce(function(s,l){return s+_flDue(l);},0);
    out.push({type:'danger',icon:'⛽',title:fl.length+' fuel bill'+(fl.length>1?'s':'')+' overdue — '+fmt(fa),
      desc:[...new Set(fl.map(function(l){return l.supplier;}))].slice(0,3).join(', '),action:'LOADS',page:'fuelload'});
  }
  return out;
}"""),

("A2 credit days re-draw fuel loads too",
r"""  if(typeof logActivity==='function')logActivity('supplier_days','supplier',co,co+' • '+(n?n+' days credit':'no due date'));
  renderOilReg();""",
r"""  if(typeof logActivity==='function')logActivity('supplier_days','supplier',co,co+' • '+(n?n+' days credit':'no due date'));
  try{ renderOilReg(); }catch(e){}
  try{ if(typeof renderFuelLoads==='function')renderFuelLoads(); }catch(e){}   // MF_FUELLOAD_V1"""),

# ── sync ────────────────────────────────────────────────────────────────
("Y1 save: payments column with fallback",
r"""  // MF_FIVE_V1: delivery check rides in fuel_loads.receipt (db/017). Without the
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
  await _sbUpsert('fuel_loads', _row);""",
r"""  // MF_FIVE_V1 / MF_FUELLOAD_V1: the delivery check (fuel_loads.receipt, db/017)
  // and the payment history (fuel_loads.payments, db/019) ride in their own
  // jsonb columns. A missing column rejects the whole row, so try, drop the
  // column the server does not have, and try again.
  if (load.receipt && MF_RECEIPT_COL !== false) _row.receipt = load.receipt;
  if (Array.isArray(load.payments) && MF_FLPAY_COL !== false) _row.payments = load.payments;   // [] too: every payment reversed
  if ((_row.receipt || _row.payments) && _supa && !(typeof navigator !== 'undefined' && navigator.onLine === false)) {
    for (let i = 0; i < 3 && (_row.receipt || _row.payments); i++) {
      const r = await _supa.from('fuel_loads').upsert(_row, { onConflict: 'id' });
      if (!r.error) { if (_row.receipt) MF_RECEIPT_COL = true; if (_row.payments) MF_FLPAY_COL = true; return; }
      const m = String(r.error.message || '');
      const miss = _isMissingCol(m);
      if (_row.payments && (/payments/i.test(m) || (miss && !/receipt/i.test(m)))) {
        MF_FLPAY_COL = false; delete _row.payments;
        console.warn('fuel_loads has no payments column — apply db/019_fuel_load_payments.sql. Payment dates stay on this device until then.');
        continue;
      }
      if (_row.receipt && (/receipt/i.test(m) || miss)) {
        MF_RECEIPT_COL = false; delete _row.receipt;
        console.warn('fuel_loads has no receipt column — apply db/017_five_features.sql. Delivery checks stay on this device until then.');
        continue;
      }
      break;
    }
  }
  await _sbUpsert('fuel_loads', _row);"""),

("Y2 load: keep payments",
r"""        receipt: ('receipt' in l) ? (l.receipt||null)""",
r"""        // MF_FUELLOAD_V1: keep this device's payment history when the server has no column yet
        payments: ('payments' in l) ? (l.payments||null)
                  : ((fuelLoads.find(function(x){return String(x.id)===String(l.id);})||{}).payments||null),
        receipt: ('receipt' in l) ? (l.receipt||null)"""),

# ── module ──────────────────────────────────────────────────────────────
("V1 fuel loads module",
r"""function renderFuelLoads(){
  const list=document.getElementById('fl_records_list');""",
MODULE + r"""
function renderFuelLoads(){
  const list=document.getElementById('fl_records_list');"""),
]


def main():
    if not os.path.exists(PATH):
        sys.exit(f"✗ {PATH} not found")
    src = open(PATH, encoding="utf-8").read()
    for need in ("MF_FIVE_V1", "MF_OIL_V1", "MF_REPORTS_V1"):
        if need not in src:
            sys.exit(f"✗ {need} is not in {PATH} — apply that patch first. Nothing written.")
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
