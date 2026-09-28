#!/usr/bin/env python3
"""
MF_SHIFT_ENTRY_V1 — shift entry: never lose a shift, fix one without retyping.

1) AUTO-SAVE DRAFT   Everything on the form — meters, payments, expenses, pack
                     and loose oil, credit and collection rows, oil sold, notes,
                     price split, attendance marks — is kept on the phone as you
                     type, per shift (date + morning/night). Coming back to that
                     shift (reload, app killed, battery) shows
                     "Unsaved entry … RESTORE / DISCARD". Cleared on save.
                     Also keeps typed oil-sold quantities through a background
                     sync (the table used to be redrawn from an empty list).
2) EDIT A SAVED SHIFT History → ✎ EDIT loads the saved shift back into the form:
                     meters, rates (and price split, for shifts saved from now
                     on), payments, expense heads, testing, packs, loose oil,
                     credit rows, collections, oil sold, notes, tag. Change what
                     is wrong and SAVE — the existing re-save undoes the old
                     entry first. Locked shifts are refused.
3) COUNT NOTES       ₹500 / 200 / 100 / 50 / 20 / 10 × count + coins → fills
                     Cash. The breakdown is stored with the shift.
4) OPENINGS FILL     When a shift is opened (and after each save, for the next
   THEMSELVES        one) the openings are carried from the last closing —
                     meters, loose oil, packs. Only empty boxes are filled.
5) NUMBER KEYPAD     Every number box asks the phone for the number pad; Enter
                     moves to the next box.
6) PRICE CHECK       On save: warns when a fuel rate differs from the last
                     shift's, or from the selling rate of a tanker received
                     since then — the day a price revision is missed.

Usage:  python3 patch_shift_entry.py [path/to/index.html]
Idempotent. Requires MF_LEDGER_SEARCH_V1.
"""
import shutil, subprocess, sys, re, os, tempfile

PATH = sys.argv[1] if len(sys.argv) > 1 else "index.html"
SENTINEL = "MF_SHIFT_ENTRY_V1"

HUNKS = [
# ───────── HTML ─────────
("H1 draft / edit banner",
r"""  <div class="entry-grid">
    <!-- LEFT: Collections -->""",
r"""  <!-- MF_SHIFT_ENTRY_V1: unsaved draft / editing a saved shift -->
  <div id="draft_banner" style="display:none;margin:0 0 10px;padding:10px 12px;border-radius:6px;border:1px solid var(--diesel);background:rgba(255,176,32,.08);font-family:'JetBrains Mono',monospace;font-size:12px"></div>
  <div class="entry-grid">
    <!-- LEFT: Collections -->"""),

("H2 cash counter",
r"""        <div class="frow"><span class="flabel">Cash (₹)</span><input type="number" id="p_cash" placeholder="0" oninput="calc()"></div>""",
r"""        <div class="frow"><span class="flabel">Cash (₹)</span><input type="number" id="p_cash" placeholder="0" oninput="calc()"></div>
        <!-- MF_SHIFT_ENTRY_V1: count the drawer by notes -->
        <div style="margin:-2px 0 6px;display:flex;gap:8px;align-items:center;flex-wrap:wrap">
          <button type="button" class="btn btn-g" style="padding:3px 10px;font-size:10px" onclick="var p=document.getElementById('cash_counter');p.style.display=p.style.display==='none'?'block':'none'">🧮 COUNT NOTES</button>
          <span id="cash_count_note" style="font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--muted)"></span>
        </div>
        <div id="cash_counter" style="display:none;background:var(--s3);border-radius:6px;padding:8px;margin-bottom:8px">
          <div style="display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:6px">
            <div><label>₹500 ×</label><input type="number" id="cash_n500" min="0" step="1" placeholder="0" oninput="_cashCount()"></div>
            <div><label>₹200 ×</label><input type="number" id="cash_n200" min="0" step="1" placeholder="0" oninput="_cashCount()"></div>
            <div><label>₹100 ×</label><input type="number" id="cash_n100" min="0" step="1" placeholder="0" oninput="_cashCount()"></div>
            <div><label>₹50 ×</label><input type="number" id="cash_n50" min="0" step="1" placeholder="0" oninput="_cashCount()"></div>
            <div><label>₹20 ×</label><input type="number" id="cash_n20" min="0" step="1" placeholder="0" oninput="_cashCount()"></div>
            <div><label>₹10 ×</label><input type="number" id="cash_n10" min="0" step="1" placeholder="0" oninput="_cashCount()"></div>
            <div style="grid-column:span 2"><label>COINS (₹ total)</label><input type="number" id="cash_coins" min="0" step="1" placeholder="0" oninput="_cashCount()"></div>
          </div>
          <div style="font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--muted);margin-top:6px">The total goes into Cash as you count. The breakdown is saved with the shift.</div>
        </div>"""),

("H3 History: EDIT",
r"""             <button class="btn btn-g" style="padding:3px 8px;font-size:10px" data-id="${r.id}"
               onclick="askDelRec(this)">DEL</button>`}""",
r"""             <button class="btn btn-g" style="padding:3px 8px;font-size:10px" data-id="${r.id}"
               onclick="editShiftInForm(this.dataset.id)" title="Load into the shift form to correct it">✎ EDIT</button>
             <button class="btn btn-g" style="padding:3px 8px;font-size:10px" data-id="${r.id}"
               onclick="askDelRec(this)">DEL</button>`}"""),

# ───────── JS module ─────────
("J1 module",
r"""function _entryPristine(){""",
r"""// MF_SHIFT_ENTRY_V1 ──────────────────────────────────────────────────────
var MF_DRAFT_PREFIX='mf_shift_draft_';
var _draftRestoring=false, _draftTimer=null, _editingShiftId=null;
function _curSlotId(){ return ((document.getElementById('shiftId')||{}).textContent||'').trim(); }
function _splitOn(t){ var e=document.getElementById(t+'_price_split'); return !!(e&&e.style.display!=='none'); }
var _CASH_D=[500,200,100,50,20,10];
function _cashNotes(){
  var o={}, any=false;
  _CASH_D.forEach(function(d){ var n=parseInt((document.getElementById('cash_n'+d)||{}).value,10)||0; if(n){o['n'+d]=n;any=true;} });
  var c=parseFloat((document.getElementById('cash_coins')||{}).value)||0; if(c){o.coins=c;any=true;}
  return any?o:null;
}
function _cashCountNote(){
  var o=_cashNotes(), el=document.getElementById('cash_count_note'); if(!el)return;
  if(!o){el.textContent='';return;}
  var tot=_CASH_D.reduce(function(s,d){return s+(o['n'+d]||0)*d;},0)+(o.coins||0);
  el.textContent='Counted '+_CASH_D.filter(function(d){return o['n'+d];}).map(function(d){return o['n'+d]+'×'+d;}).join(' + ')+
    (o.coins?' + ₹'+o.coins+' coins':'')+' = '+fmt(tot);
  var p=document.getElementById('cash_counter'); if(p&&p.style.display==='none')p.style.display='block';
  return tot;
}
function _cashCount(){
  var o=_cashNotes(); var tot=_cashCountNote();
  if(o){ var pc=document.getElementById('p_cash'); if(pc)pc.value=tot; }
  calc(); _saveDraftSoon();
}
function _shiftRates(){
  var sp=function(t){ return _splitOn(t)?{bl:v(t+'_before_l'),r1:v(t+'_rate1'),al:v(t+'_after_l'),r2:v(t+'_rate2')}:null; };
  return {msd:v('msd_rate'),hsd:v('hsd_rate'),msdSplit:sp('msd'),hsdSplit:sp('hsd')};
}
// ── draft: collect / content / store ──
function _collectDraft(){
  var f={};
  document.querySelectorAll('#page-entry input[id], #page-entry select[id], #page-entry textarea[id]').forEach(function(e){
    if(e.id==='shiftDate'||e.closest('#sa_card')||/^cred(back)?_new_/.test(e.id))return;
    f[e.id]=e.type==='checkbox'?e.checked:e.value;
  });
  var rows=function(sel,cls){ var out=[];
    document.querySelectorAll(sel).forEach(function(r){
      var s=r.querySelector('.'+cls+'-name-sel'), i=r.querySelector('.'+cls+'-new-name');
      var isNew=!s||s.style.display==='none'||s.value==='__new__';
      out.push({name:isNew?(i?i.value:''):s.value, isNew:isNew,
                fuel:(r.querySelector('.cred-fuel')||{}).value||'', amt:(r.querySelector('.'+cls+'-amt')||{}).value||''});
    }); return out; };
  var ss={}; document.querySelectorAll('.ss-qty').forEach(function(e){ if(e.value)ss[e.dataset.id]=e.value; });
  var date=(document.getElementById('shiftDate')||{}).value||'';
  return {v:1, slot:_curSlotId(), date:date, shift:shift, at:new Date().toISOString(), f:f,
          credits:rows('#cred_list .cred-row','cred'), credbacks:rows('#credback_list .cred-row-3','credback'),
          loose:[].map.call(document.querySelectorAll('#loose_open_list .loose-row'),function(r){
            return {id:r.querySelector('.loose-item').value, qty:r.querySelector('.loose-qty').value};}),
          ss:ss, split:{msd:_splitOn('msd'),hsd:_splitOn('hsd')},
          att:(typeof _saDrafts!=='undefined'&&_saDrafts[_saKey(date,shift)])||null, editing:_editingShiftId};
}
// Carried openings and saved rates are not "work" — without anything else
// typed there is nothing to lose.
function _draftHasContent(d){
  if(!d)return false;
  if(d.editing)return true;
  var typed=Object.keys(d.f).some(function(k){
    var val=d.f[k]; if(val===''||val===false||val==null)return false;
    return !/_prev$|_rate\d?$|^pack\d*_rate$|^oil_rate$/.test(k);
  });
  return typed||d.credits.some(function(c){return c.amt;})||d.credbacks.some(function(c){return c.amt;})||
         Object.keys(d.ss).length>0||(d.loose.length>0&&!!d.f.oil_cur);
}
function _readDraft(slot){ try{ return JSON.parse(localStorage.getItem(MF_DRAFT_PREFIX+slot)||'null'); }catch(e){ return null; } }
function _dropDraft(slot){ try{ localStorage.removeItem(MF_DRAFT_PREFIX+slot); }catch(e){} }
function _pruneDrafts(){
  try{ var ks=[]; for(var i=0;i<localStorage.length;i++){ var k=localStorage.key(i); if(k&&k.indexOf(MF_DRAFT_PREFIX)===0)ks.push(k); }
    var cut=Date.now()-10*86400000;
    ks.map(function(k){var d=null;try{d=JSON.parse(localStorage.getItem(k));}catch(e){} return {k:k,t:Date.parse((d&&d.at)||0)||0};})
      .sort(function(a,b){return b.t-a.t;})
      .forEach(function(x,i){ if(i>=12||x.t<cut)localStorage.removeItem(x.k); });
  }catch(e){}
}
function _saveDraftNow(){
  if(_draftRestoring)return;
  var d=_collectDraft(); if(!d.slot)return;
  if(_draftHasContent(d)){ try{ localStorage.setItem(MF_DRAFT_PREFIX+d.slot,JSON.stringify(d)); }catch(e){} _pruneDrafts(); }
  else _dropDraft(d.slot);
  var b=document.getElementById('draft_banner');
  if(b&&b.dataset.kind==='offer'&&b.dataset.slot===d.slot&&_draftHasContent(d)){ b.style.display='none'; b.dataset.kind=''; }
}
function _saveDraftSoon(){ if(_draftRestoring)return; clearTimeout(_draftTimer); _draftTimer=setTimeout(_saveDraftNow,700); }
document.addEventListener('input',function(e){
  var t=e.target; if(!t||!t.closest||!t.closest('#page-entry')||t.id==='shiftDate')return;
  if(t.classList&&t.classList.contains('ss-qty')&&typeof shiftSales!=='undefined')shiftSales[t.dataset.id]=t.value;
  _saveDraftSoon();
},true);
document.addEventListener('change',function(e){
  var t=e.target; if(t&&t.closest&&t.closest('#page-entry')&&t.id!=='shiftDate')_saveDraftSoon();
},true);
// Saving a draft when the phone puts the app away is the whole point.
document.addEventListener('visibilitychange',function(){ if(document.visibilityState==='hidden'){ clearTimeout(_draftTimer); _saveDraftNow(); } });
window.addEventListener('pagehide',function(){ clearTimeout(_draftTimer); _saveDraftNow(); });

// ── draft: apply (restore or edit) ──
function _applyDraft(d){
  if(!d)return;
  _draftRestoring=true;
  try{
    var ds=document.getElementById('shiftDate');
    if(d.date&&ds&&ds.value!==d.date)ds.value=d.date;
    if(d.shift&&d.shift!==shift)setShift(d.shift,true);
    _slotManual=true;
    // clear the form first, keeping the saved rates unless the draft has them
    document.querySelectorAll('#page-entry input[id], #page-entry textarea[id]').forEach(function(e){
      if(e.id==='shiftDate'||e.closest('#sa_card')||e.type==='checkbox'||e.type==='radio')return;
      if(/_rate$/.test(e.id)&&!(e.id in d.f))return;
      e.value='';
    });
    ['msd','hsd'].forEach(function(t){ if(!!(d.split&&d.split[t])!==_splitOn(t))togglePriceChange(t); });
    // credit rows
    var cl=document.getElementById('cred_list'); cl.innerHTML=''; creditCount=0;
    (d.credits&&d.credits.length?d.credits:[{name:'',isNew:false,fuel:'',amt:''}]).forEach(function(c){
      addCredit(); var r=cl.lastElementChild, s=r.querySelector('.cred-name-sel'), i=r.querySelector('.cred-new-name');
      var has=s&&[].some.call(s.options,function(o){return o.value===c.name;});
      if(c.name&&has&&!c.isNew){ s.style.display=''; s.value=c.name; if(i){i.style.display='none';i.value='';} }
      else if(c.name){ if(s){s.value='__new__'; toggleNewCustInput(s,creditCount);} if(i){i.style.display='';i.value=c.name;} }
      if(c.fuel)(r.querySelector('.cred-fuel')||{}).value=c.fuel;
      (r.querySelector('.cred-amt')||{}).value=c.amt||'';
    });
    // collection rows
    var bl=document.getElementById('credback_list'); bl.innerHTML=''; credbackCount=0;
    (d.credbacks&&d.credbacks.length?d.credbacks:[{name:'',isNew:false,amt:''}]).forEach(function(c){
      addCredBack(); var r=bl.lastElementChild, s=r.querySelector('.credback-name-sel'), i=r.querySelector('.credback-new-name');
      var has=s&&[].some.call(s.options,function(o){return o.value===c.name;});
      if(c.name&&has&&!c.isNew){ s.style.display=''; s.value=c.name; if(i){i.style.display='none';i.value='';} }
      else if(c.name){ if(s){s.value='__new__'; toggleNewCredBackInput(s,credbackCount);} if(i){i.style.display='';i.value=c.name;} }
      (r.querySelector('.credback-amt')||{}).value=c.amt||'';
    });
    // loose oil bottles
    var lo=document.getElementById('loose_open_list'); if(lo)lo.innerHTML='';
    (d.loose||[]).forEach(function(x){ try{ addLooseOpen(x.id,parseInt(x.qty,10)||1); }catch(e){} });
    // static fields
    Object.keys(d.f||{}).forEach(function(k){
      var e=document.getElementById(k); if(!e||k==='shiftDate'||e.closest('#sa_card'))return;
      var val=d.f[k]; if(val==null)val='';
      if(e.type==='checkbox')e.checked=!!val; else e.value=val;
    });
    // oil sold off the counter
    if(typeof shiftSales!=='undefined'){ shiftSales=Object.assign({},d.ss||{}); renderStockSales(); }
    // attendance marks not yet saved
    if(d.att&&typeof _saDrafts!=='undefined'){ _saDrafts[_saKey(d.date,d.shift)]=d.att; renderShiftAttendance(); }
    _editingShiftId=d.editing||null;
  } finally { _draftRestoring=false; }
  _cashCountNote();
  calc();
  if(typeof renderPackStockHint==='function')renderPackStockHint();
  _renderDraftBanner();
}
// ── banner ──
function _renderDraftBanner(){
  var b=document.getElementById('draft_banner'); if(!b)return;
  var slot=_curSlotId();
  if(_editingShiftId){
    b.dataset.kind='edit'; b.dataset.slot=slot;
    b.innerHTML='✎ Editing saved shift <b>'+_esc(_editingShiftId)+'</b> — change what is wrong and SAVE. The saved entry is undone first, then this one applied. '+
      '<button type="button" class="btn btn-g" style="padding:2px 10px;font-size:10px;margin-left:6px" onclick="cancelShiftEdit()">CANCEL EDIT</button>';
    b.style.display='block'; return;
  }
  var d=_readDraft(slot);
  var formHas=_draftHasContent(_collectDraft());
  if(d&&_draftHasContent(d)&&!formHas){
    var t=new Date(d.at);
    b.dataset.kind='offer'; b.dataset.slot=slot;
    b.innerHTML='📝 Unsaved entry for <b>'+_esc(slot)+'</b> from '+t.toLocaleDateString('en-IN',{day:'2-digit',month:'short'})+' '+
      t.toLocaleTimeString('en-IN',{hour:'2-digit',minute:'2-digit'})+(d.editing?' (editing the saved shift)':'')+'. '+
      '<button type="button" class="save-btn" style="padding:3px 12px;font-size:10px;margin-left:6px;max-width:140px" onclick="restoreShiftDraft()">RESTORE</button> '+
      '<button type="button" class="btn btn-g" style="padding:3px 10px;font-size:10px" onclick="discardShiftDraft()">DISCARD</button>';
    b.style.display='block';
  } else if(b.dataset.kind!=='edit'){ b.style.display='none'; b.dataset.kind=''; }
}
function restoreShiftDraft(){ var d=_readDraft(_curSlotId()); if(d){ _applyDraft(d); showToast('✓ Unsaved entry restored'); } }
function discardShiftDraft(){
  if(!confirm('Throw away the unsaved entry for '+_curSlotId()+'?'))return;
  _dropDraft(_curSlotId()); var b=document.getElementById('draft_banner'); if(b){b.style.display='none';b.dataset.kind='';}
}
function cancelShiftEdit(){
  if(!confirm('Stop editing '+_editingShiftId+'? The saved shift stays exactly as it was.'))return;
  var id=_editingShiftId; _editingShiftId=null; _dropDraft(id);
  _applyDraft({f:{},credits:[],credbacks:[],loose:[],ss:{},split:{msd:false,hsd:false},date:null,shift:null});
  if(typeof mfJumpToDueShift==='function')mfJumpToDueShift();
  showToast('Edit cancelled — '+id+' unchanged');
}
// ── edit a saved shift ──
function _draftFromRecord(r){
  var m=r.meters||{}, f={}, ex=m.exp||{}, R=m.rates||null;
  ['msd1','msd2','hsd1','hsd2'].forEach(function(k){
    if(m[k+'_prev']!=null)f[k+'_prev']=m[k+'_prev']; if(m[k+'_cur']!=null)f[k+'_cur']=m[k+'_cur']; });
  var ratio=function(V,T){ return T>0?Math.round(V/T*100)/100:''; };
  f.msd_rate=R?R.msd:ratio(r.msdV,r.msdT); f.hsd_rate=R?R.hsd:ratio(r.hsdV,r.hsdT);
  ['msd','hsd'].forEach(function(t){ var s=R&&R[t+'Split']; if(s){ f[t+'_before_l']=s.bl; f[t+'_rate1']=s.r1; f[t+'_after_l']=s.al; f[t+'_rate2']=s.r2; } });
  f.p_gpay=r.gpay||''; f.p_paytm=r.paytm||''; f.p_cash=r.cash||'';
  f.e_tmsd=ex.tmsd||''; f.e_thsd=ex.thsd||''; f.e_toil=ex.toil||''; f.e_items=ex.items||'';
  f.e_tea=ex.tea||''; f.e_chit=ex.chit||''; f.e_other=ex.other||''; f.e_handover=r.handover||m.handover||'';
  f.t_msd_l=r.testMSDL||''; f.t_hsd_l=r.testHSDL||'';
  if(m.pack_prev!=null)f.pack_prev=m.pack_prev; if(m.pack_cur!=null)f.pack_cur=m.pack_cur; if(m.pack_units)f.pack_units=m.pack_units;
  Object.keys(m.packs||{}).forEach(function(s){ var p=m.packs[s]; if(p.prev!=null)f['pack'+s+'_prev']=p.prev; if(p.cur!=null)f['pack'+s+'_cur']=p.cur; });
  if(m.oil_prev!=null)f.oil_prev=m.oil_prev; if(m.oil_cur!=null)f.oil_cur=m.oil_cur;
  var cn=m.cash_notes||{}; _CASH_D.forEach(function(d){ if(cn['n'+d])f['cash_n'+d]=cn['n'+d]; }); if(cn.coins)f.cash_coins=cn.coins;
  f.notes=r.notes||''; f.shiftTag=r.tag||'';
  var credits=ledger.filter(function(e){return e.shiftId===r.id&&(e.amount||0)>0;})
    .map(function(e){return {name:e.customer,isNew:false,fuel:e.fuel||'',amt:e.amount};});
  var byRef={}; (typeof _shiftPays==='function'?_shiftPays(r):[]).forEach(function(p){
    var k=p.ref||p.id; (byRef[k]=byRef[k]||{name:p.customer,isNew:false,amt:0}).amt=_r2(byRef[k].amt+(+p.amount||0)); });
  var ss={}; (r.stockSold||[]).forEach(function(s){ ss[s.id]=s.qty; });
  return {v:1, slot:r.id, date:r.date, shift:r.shift, at:new Date().toISOString(), f:f,
          credits:credits, credbacks:Object.keys(byRef).map(function(k){return byRef[k];}),
          loose:(Array.isArray(r.looseOpened)?r.looseOpened:[]).map(function(o){return {id:o.id,qty:o.qty};}),
          ss:ss, split:{msd:!!(R&&R.msdSplit),hsd:!!(R&&R.hsdSplit)}, att:null, editing:r.id};
}
function editShiftInForm(id){
  var r=records.find(function(x){return x.id===id;}); if(!r)return;
  if(_isLocked(r)){showToast('🔒 '+id+' is locked — an owner must unlock it first');return;}
  if(!_entryPristine()&&_curSlotId()!==id&&!confirm('The shift form has figures for '+_curSlotId()+'. They stay saved as an unsaved entry for that shift.\n\nLoad '+id+' to edit?'))return;
  _saveDraftNow();
  var d=_draftFromRecord(r);
  _editingShiftId=id;
  showPage('entry');
  setTimeout(function(){
    _applyDraft(d);
    var noMeters=!(r.meters&&r.meters.msd1_cur!=null);
    showToast(noMeters?'Loaded '+id+' — its meter readings were not stored; type them again':'✓ '+id+' loaded — correct it and SAVE');
  },60);
}
// ── openings fill themselves; offer a draft ──
function _onSlotChanged(){
  if(_draftRestoring||_editingShiftId)return;
  try{ if(typeof carryForwardMeters==='function')carryForwardMeters(true); }catch(e){}
  _renderDraftBanner();
}
// ── price check on save ──
function _prevShiftRate(t){
  var date=(document.getElementById('shiftDate')||{}).value||'', rank=shift==='night'?2:1;
  var pr=records.filter(function(r){
    var rr=r.shift==='night'?2:1; return (r.date<date||(r.date===date&&rr<rank))&&((t==='msd'?r.msdT:r.hsdT)>0);
  }).sort(function(a,b){return String(b.date).localeCompare(String(a.date))||((b.shift==='night'?2:1)-(a.shift==='night'?2:1));})[0];
  if(!pr)return null;
  var R=pr.meters&&pr.meters.rates, s=R&&R[t+'Split'];
  var rate=s?(s.r2||s.r1):(R&&R[t])?R[t]:(t==='msd'?pr.msdV/pr.msdT:pr.hsdV/pr.hsdT);
  return {rate:Math.round(rate*100)/100, rec:pr};
}
function _rateIssues(){
  var out=[], c=getCalcVals();
  ['msd','hsd'].forEach(function(t){
    var lit=t==='msd'?c.msdT:c.hsdT, T=t.toUpperCase(); if(!(lit>0))return;
    var cur=_splitOn(t)?(v(t+'_rate2')||v(t+'_rate')):v(t+'_rate');
    if(!(cur>0)){ out.push({level:'error',machine:T+' price',msg:'No selling rate — '+lit.toFixed(0)+' L would be valued at ₹0'}); return; }
    var p=_prevShiftRate(t);
    if(p&&Math.abs(p.rate-cur)>0.009&&!(_splitOn(t)&&Math.abs(v(t+'_rate1')-p.rate)<0.01))
      out.push({level:'warn',machine:T+' price',msg:'₹'+p.rate.toFixed(2)+' last shift ('+p.rec.id+') → ₹'+cur.toFixed(2)+' now. Right? If it changed during the shift, use PRICE CHANGE to split the litres.'});
    var since=p?p.rec.date:'';
    var ld=(typeof fuelLoads!=='undefined'?fuelLoads:[]).filter(function(l){return l.type===T&&(+l.sell>0)&&String(l.date)>=since&&
        String(l.date)<=((document.getElementById('shiftDate')||{}).value||'9999');})
      .sort(function(a,b){return String(b.date).localeCompare(String(a.date));})[0];
    if(ld&&Math.abs(+ld.sell-cur)>0.009)
      out.push({level:'warn',machine:T+' price',msg:'Tanker of '+ld.date+' lists selling price ₹'+(+ld.sell).toFixed(2)+'; this shift uses ₹'+cur.toFixed(2)+'. Was the price revised?'});
  });
  return out;
}
// ── number keypad and Enter → next box ──
function _entryKeypad(root){
  (root||document).querySelectorAll('#page-entry input[type=number]:not([inputmode])').forEach(function(e){ e.setAttribute('inputmode','decimal'); });
}
document.addEventListener('keydown',function(e){
  var t=e.target; if(e.key!=='Enter'||!t||t.tagName!=='INPUT'||!t.closest||!t.closest('#page-entry'))return;
  if(t.type==='checkbox'||t.type==='radio'||t.type==='button'||t.type==='submit')return;
  var list=[].filter.call(document.querySelectorAll('#page-entry input, #page-entry select'),function(x){
    return x.offsetParent!==null&&!x.disabled&&!x.readOnly&&x.type!=='hidden'&&x.type!=='checkbox'&&x.type!=='radio';});
  var i=list.indexOf(t); if(i<0||i===list.length-1)return;
  e.preventDefault(); var n=list[i+1]; n.focus(); if(n.select&&n.tagName==='INPUT')try{n.select();}catch(err){}
});
setTimeout(function(){
  try{ _entryKeypad(); var pe=document.getElementById('page-entry');
    if(pe&&typeof MutationObserver!=='undefined')new MutationObserver(function(){ _entryKeypad(); }).observe(pe,{childList:true,subtree:true});
  }catch(e){}
  try{ _onSlotChanged(); }catch(e){}
},400);
function _entryPristine(){"""),

# ───────── hooks ─────────
("K1 slot change → carry + draft offer",
r"""  if(id!==_saSlotId){ _saSlotId=id; renderShiftAttendance(); }""",
r"""  if(id!==_saSlotId){ _saSlotId=id; renderShiftAttendance();
    setTimeout(function(){ try{ if(typeof _onSlotChanged==='function')_onSlotChanged(); }catch(e){} },0); }   // MF_SHIFT_ENTRY_V1"""),

("K2 entry page shown → carry + draft offer",
r"""  renderShiftAttendance();
}
// After a save: next shift in sequence if it has started (or starts within""",
r"""  renderShiftAttendance();
  try{ if(typeof _onSlotChanged==='function')_onSlotChanged(); }catch(e){}   // MF_SHIFT_ENTRY_V1
}
// After a save: next shift in sequence if it has started (or starts within"""),

("K3 attendance mark → draft",
r"""  _saDrafts[k][staffId]=status;""",
r"""  _saDrafts[k][staffId]=status;
  if(typeof _saveDraftSoon==='function')_saveDraftSoon();   // MF_SHIFT_ENTRY_V1"""),

("K4 save: rates and cash notes with the shift",
r"""            packs:_packExtraReadings(),   // MF_OPENING_SLOT_V1: 20 / 30 ml … by size""",
r"""            packs:_packExtraReadings(),   // MF_OPENING_SLOT_V1: 20 / 30 ml … by size
            // MF_SHIFT_ENTRY_V1: rates (and any price split) and the note count,
            // so the shift can be loaded back for editing exactly as entered.
            rates:_shiftRates(), cash_notes:_cashNotes(),"""),

("K5 save: clear draft and edit mode",
r"""  // Reset all entry fields
  ['msd1_prev','msd1_cur','msd2_prev','msd2_cur',""",
r"""  // MF_SHIFT_ENTRY_V1: saved — its draft and the edit mode end here
  clearTimeout(_draftTimer); _dropDraft(rec.id); _editingShiftId=null;
  { const _db=document.getElementById('draft_banner'); if(_db){_db.style.display='none';_db.dataset.kind='';} }
  // Reset all entry fields
  ['msd1_prev','msd1_cur','msd2_prev','msd2_cur',"""),

("K6 save: reset note counts too",
r"""   'e_tmsd','e_thsd','t_msd_l','t_hsd_l','e_toil','e_items','e_tea','e_chit','e_other','e_handover','notes','shiftTag'
  ].forEach(id=>{const el=document.getElementById(id);if(el)el.value='';});""",
r"""   'e_tmsd','e_thsd','t_msd_l','t_hsd_l','e_toil','e_items','e_tea','e_chit','e_other','e_handover','notes','shiftTag',
   'cash_n500','cash_n200','cash_n100','cash_n50','cash_n20','cash_n10','cash_coins'   // MF_SHIFT_ENTRY_V1
  ].forEach(id=>{const el=document.getElementById(id);if(el)el.value='';});
  { const _cn=document.getElementById('cash_count_note'); if(_cn)_cn.textContent=''; const _cc=document.getElementById('cash_counter'); if(_cc)_cc.style.display='none'; }
  if(typeof shiftSales!=='undefined')shiftSales={};"""),

("K7 save confirmation: price check",
r"""  if(typeof _credNameIssues==='function')Array.prototype.push.apply(_extra, _credNameIssues());   // MF_LEDGER_V1""",
r"""  if(typeof _credNameIssues==='function')Array.prototype.push.apply(_extra, _credNameIssues());   // MF_LEDGER_V1
  try{ if(typeof _rateIssues==='function')Array.prototype.push.apply(_extra, _rateIssues()); }catch(e){}   // MF_SHIFT_ENTRY_V1"""),
]


def main():
    if not os.path.exists(PATH):
        sys.exit(f"✗ {PATH} not found")
    src = open(PATH, encoding="utf-8").read()
    if "MF_LEDGER_SEARCH_V1" not in src:
        sys.exit("✗ Apply patch_ledger_search.py (MF_LEDGER_SEARCH_V1) first. Nothing written.")
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
