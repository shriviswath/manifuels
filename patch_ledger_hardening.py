#!/usr/bin/env python3
"""
MF_LEDGER_V1 — credit ledger hardening.

1) EDIT            Amount/date/shift/fuel only, owner or manager. "Paid" is no
                   longer typed — it moves only through a payment, a reversal
                   or an advance, so the payment history always matches the
                   bills. Amount can't go below what is already paid. The log
                   records old → new.
2) DELETE          Owner or manager. A bill with payment records against it is
                   refused until those payments are reversed (they used to be
                   left behind and still counted as collections). Advance used
                   by the bill is handed back. Deleting a customer now removes
                   their payment records too.
3) RENAME / MERGE  One button on the customer page. Typing an existing name
                   merges the two accounts: bills, payments, advances, profile
                   (discount, billing, credit limit) all move across.
4) AGEING          0–30 / 31–60 / 61–90 / 90+ days on every customer card, and
                   a total across all customers above the list.
5) ADVANCES USED   New credit for a customer holding an advance is paid from
                   the advance first; a new advance pays their oldest unpaid
                   bills. Each link is tagged on both rows ([adv:id:₹] and
                   [used:id:₹]) so deleting a bill or a shift hands the advance
                   back. "USE ADVANCE" applies it to bills already open.
                   An advance typed in "Add transaction" is now recorded as a
                   payment too, so collection reports include it.
6) PAY ONE BILL    Mode (Cash / GPay / Paytm / Bank / Cheque) and date on each
                   bill's RECORD — it always said Cash, today.
7) NAME CHECK      Typing a new customer name in shift entry (credit or
                   collection) or the ledger suggests the existing customer it
                   resembles — "ravi " → Ravi — with a one-tap USE. The save
                   screen warns too.

Usage:  python3 patch_ledger_hardening.py [path/to/index.html]
Idempotent. Requires MF_FIVE_V1.
"""
import shutil, subprocess, sys, re, os, tempfile

PATH = sys.argv[1] if len(sys.argv) > 1 else "index.html"
SENTINEL = "MF_LEDGER_V1"
X = "\\" + "u2715"          # the ✕ glyph is written as an escape in the source

HUNKS = [
# ───────── helpers (one block) ─────────
("H0 ledger helpers",
r"""function saveCustDiscountRate(){""",
r"""// MF_LEDGER_V1 ── ledger helpers ─────────────────────────────────────────
function _ledgerCanEdit(){
  if(!_currentUser)return true;
  return !!(_isOwner||_currentUser.role==='manager');
}
function _allCustomerNames(){
  return [...new Set(ledger.map(function(e){return e.customer;}).concat(Object.keys(customerProfiles||{})))]
    .filter(Boolean).sort();
}
// Advance links, kept in the notes so they sync with the row:
//   on a bill    [adv:<advance id>:<amount>]
//   on an advance [used:<bill id>:<amount>]
function _advTags(e,kind){
  var re=new RegExp('\\['+kind+':(-?\\d+):([\\d.]+)\\]','g'), out=[], m;
  while((m=re.exec(String((e&&e.notes)||''))))out.push({id:m[1],amt:+m[2]});
  return out;
}
function _stripTag(notes,kind,id){
  return String(notes||'').split(' | ').filter(function(p){
    return p.indexOf('['+kind+':'+id+':')<0;}).join(' | ');
}
function _advSettled(e){ return _r2(_advTags(e,'adv').reduce(function(s,t){return s+t.amt;},0)); }
function _byIntId(id){ return ledger.find(function(x){return String(_intId(x.id))===String(_intId(id));}); }
function _saveLedgerRow(e){ _touch(e); if(_currentUser&&typeof sbSaveLedgerEntry==='function')sbSaveLedgerEntry(e).catch(console.error); }
// Pair the customer's oldest advance with their oldest unpaid bill until one
// side runs out. Returns the amount moved.
function _settleWithAdvance(name){
  if(!name)return 0;
  var moved=0, guard=0;
  while(guard++<500){
    var bill=_custUnpaid(name)[0];
    var adv=ledger.filter(function(e){return e.customer===name&&(e.amount||0)<0&&
        (Math.abs(e.amount)-(e.paidBack||0))>0.005;})
      .sort(function(a,b){return String(a.date||'').localeCompare(String(b.date||''))||((a.id||0)-(b.id||0));})[0];
    if(!bill||!adv)break;
    var x=_r2(Math.min(bill.amount-(bill.paidBack||0), Math.abs(adv.amount)-(adv.paidBack||0)));
    if(x<=0.005)break;
    bill.paidBack=_r2((bill.paidBack||0)+x);
    adv.paidBack=_r2((adv.paidBack||0)+x);
    bill.notes=((bill.notes?bill.notes+' | ':'')+'[adv:'+_intId(adv.id)+':'+x+'] from advance of '+adv.date).slice(0,480);
    adv.notes=((adv.notes?adv.notes+' | ':'')+'[used:'+_intId(bill.id)+':'+x+'] for bill of '+bill.date).slice(0,480);
    _saveLedgerRow(bill); _saveLedgerRow(adv);
    moved=_r2(moved+x);
  }
  if(moved>0&&typeof logActivity==='function')logActivity('advance_applied','ledger',name,name+' • '+fmt(moved)+' of advance used for bills');
  return moved;
}
// Give back whatever advance this bill consumed (before the bill goes).
function _undoAdvanceOn(bill){
  _advTags(bill,'adv').forEach(function(t){
    var a=_byIntId(t.id);
    if(a){ a.paidBack=_r2(Math.max(0,(a.paidBack||0)-t.amt)); a.notes=_stripTag(a.notes,'used',_intId(bill.id)); _saveLedgerRow(a); }
    bill.paidBack=_r2(Math.max(0,(bill.paidBack||0)-t.amt));
  });
  bill.notes=String(bill.notes||'').split(' | ').filter(function(p){return p.indexOf('[adv:')<0;}).join(' | ');
}
function _recordManualAdvance(entry){
  var ref='ADV-'+_newId();
  entry.notes=((entry.notes?entry.notes+' | ':'')+ref+': advance entered in ledger').slice(0,480);
  _recordPayments([{ledgerId:null,amount:Math.abs(entry.amount),kind:'advance'}],
    {customer:entry.customer,date:entry.date,mode:'Cash',note:'Advance entered in ledger',ref:ref,source:'ledger'});
}
// ── name matching ──
function _normName(s){ return String(s||'').toLowerCase().replace(/[^\p{L}\p{N}]/gu,''); }
function _lev(a,b){
  if(a===b)return 0; var m=a.length,n=b.length; if(!m)return n; if(!n)return m;
  var p=[],i,j; for(j=0;j<=n;j++)p[j]=j;
  for(i=1;i<=m;i++){ var prev=p[0]; p[0]=i;
    for(j=1;j<=n;j++){ var t=p[j]; p[j]=Math.min(p[j]+1,p[j-1]+1,prev+(a[i-1]===b[j-1]?0:1)); prev=t; } }
  return p[n];
}
function _similarCustomer(name){
  name=String(name||'').trim(); var n=_normName(name); if(n.length<2)return null;
  var names=_allCustomerNames(); if(names.indexOf(name)>=0)return null;
  var best=null, bd=99;
  names.forEach(function(x){ var m=_normName(x);
    var d=m===n?0:((m.indexOf(n)===0||n.indexOf(m)===0)&&Math.min(m.length,n.length)>=3?1:_lev(m,n));
    if(d<bd){bd=d;best=x;} });
  return bd<=(n.length<=4?1:2)?best:null;
}
function _nameHint(inp){
  var row=inp.closest('.cred-row,.cred-row-3'); if(!row)return;
  var h=row.querySelector('.cred-name-hint'); if(!h)return;
  var s=_similarCustomer(inp.value);
  if(!s){h.innerHTML='';return;}
  h.innerHTML='<span style="color:var(--diesel)">Did you mean <b>'+_esc(s)+'</b>? A new name opens a separate account.</span> '+
    '<button type="button" class="btn btn-g" style="padding:1px 8px;font-size:10px" data-name="'+_esc(s)+'" onclick="_useSuggested(this)">USE</button>';
}
function _useSuggested(btn){
  var row=btn.closest('.cred-row,.cred-row-3'), name=btn.getAttribute('data-name'); if(!row)return;
  var sel=row.querySelector('.cred-name-sel,.credback-name-sel'), inp=row.querySelector('.cred-new-name,.credback-new-name');
  if(sel){ if(![].some.call(sel.options,function(o){return o.value===name;})){var o=document.createElement('option');o.value=name;o.textContent=name;sel.insertBefore(o,sel.firstChild);}
    sel.style.display=''; sel.value=name; }
  if(inp){ inp.value=''; inp.style.display='none'; }
  var h=row.querySelector('.cred-name-hint'); if(h)h.innerHTML='';
  calc();
}
function _credNameIssues(){
  var out=[];
  document.querySelectorAll('#cred_list .cred-new-name, #credback_list .credback-new-name').forEach(function(inp){
    if(inp.style.display==='none'||!inp.value.trim())return;
    var s=_similarCustomer(inp.value);
    if(s)out.push({level:'warn',machine:'Customer name',msg:'"'+inp.value.trim()+'" looks like existing customer "'+s+'" — pick them from the list to keep one account'});
  });
  return out;
}
document.addEventListener('input',function(e){
  var t=e.target; if(t&&t.classList&&(t.classList.contains('cred-new-name')||t.classList.contains('credback-new-name')))_nameHint(t);
});
// ── ageing ──
function _custAgeing(name){
  var b=[0,0,0,0], today=Date.parse(_isoLocal());
  ledger.forEach(function(e){
    if(e.customer!==name||!((e.amount||0)>0))return;
    var due=_r2(e.amount-(e.paidBack||0)); if(due<=0.005)return;
    var age=Math.floor((today-Date.parse(e.date))/86400000);
    b[age<=30?0:age<=60?1:age<=90?2:3]+=due;
  });
  return b.map(_r2);
}
var _AGE_LBL=['0–30','31–60','61–90','90+'], _AGE_COL=['var(--green)','var(--diesel)','#ff8c42','var(--red)'];
function _ageStrip(name){
  var b=_custAgeing(name); if(!(b[0]+b[1]+b[2]+b[3]>0.5))return '';
  return '<div class="cust-age" style="display:flex;gap:4px;margin:6px 0 2px;font-family:\'JetBrains Mono\',monospace;font-size:9px">'+
    b.map(function(v,i){return '<span title="'+_AGE_LBL[i]+' days" style="flex:1;text-align:center;padding:2px 0;border-radius:3px;background:var(--s3);color:'+
      (v>0.5?_AGE_COL[i]:'var(--muted)')+'">'+_AGE_LBL[i]+'<br><b>'+(v>0.5?'₹'+Math.round(v).toLocaleString('en-IN'):'—')+'</b></span>';}).join('')+'</div>';
}
// ── pay one bill: mode and date ──
function _payModeHtml(id){
  var sel='<select id="pay_mode_'+id+'" style="padding:4px 6px;font-size:11px;background:var(--bg);border:1px solid var(--border);border-radius:4px;color:var(--text)">'+
    ['Cash','GPay','Paytm','Bank Transfer','Cheque','Other'].map(function(m){return '<option>'+m+'</option>';}).join('')+'</select>';
  return sel+'<input type="date" id="pay_date_'+id+'" value="'+_isoLocal()+'" style="width:130px;padding:4px 6px;font-size:11px">';
}
// ── rename / merge ──
function renameCustomer(){
  var old=currentLedgerCustomer; if(!old)return;
  if(!_ledgerCanEdit()){showToast('🔒 Only an owner or manager can rename or merge customers');return;}
  var nn=prompt('Rename "'+old+'" to:\n\nType an existing customer\'s name to MERGE the two accounts into one.',old);
  if(nn===null)return;
  nn=_clean(String(nn).trim().replace(/\s+/g,' '));
  if(!nn||nn===old)return;
  var existing=_allCustomerNames().find(function(n){return n!==old&&n.toLowerCase()===nn.toLowerCase();});
  var target=existing||nn;
  if(existing){
    var a=_custPosition(old), b=_custPosition(existing);
    if(!confirm('MERGE "'+old+'" into "'+existing+'"?\n\n'+old+': owes '+fmt(a.due)+(a.advLeft>0.005?', advance '+fmt(a.advLeft):'')+
      '\n'+existing+': owes '+fmt(b.due)+(b.advLeft>0.005?', advance '+fmt(b.advLeft):'')+
      '\n\nEvery bill, payment and advance moves to "'+existing+'". "'+old+'" disappears. This cannot be undone with one tap.'))return;
  } else if(!confirm('Rename "'+old+'" to "'+nn+'"? Every bill and payment moves with it.'))return;
  var nBills=0, nPays=0;
  ledger.forEach(function(e){ if(e.customer===old){ e.customer=target; _saveLedgerRow(e); nBills++; } });
  (ledgerPayments||[]).forEach(function(p){ if(p.customer===old){ p.customer=target; p.updatedAt=new Date().toISOString(); nPays++;
    if(_currentUser&&MF_PAYTBL_OK&&typeof sbSaveLedgerPayment==='function')sbSaveLedgerPayment(p).catch(console.error); } });
  savePaymentsLS();
  var po=customerProfiles[old];
  if(po){
    var pt=customerProfiles[target];
    if(!pt) customerProfiles[target]=Object.assign({},po);
    else {
      if(!(pt.discountPerL>0)&&po.discountPerL>0)pt.discountPerL=po.discountPerL;
      var bo=po.billing||{}, bt=pt.billing||{}, merged=Object.assign({},bo);
      Object.keys(bt).forEach(function(k){ if(bt[k]!==''&&bt[k]!=null&&bt[k]!==0)merged[k]=bt[k]; });
      pt.billing=merged; if(!pt.notes&&po.notes)pt.notes=po.notes;
    }
    delete customerProfiles[old]; saveCustProfiles();
    if(_currentUser){
      if(typeof sbSaveCustProfile==='function')sbSaveCustProfile(target).catch(console.error);
      _sbRemove('customer_profiles', old, 'customer_name');
    }
    _tombAdd('customer_profiles', old);
  }
  if(existing)_settleWithAdvance(target);   // one account now: its advance meets its bills
  saveLedger();
  if(typeof logActivity==='function')logActivity(existing?'merge_customer':'rename_customer','customer',target,
    (existing?'Merged "':'Renamed "')+old+'" → "'+target+'" • '+nBills+' ledger rows, '+nPays+' payments');
  refreshCreditSelects();refreshCredBackSelects();
  openLedgerDetail(target);
  showToast(existing?'✓ Merged into '+target:'✓ Renamed to '+target);
}
function applyAdvanceNow(){
  var name=currentLedgerCustomer; if(!name)return;
  var pos=_custPosition(name);
  if(!(pos.due>0.005&&pos.advLeft>0.005)){showToast('Nothing to apply');return;}
  if(!confirm('Use '+fmt(Math.min(pos.due,pos.advLeft))+' of '+name+'\'s advance to pay their oldest unpaid bills?'))return;
  var m=_settleWithAdvance(name); saveLedger();
  openLedgerDetail(name); showToast('✓ '+fmt(m)+' of advance applied');
}
function saveCustDiscountRate(){"""),

# ───────── 1. edit ─────────
("E1 edit: role check",
r"""function editLedgerEntry(id){
  const e=ledger.find(x=>x.id===id);if(!e)return;""",
r"""function editLedgerEntry(id){
  const e=ledger.find(x=>x.id===id);if(!e)return;
  if(!_ledgerCanEdit()){showToast('🔒 Only an owner or manager can edit ledger entries');return;}   // MF_LEDGER_V1"""),

("E2 edit: paid is read-only",
r"""    <td><input type="number" id="ed_paid_${id}" value="${e.paidBack}" style="width:90px;padding:3px 6px;font-size:11px"></td>""",
r"""    <td style="font-size:11px;color:var(--muted)">&#8377;${(e.paidBack||0).toLocaleString('en-IN')}<br><span style="font-size:9px">changes only by payment / reversal</span></td>"""),

("E3 edit: validated save with old → new",
r"""function saveEditLedger(id){
  const e=ledger.find(x=>x.id===id);if(!e)return;
  e.date=document.getElementById('ed_date_'+id).value||e.date;
  e.shift=document.getElementById('ed_shift_'+id).value;
  e.fuel=document.getElementById('ed_fuel_'+id).value;
  e.amount=parseFloat(document.getElementById('ed_amt_'+id).value)||e.amount;
  e.paidBack=parseFloat(document.getElementById('ed_paid_'+id).value)||0;
  saveLedger();""",
r"""function saveEditLedger(id){
  const e=ledger.find(x=>x.id===id);if(!e)return;
  // MF_LEDGER_V1: "paid" moves only through payments, reversals and advances.
  if(!_ledgerCanEdit()){showToast('🔒 Only an owner or manager can edit ledger entries');return;}
  const nd=document.getElementById('ed_date_'+id).value||e.date;
  const ns=document.getElementById('ed_shift_'+id).value;
  const nf=document.getElementById('ed_fuel_'+id).value;
  const na=_r2(parseFloat(document.getElementById('ed_amt_'+id).value));
  if(!isFinite(na)||na===0){showToast('Enter the amount (delete the entry if it should not exist)');return;}
  if((na<0)!==((e.amount||0)<0)){showToast(e.amount<0?'An advance stays negative':'A credit stays positive');return;}
  if(Math.abs(na)+0.005<(e.paidBack||0)){
    showToast(fmt(e.paidBack)+' is already '+(e.amount<0?'used':'paid')+' against it — reverse that first');return;}
  const ch=[];
  if(nd!==e.date)ch.push('date '+e.date+' → '+nd);
  if(ns!==e.shift)ch.push('shift '+e.shift+' → '+ns);
  if(nf!==e.fuel)ch.push('fuel '+e.fuel+' → '+nf);
  if(na!==_r2(e.amount))ch.push('amount '+fmt(e.amount)+' → '+fmt(na));
  if(!ch.length){openLedgerDetail(currentLedgerCustomer);return;}
  e.date=nd; e.shift=ns; e.fuel=nf; e.amount=na;
  if(typeof logActivity==='function')logActivity('edit_ledger','ledger',id,e.customer+' • '+ch.join(' • '));
  if(na>0)_settleWithAdvance(e.customer);
  saveLedger();"""),

("E3b edit: old log line removed",
r"""  if(typeof logActivity==='function')logActivity('edit_ledger','ledger',id,e.customer+' → '+fmt(e.amount));
  openLedgerDetail(currentLedgerCustomer);showToast('Entry updated.');""",
r"""  openLedgerDetail(currentLedgerCustomer);showToast('Entry updated.');   // MF_LEDGER_V1: logged above with old → new"""),

# ───────── 2. delete ─────────
("D1 delete a ledger row safely",
r"""function delLedger(id){
  if(!confirm('Delete this transaction?'))return;
  const _gone=ledger.find(x=>x.id===id);""",
r"""function delLedger(id){
  // MF_LEDGER_V1
  if(!_ledgerCanEdit()){showToast('🔒 Only an owner or manager can delete ledger entries');return;}
  const _e=ledger.find(x=>x.id===id); if(!_e)return;
  const _pays=(ledgerPayments||[]).filter(function(p){return p.ledgerId!=null&&String(_intId(p.ledgerId))===String(_intId(id));});
  if(_pays.length){
    showToast(fmt(_pays.reduce(function(s,p){return s+(+p.amount||0);},0))+' of payments are recorded against this bill — reverse them first (Payment history → REVERSE)');
    return;
  }
  const _isAdv=(_e.amount||0)<0;
  if(_isAdv&&(_e.paidBack||0)>0.005){
    showToast('This advance has been used ('+fmt(_e.paidBack)+') — delete or reverse what used it first');return;}
  const _fromAdv=_isAdv?0:_advSettled(_e);
  const _legacy=_isAdv?0:_r2((_e.paidBack||0)-_fromAdv);
  if(_legacy>0.005&&_currentUser&&!_isOwner){
    showToast('🔒 '+fmt(_legacy)+' was marked paid without a payment record — only an owner can delete it');return;}
  let _msg='Delete this '+(_isAdv?'advance':'credit')+' of '+fmt(Math.abs(_e.amount||0))+' ('+_e.date+')?';
  if(_fromAdv>0.005)_msg+='\n\n'+fmt(_fromAdv)+' of advance that paid it goes back to the customer\'s advance.';
  if(_legacy>0.005)_msg+='\n\n⚠ '+fmt(_legacy)+' was marked paid on it with no payment record — that amount disappears with it.';
  if(_e.shiftId)_msg+='\n\nIt was entered in shift '+_e.shiftId+'. The shift\'s cash tally still counts it; deleting and re-entering the shift is the cleaner fix.';
  if(!confirm(_msg))return;
  if(!_isAdv)_undoAdvanceOn(_e);
  const _gone=_e;"""),

("D2 delete customer: role + payment records",
r"""function deleteCustomer(name){
  const rows=ledger.filter(e=>e.customer===name);""",
r"""function deleteCustomer(name){
  if(!_ledgerCanEdit()){showToast('🔒 Only an owner or manager can delete a customer');return;}   // MF_LEDGER_V1
  const rows=ledger.filter(e=>e.customer===name);"""),

("D2b delete customer: remove their payments",
r"""  ledger=ledger.filter(e=>e.customer!==name);
  delete customerProfiles[name];""",
r"""  ledger=ledger.filter(e=>e.customer!==name);
  // MF_LEDGER_V1: their payment records go too, or collections keep counting them.
  const _cp=(ledgerPayments||[]).filter(function(p){return p.customer===name;});
  if(_cp.length){
    ledgerPayments=ledgerPayments.filter(function(p){return p.customer!==name;}); savePaymentsLS();
    if(_currentUser&&MF_PAYTBL_OK)_cp.forEach(function(p){sbDelete('ledger_payments',_intId(p.id)).catch(console.error);});
  }
  delete customerProfiles[name];"""),

# ───────── 3. rename / merge + use advance buttons ─────────
("R1 header buttons",
r"""<button class="btn btn-g" onclick="addLedgerEntryFor()" style="padding:6px 14px">&#65291; ADD TRANSACTION</button>""",
r"""<button class="btn btn-g" onclick="addLedgerEntryFor()" style="padding:6px 14px">&#65291; ADD TRANSACTION</button>
      <!-- MF_LEDGER_V1 -->
      <button class="btn btn-g" id="use_adv_btn" onclick="applyAdvanceNow()" style="padding:6px 14px;display:none">↺ USE ADVANCE</button>
      <button class="btn btn-g" onclick="renameCustomer()" style="padding:6px 14px">✎ RENAME / MERGE</button>"""),

("R2 detail: show USE ADVANCE when both exist",
r"""  if(typeof _renderCustLimitBadge==='function')_renderCustLimitBadge(name);   // MF_FIVE_V1""",
r"""  if(typeof _renderCustLimitBadge==='function')_renderCustLimitBadge(name);   // MF_FIVE_V1
  { const _ub=document.getElementById('use_adv_btn'), _ps=_custPosition(name);   // MF_LEDGER_V1
    if(_ub){ const _can=_ps.due>0.005&&_ps.advLeft>0.005; _ub.style.display=_can?'':'none';
      if(_can)_ub.textContent='↺ USE ADVANCE '+fmt(Math.min(_ps.due,_ps.advLeft)); } }"""),

# ───────── 4. ageing ─────────
("A1 ageing total container",
r"""    <div id="led_period_note" style="font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--muted);margin-bottom:14px;line-height:1.6"></div>""",
r"""    <div id="led_ageing" style="margin-bottom:10px"></div><!-- MF_LEDGER_V1 -->
    <div id="led_period_note" style="font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--muted);margin-bottom:14px;line-height:1.6"></div>"""),

("A2 ageing on each card",
r"""      <div class="cust-boxes">${boxes}</div>""",
r"""      <div class="cust-boxes">${boxes}</div>
      ${_ageStrip(name)}"""),

("A3 ageing total",
r"""  const advEl=document.getElementById('led_advance_held');
  if(advEl)advEl.textContent=_r0(totalAdvanceHeld);""",
r"""  const advEl=document.getElementById('led_advance_held');
  if(advEl)advEl.textContent=_r0(totalAdvanceHeld);
  // MF_LEDGER_V1: how old the money owed is
  { const _ag=document.getElementById('led_ageing');
    if(_ag){ const T=[0,0,0,0]; names.forEach(function(n){ _custAgeing(n).forEach(function(v,i){T[i]+=v;}); });
      const tot=T[0]+T[1]+T[2]+T[3];
      _ag.innerHTML=tot>0.5?'<div style="font-family:\'Syne\',sans-serif;font-weight:700;font-size:10px;letter-spacing:1.5px;color:var(--muted);margin-bottom:4px">UNPAID BILLS BY AGE</div>'+
        '<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:6px">'+T.map(function(v,i){
          return '<div class="mini-card" style="text-align:center"><div class="mini-lbl">'+_AGE_LBL[i]+' DAYS</div><div class="mini-val" style="color:'+
            (v>0.5?_AGE_COL[i]:'var(--muted)')+'">'+_r0(v)+'</div><div style="font-size:9px;color:var(--muted)">'+(tot?Math.round(v/tot*100):0)+'%</div></div>';}).join('')+'</div>':''; } }"""),

# ───────── 5. advances used automatically ─────────
("V1 shift save: settle with advance",
r"""  saveLedger();
  }
  refreshCreditSelects();refreshCredBackSelects();
  const rec={""",
r"""  // MF_LEDGER_V1: credit for someone holding an advance is paid from it first.
  try{ [...new Set(ledger.filter(function(e){return e.shiftId===_shiftIdStr&&(e.amount||0)>0;})
        .map(function(e){return e.customer;}))].forEach(_settleWithAdvance); }catch(err){ console.warn('advance settle:',err); }
  saveLedger();
  }
  refreshCreditSelects();refreshCredBackSelects();
  const rec={"""),

("V2 ledger add (new customer form)",
r"""  const newEntry3={id:_newId(),date,customer:name,shift,fuel,amount:amt,paidBack:0,kind:type};
  ledger.push(newEntry3);
  saveLedger();""",
r"""  const newEntry3={id:_newId(),date,customer:name,shift,fuel,amount:amt,paidBack:0,kind:type};
  ledger.push(newEntry3);
  if(type==='advance')_recordManualAdvance(newEntry3);   // MF_LEDGER_V1
  _settleWithAdvance(name);
  saveLedger();"""),

("V2b ledger add: name check",
r"""  if(!name||!amt){showToast('Fill in name and amount');return;}""",
r"""  if(!name||!amt){showToast('Fill in name and amount');return;}
  { const _s=_similarCustomer(name);   // MF_LEDGER_V1
    if(_s&&confirm('"'+name+'" looks like existing customer "'+_s+'".\n\nOK = add it to '+_s+'\nCancel = create a new customer "'+name+'"'))name=_s; }"""),

("V2c ledger add: name is reassignable",
r"""function submitLedgerEntry(){
  const name=_clean(document.getElementById('lf_name').value.trim());""",
r"""function submitLedgerEntry(){
  let name=_clean(document.getElementById('lf_name').value.trim());"""),

("V3 ledger add (existing customer)",
r"""  const newEntry2={id:_newId(),date,customer:currentLedgerCustomer,shift,fuel,amount:amt,paidBack:0,kind:type};
  ledger.push(newEntry2);
  saveLedger();""",
r"""  const newEntry2={id:_newId(),date,customer:currentLedgerCustomer,shift,fuel,amount:amt,paidBack:0,kind:type};
  ledger.push(newEntry2);
  if(type==='advance')_recordManualAdvance(newEntry2);   // MF_LEDGER_V1
  _settleWithAdvance(currentLedgerCustomer);
  saveLedger();"""),

("V4 shift undo: advance-paid credits are not 'paid'",
r"""  const settled=credits.filter(function(e){return (e.paidBack||0)>0.005;});
  const freeCredits=credits.filter(function(e){return !((e.paidBack||0)>0.005);});""",
r"""  // MF_LEDGER_V1: only money actually paid blocks the undo; advance is handed back.
  const _real=function(e){return (e.paidBack||0)-(typeof _advSettled==='function'?_advSettled(e):0);};
  const settled=credits.filter(function(e){return _real(e)>0.005;});
  const freeCredits=credits.filter(function(e){return !(_real(e)>0.005);});"""),

("V4b shift undo: return advance",
r"""  // 5. credit given in the shift, and advances it created
  const drop=new Set(""",
r"""  // MF_LEDGER_V1: advance that paid these credits goes back to the customer
  if(typeof _undoAdvanceOn==='function')plan.freeCredits.forEach(_undoAdvanceOn);
  // 5. credit given in the shift, and advances it created
  const drop=new Set("""),

# ───────── 6. pay one bill: mode + date ─────────
("M1 bill row: mode and date",
r"""          <button class="btn btn-g" style="padding:5px 12px;font-size:11px;white-space:nowrap;${settled?'opacity:.4;pointer-events:none':''}" onclick="markPaid(${e.id})">""",
r"""          ${(!isAdvance&&!settled&&typeof _payModeHtml==='function')?_payModeHtml(e.id):''}
          <button class="btn btn-g" style="padding:5px 12px;font-size:11px;white-space:nowrap;${settled?'opacity:.4;pointer-events:none':''}" onclick="markPaid(${e.id})">"""),

("M2 markPaid: use the chosen mode and date",
r"""      {customer:entry.customer, date:_isoLocal(), mode:'Cash',
       note:'Recorded against '+(entry.date||'')+' bill',""",
r"""      {customer:entry.customer,
       date:((document.getElementById('pay_date_'+id)||{}).value||_isoLocal()),   // MF_LEDGER_V1
       mode:((document.getElementById('pay_mode_'+id)||{}).value||'Cash'),
       note:'Recorded against '+(entry.date||'')+' bill',"""),

# ───────── 7. name check in shift entry ─────────
("N1 credit row: name hint",
r"""    <div class="cred-limit-hint" style="grid-column:1/-1;font-family:'JetBrains Mono',monospace;font-size:10px;line-height:1.4"></div>`;""",
r"""    <div class="cred-limit-hint" style="grid-column:1/-1;font-family:'JetBrains Mono',monospace;font-size:10px;line-height:1.4"></div>
    <div class="cred-name-hint" style="grid-column:1/-1;font-family:'JetBrains Mono',monospace;font-size:10px;line-height:1.4"></div>`;"""),

("N2 collection row: name hint",
r"""    <button class="rm-btn" onclick="document.getElementById('cb_${id}').remove();calc()">@@X@@</button>`;""",
r"""    <button class="rm-btn" onclick="document.getElementById('cb_${id}').remove();calc()">@@X@@</button>
    <div class="cred-name-hint" style="grid-column:1/-1;font-family:'JetBrains Mono',monospace;font-size:10px;line-height:1.4"></div>`;"""),

("N3 save confirmation: name warning",
r"""  if(typeof _credLimitIssues==='function')Array.prototype.push.apply(_extra, _credLimitIssues());   // MF_FIVE_V1""",
r"""  if(typeof _credLimitIssues==='function')Array.prototype.push.apply(_extra, _credLimitIssues());   // MF_FIVE_V1
  if(typeof _credNameIssues==='function')Array.prototype.push.apply(_extra, _credNameIssues());   // MF_LEDGER_V1"""),

# ───────── reversal of an advance that was auto-applied ─────────
("P1 reversePayment: advance used by auto-settle can be reversed",
r"""  if(advRows.some(function(e){return (e.paidBack||0)>0.005;})){
    showToast('The advance from this payment has already been used — reverse that first');return;}""",
r"""  // MF_LEDGER_V1: use through [used:] links (auto-settled bills) is undone with
  // the payment; only fuel drawn by hand against the advance blocks it.
  var _autoUsed=function(e){return _advTags(e,'used').reduce(function(s,t){return s+t.amt;},0);};
  if(advRows.some(function(e){return (e.paidBack||0)-_autoUsed(e)>0.005;})){
    showToast('Fuel has been drawn against the advance from this payment — reverse that first');return;}
  var _linked=[]; advRows.forEach(function(a){ _advTags(a,'used').forEach(function(t){ var b=_byIntId(t.id); if(b)_linked.push({a:a,b:b,amt:t.amt}); }); });"""),

("P2 reversePayment: confirm mentions linked bills",
r"""    (advAmt>0?'\n• the '+fmt(advAmt)+' advance it created is removed':'')+""",
r"""    (advAmt>0?'\n• the '+fmt(advAmt)+' advance it created is removed':'')+
    (_linked.length?'\n• '+_linked.length+' bill(s) that advance paid go back to unpaid':'')+"""),

("P3 reversePayment: undo advance links",
r"""  if(advRows.length){
    var drop=new Set(advRows.map(function(e){return String(e.id);}));""",
r"""  _linked.forEach(function(x){   // MF_LEDGER_V1
    x.b.paidBack=_r2(Math.max(0,(x.b.paidBack||0)-x.amt));
    x.b.notes=_stripTag(x.b.notes,'adv',_intId(x.a.id));
    _saveLedgerRow(x.b);
  });
  if(advRows.length){
    var drop=new Set(advRows.map(function(e){return String(e.id);}));"""),
]


def main():
    if not os.path.exists(PATH):
        sys.exit(f"✗ {PATH} not found")
    src = open(PATH, encoding="utf-8").read()
    if "MF_FIVE_V1" not in src:
        sys.exit("✗ Apply patch_five_features.py (MF_FIVE_V1) first. Nothing written.")
    out = src
    applied = 0
    for h in HUNKS:
        name, old, new = h[0], h[1].replace("@@X@@", X), h[2].replace("@@X@@", X)
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
