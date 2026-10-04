#!/usr/bin/env python3
"""
MF_PRICE_6AM_V1 — price revisions take effect at 6 AM, inside the MORNING shift.

1. SHIFT ENTRY
   • "PRICE CHANGED AT 6 AM" is offered on the Morning shift only.
   • Instead of typing "litres before / litres after", the staff enter the meter
     reading taken at 6 AM for each machine. Litres at the old rate are
     opening → 6 AM, litres at the new rate are 6 AM → closing.
   • The panel closes itself once the shift is saved (it used to stay open on
     the next shift and block it with "Split is 0.000 L …").

2. THE NEW RATE GOES EVERYWHERE
   • Saving the shift makes the new rate the pump rate: the rate box on the
     next shift, the saved rates that sync to every phone, the rate history
     (stamped 6 AM, not the time of saving) and the activity log.
   • A back-filled or corrected OLD shift never overwrites today's rate.

3. PROFIT AFTER A PRICE CHANGE
   • Fuel is now costed at a MOVING average: each load is blended into what is
     actually in the tank when it arrives, and each shift is costed at the
     tank's average when it sold. The old all-time average barely moved after
     a revision, so profit stayed overstated (or understated) by nearly the
     whole revision for months.
   • Stock in the tank at the moment of a revision × the change is reported as
     STOCK GAIN / LOSS: on the shift panel, the shift detail, the P&L cards,
     the CA workings (note 2A), the statement, the Petrol vs Diesel report and
     the dashboard.

Usage:  python3 patch_price_change_6am.py [path/to/index.html]   (idempotent)
"""
import re, os, sys, shutil, subprocess, tempfile

PATH = sys.argv[1] if len(sys.argv) > 1 else "index.html"
SENTINEL = "MF_PRICE_6AM_V1"

# ══════════════════════════════════════════════════════════════════════════
# 1. ENTRY FORM — rate row + 6 AM panel, one copy per fuel
# ══════════════════════════════════════════════════════════════════════════
def entry_html(t, cls):
    return f'''        <div class="frow" id="{t}_rate_row" style="margin-top:8px"><span class="flabel">Rate (₹/L)</span><input type="number"{cls} id="{t}_rate" step="0.01" oninput="queueSaveRates();calc()" onchange="saveRatesNow()"></div>
        <!-- Price Change Toggle — MF_PRICE_6AM_V1: a revision takes effect at 6 AM, inside the MORNING shift -->
        <div id="{t}_pc_row" style="display:flex;align-items:center;gap:8px;margin:8px 0 4px">
          <button id="{t}_price_change_btn" type="button" onclick="togglePriceChange('{t}')"
            style="font-family:'Syne',sans-serif;font-weight:700;font-size:10px;letter-spacing:1px;
                   padding:4px 12px;border:1px solid var(--border2);border-radius:4px;
                   background:transparent;color:var(--muted);cursor:pointer;white-space:nowrap">
            ⚡ PRICE CHANGED AT 6 AM
          </button>
          <span id="{t}_pc_hint" style="font-size:10px;color:var(--muted)">Tap if the rate was revised at 6 AM</span>
        </div>
        <div id="{t}_price_split" style="display:none;background:var(--s3);border-radius:6px;padding:10px;margin-bottom:8px">
          <div style="font-size:10px;letter-spacing:1px;color:var(--diesel);font-family:'Syne',sans-serif;font-weight:700;margin-bottom:8px">⚡ PRICE CHANGED AT 6 AM — ENTER THE READINGS TAKEN AT 6 AM</div>
          <div class="rg" style="margin-bottom:6px">
            <div><label>6 AM READING — MACHINE 1</label><input type="number" id="{t}1_at6" placeholder="0.000" step="0.001" oninput="calc()"></div>
            <div><label>6 AM READING — MACHINE 2</label><input type="number" id="{t}2_at6" placeholder="0.000" step="0.001" oninput="calc()"></div>
          </div>
          <div class="rg">
            <div><label>OLD RATE — TILL 6 AM (₹/L)</label><input type="number" id="{t}_rate1" placeholder="Old rate" step="0.01" oninput="calc()"></div>
            <div><label>NEW RATE — FROM 6 AM (₹/L)</label><input type="number" id="{t}_rate2" placeholder="New rate" step="0.01" oninput="calc()"></div>
          </div>
          <input type="hidden" id="{t}_before_l"><input type="hidden" id="{t}_after_l"><input type="hidden" id="{t}_split_src">
          <div id="{t}_split_lines" style="margin-top:8px;font-family:'JetBrains Mono',monospace;font-size:11px;color:var(--muted);line-height:1.7"></div>
          <div class="field-warn-msg" id="{t}_split_check" style="margin-top:6px;display:none"></div>
          <div id="{t}_split_gain" style="margin-top:6px;font-family:'JetBrains Mono',monospace;font-size:10px;line-height:1.5"></div>
        </div>
'''

def entry_anchors(t, cls):
    start = f'        <div class="frow" style="margin-top:8px"><span class="flabel">Rate (₹/L)</span><input type="number"{cls} id="{t}_rate" step="0.01" oninput="queueSaveRates();calc()" onchange="saveRatesNow()"></div>\n'
    end = f'          <div class="field-warn-msg" id="{t}_split_check" style="margin-top:6px"></div>\n        </div>\n'
    return start, end

# ══════════════════════════════════════════════════════════════════════════
# 2. ENTRY LOGIC — replaces _shiftRates(), adds the 6 AM helpers
# ══════════════════════════════════════════════════════════════════════════
SHIFTRATES_OLD = """function _shiftRates(){
  var sp=function(t){ return _splitOn(t)?{bl:v(t+'_before_l'),r1:v(t+'_rate1'),al:v(t+'_after_l'),r2:v(t+'_rate2')}:null; };
  return {msd:v('msd_rate'),hsd:v('hsd_rate'),msdSplit:sp('msd'),hsdSplit:sp('hsd')};
}
"""
SHIFTRATES_NEW = r"""// ── MF_PRICE_6AM_V1 ────────────────────────────────────────────────────────
// The oil companies revise the price at 6 AM and it lands on every station at
// once, so a revision always falls inside the MORNING shift (6 PM → 9 AM). The
// staff take one more meter reading at 6 AM. Litres at the old rate are
// opening → 6 AM, litres at the new rate are 6 AM → closing; nobody types
// litres any more, so the two halves cannot disagree with the meters.
function _pcN(x,d){ return (+x||0).toLocaleString('en-IN',{minimumFractionDigits:d,maximumFractionDigits:d}); }
// Works the split out from the 6 AM readings and parks it in the hidden
// *_before_l / *_after_l inputs, which is where calc(), the draft and the
// saved record have always read it from.
function _pcSyncType(t){
  var st={on:_splitOn(t),legacy:false,missing:[],bad:[],bl:0,al:0,m:[]};
  if(!st.on)return st;
  var bEl=document.getElementById(t+'_before_l'), aEl=document.getElementById(t+'_after_l'), sEl=document.getElementById(t+'_split_src');
  var raw=[1,2].map(function(n){ var e=document.getElementById(t+n+'_at6'); return e?String(e.value).trim():''; });
  if(!raw[0]&&!raw[1]){
    // Readings cleared again — drop what was worked out from them. Litres with
    // no source marker belong to a shift saved before 6 AM readings were kept.
    if(sEl&&sEl.value==='at6'){ if(bEl)bEl.value=''; if(aEl)aEl.value=''; sEl.value=''; }
    st.bl=Math.max(0,v(t+'_before_l')); st.al=Math.max(0,v(t+'_after_l'));
    st.legacy=(st.bl+st.al)>0;
    return st;
  }
  [1,2].forEach(function(n){
    var p=v(t+n+'_prev'), c=v(t+n+'_cur'), d=Math.max(0,c-p), b=0, a=0;
    if(!raw[n-1]){ if(d>0.0005)st.missing.push(n); a=d; }   // an idle machine needs no 6 AM reading
    else {
      var x=parseFloat(raw[n-1])||0;
      if(x<p-0.0005||(c>0&&x>c+0.0005))st.bad.push(n);
      b=Math.max(0,x-p); a=c>0?Math.max(0,c-x):0;
    }
    st.m.push({n:n,b:b,a:a}); st.bl+=b; st.al+=a;
  });
  st.bl=Math.round(st.bl*1000)/1000; st.al=Math.round(st.al*1000)/1000;
  if(bEl)bEl.value=st.bl; if(aEl)aEl.value=st.al; if(sEl)sEl.value='at6';
  return st;
}
function _pcSync(){ _pcSyncType('msd'); _pcSyncType('hsd'); }
// Book stock at the moment of the revision: what the tank held when the shift
// opened, less what was sold before the change.
function _pcStockAt(type,date,sh,before){
  try{ var b=bookStock(type,date,sh==='night'?'mid':'open').book-(before||0); return (isFinite(b)&&b>0)?b:0; }
  catch(e){ return 0; }
}
function _pcRender(){
  ['msd','hsd'].forEach(function(t){
    if(!_splitOn(t))return;
    var st=_pcSyncType(t), col=t==='msd'?'var(--petrol)':'var(--diesel)';
    var r1=Math.max(0,v(t+'_rate1')), r2=Math.max(0,v(t+'_rate2'));
    var box=document.getElementById(t+'_split_lines');
    if(box){
      var parts=function(k){ return st.m.length?st.m.map(function(x){return 'M'+x.n+' '+_pcN(x[k],3);}).join(' + ')+' = ':''; };
      box.innerHTML=
        '<div>Till 6 AM &nbsp;: '+parts('b')+'<b style="color:var(--text)">'+_pcN(st.bl,3)+' L</b> × ₹'+_pcN(r1,2)+' = <span style="color:'+col+'">'+fmt(_r2(st.bl*r1))+'</span></div>'+
        '<div>From 6 AM : '+parts('a')+'<b style="color:var(--text)">'+_pcN(st.al,3)+' L</b> × ₹'+_pcN(r2,2)+' = <span style="color:'+col+'">'+fmt(_r2(st.al*r2))+'</span></div>'+
        '<div>Total &nbsp; &nbsp; &nbsp;: '+_pcN(st.bl+st.al,3)+' L = <b style="color:'+col+'">'+fmt(_r2(st.bl*r1)+_r2(st.al*r2))+'</b></div>'+
        (st.legacy?'<div style="color:var(--diesel)">These litres were typed by hand when the shift was saved — no 6 AM readings were kept. Enter the readings to work them out again.</div>':'');
    }
    var g=document.getElementById(t+'_split_gain');
    if(g){
      var txt='';
      if(r1>0&&r2>0&&Math.abs(r2-r1)>0.005){
        var stock=_pcStockAt(t.toUpperCase(),(document.getElementById('shiftDate')||{}).value||'',shift,st.bl);
        if(stock>0){
          var gain=stock*(r2-r1);
          txt='Tank at 6 AM ≈ '+_pcN(stock,0)+' L (book stock), bought at the old price. Rate '+(r2>r1?'▲':'▼')+' ₹'+_pcN(Math.abs(r2-r1),2)+
              '/L → stock '+(gain>=0?'gain':'loss')+' ≈ '+fmt(Math.abs(gain))+', '+(gain>=0?'earned':'taken')+' as that fuel is sold.';
          g.style.color=gain>=0?'var(--green)':'var(--red)';
        }
      }
      g.textContent=txt;
    }
  });
}
// The button is offered on the Morning shift only. It stays reachable on a
// Night shift that already carries a split (an old record being corrected) so
// the split can still be taken off.
function _pcGate(){
  ['msd','hsd'].forEach(function(t){
    var on=_splitOn(t), morning=(shift==='morning');
    var row=document.getElementById(t+'_pc_row'), rr=document.getElementById(t+'_rate_row'), h=document.getElementById(t+'_pc_hint');
    if(row)row.style.display=(morning||on)?'flex':'none';
    if(rr)rr.style.display=on?'none':'';   // both rates are in the panel while it is open
    if(h)h.textContent=on?(morning?'Tap again if the rate did not change':'Night shift — a revision belongs on the MORNING shift. Tap to remove.')
                         :'Tap if the rate was revised at 6 AM';
  });
}
function _pcClose(type){
  var splitDiv=document.getElementById(type+'_price_split'), btn=document.getElementById(type+'_price_change_btn');
  if(splitDiv)splitDiv.style.display='none';
  if(btn){ btn.style.background='transparent'; btn.style.color='var(--muted)'; btn.style.borderColor='var(--border2)'; }
  [type+'_before_l',type+'_rate1',type+'_after_l',type+'_rate2',type+'_split_src',type+'1_at6',type+'2_at6'].forEach(function(id){
    var el=document.getElementById(id); if(el)el.value='';
  });
}
// One line per revision in the rate history, stamped at the hour it took
// effect rather than the hour the shift happened to be saved.
function _pcLogHistory(rec,t,s){
  var T=t.toUpperCase(), hist=[];
  try{ hist=JSON.parse(localStorage.getItem('rateHistory')||'[]')||[]; }catch(e){ hist=[]; }
  var dup=hist.some(function(h){ return h.fuel===T&&Math.abs((+h.newRate||0)-s.r2)<0.005&&(h.shiftId===rec.id||h.date===rec.date); });
  if(dup)return false;
  // A corrected shift replaces its own line here; the server log is append-only and keeps both.
  hist=hist.filter(function(h){ return !(h.shiftId===rec.id&&h.fuel===T); });
  var h={id:_newId(),date:rec.date,datetime:_slotDateObj(rec.date,rec.shift==='night'?12:6).toISOString(),fuel:T,
         oldRate:s.r1,newRate:s.r2,changedBy:_currentUser?_currentUser.username:'',shiftId:rec.id};
  hist.push(h);
  hist.sort(function(a,b){ return String(b.datetime||b.date||'').localeCompare(String(a.datetime||a.date||'')); });
  localStorage.setItem('rateHistory',JSON.stringify(hist.slice(0,500)));
  if(_currentUser&&typeof sbSaveRateHistory==='function')sbSaveRateHistory(h).catch(function(){});
  return true;
}
// A saved revision becomes the pump rate everywhere the rate is read: the rate
// box on the next shift, the saved rates that sync to every phone, the history
// and the activity log. A back-filled or corrected OLD shift only writes
// history — it must not put last week's rate back on the pump.
function _pcIsLatest(date,sh,id){
  return !records.some(function(r){
    return r.id!==id&&(String(r.date)>String(date)||(r.date===date&&_shiftRank(r.shift)>_shiftRank(sh)));
  });
}
function _pcCommit(rec,prev){
  var R=rec&&rec.meters&&rec.meters.rates; if(!R)return '';
  var PR=prev&&prev.meters&&prev.meters.rates;
  var later=!_pcIsLatest(rec.date,rec.shift,rec.id);
  var cur={}; try{ cur=JSON.parse(localStorage.getItem('fuelRates')||'{}')||{}; }catch(e){ cur={}; }
  var done=[];
  // An older shift was loaded to correct it: the rate boxes go back to today's pump rate.
  if(later&&typeof loadRates==='function'){ try{ loadRates(); }catch(e){} }
  ['msd','hsd'].forEach(function(t){
    var s=R[t+'Split']; if(!s||!(s.r1>0)||!(s.r2>0)||Math.abs(s.r2-s.r1)<0.005)return;
    // Re-saving a shift whose revision has not changed is not a new revision.
    var ps=PR&&PR[t+'Split'];
    if(!(ps&&Math.abs((+ps.r1||0)-s.r1)<0.005&&Math.abs((+ps.r2||0)-s.r2)<0.005))_pcLogHistory(rec,t,s);
    if(later)return;
    var e=document.getElementById(t+'_rate'); if(e)e.value=s.r2;
    if(Math.abs((parseFloat(cur[t])||0)-s.r2)<0.005)return;
    cur[t]=String(s.r2); done.push(t.toUpperCase()+' ₹'+s.r1.toFixed(2)+' → ₹'+s.r2.toFixed(2));
  });
  if(!done.length)return '';
  ['pack','oil'].forEach(function(k){ if(cur[k]==null){ var e=document.getElementById(k+'_rate'); if(e)cur[k]=e.value; } });
  localStorage.setItem('fuelRates',JSON.stringify(cur));
  if(_currentUser&&typeof sbSaveSettings==='function')sbSaveSettings().catch(console.error);
  if(typeof logActivity==='function')logActivity('rate_change','rates',rec.id,'6 AM revision on '+rec.id+' — '+done.join(', '));
  return ' · rate now '+done.map(function(x){return x.split(' → ')[0].split(' ')[0]+' '+x.split(' → ')[1];}).join(', ');
}
// One shift's fuel sale in words. A revised shift shows both rates, never a
// blended one that was not on the pump at any time.
function _pcSaleTxt(r,t){
  var L=t==='msd'?(r.msdT||0):(r.hsdT||0), V=t==='msd'?(r.msdV||0):(r.hsdV||0);
  var s=r.meters&&r.meters.rates&&r.meters.rates[t+'Split'];
  if(s&&s.r1>0&&s.r2>0&&Math.abs(s.r2-s.r1)>0.005)
    return _pcN(s.bl,3)+' L @ ₹'+_pcN(s.r1,2)+'/L'+(s.at6?' till 6 AM':'')+' + '+_pcN(s.al,3)+' L @ ₹'+_pcN(s.r2,2)+'/L'+(s.at6?' after':'');
  return _pcN(L,3)+' L @ ₹'+_pcN(L>0?V/L:0,2)+'/L';
}
// Shift detail (History → VIEW): both rates, the 6 AM readings, the stock caught.
function _pcDetailHtml(r){
  var R=r&&r.meters&&r.meters.rates; if(!R)return '';
  var out=[];
  [['msd','MSD','var(--petrol)'],['hsd','HSD','var(--diesel)']].forEach(function(p){
    var s=R[p[0]+'Split']; if(!s)return;
    var ev=_priceChanges(p[1]).filter(function(e){return e.id===r.id&&e.at==='6am';})[0];
    var rd=s.at6?[1,2].filter(function(n){return s.at6[n]!=null;}).map(function(n){return 'M'+n+' '+s.at6[n];}).join(', '):'';
    out.push('<div><span style="color:'+p[2]+';font-weight:700">'+p[1]+'</span> '+_pcN(s.bl,3)+' L @ ₹'+_pcN(s.r1,2)+' + '+
      _pcN(s.al,3)+' L @ ₹'+_pcN(s.r2,2)+' = '+fmt(_r2((+s.bl||0)*(+s.r1||0))+_r2((+s.al||0)*(+s.r2||0)))+
      (rd?'<br><span style="color:var(--muted)">6 AM readings: '+rd+'</span>':'')+
      (ev&&ev.stock>0?'<br><span style="color:'+(ev.gain>=0?'var(--green)':'var(--red)')+'">Tank at the change ≈ '+_pcN(ev.stock,0)+
        ' L → stock '+(ev.gain>=0?'gain':'loss')+' ≈ '+fmt(Math.abs(ev.gain))+'</span>':'')+'</div>');
  });
  if(!out.length)return '';
  return '<div style="background:var(--s3);border:1px solid var(--border);border-radius:6px;padding:12px;margin-bottom:10px">'+
    '<div style="font-family:\'Syne\',sans-serif;font-weight:700;font-size:10px;letter-spacing:2px;color:var(--muted);margin-bottom:6px">⚡ PRICE CHANGED DURING THIS SHIFT — OLD RATE + NEW RATE</div>'+
    '<div style="font-family:\'JetBrains Mono\',monospace;font-size:12px;line-height:1.7">'+out.join('')+'</div></div>';
}
function _shiftRates(){
  var sp=function(t){
    if(!_splitOn(t))return null;
    var o={bl:v(t+'_before_l'),r1:v(t+'_rate1'),al:v(t+'_after_l'),r2:v(t+'_rate2')};
    var a={}, any=false;
    [1,2].forEach(function(n){ var x=_vn(t+n+'_at6'); if(x!=null){ a[n]=x; any=true; } });
    if(any){ o.at6=a; o.at=6; }   // MF_PRICE_6AM_V1: the 6 AM readings themselves
    return o;
  };
  var ms=sp('msd'), hs=sp('hsd');
  // The shift's rate is the one it closed at — that is what the next shift opens on.
  return {msd:(ms&&ms.r2>0)?ms.r2:v('msd_rate'),hsd:(hs&&hs.r2>0)?hs.r2:v('hsd_rate'),msdSplit:ms,hsdSplit:hs};
}
"""

DRAFTREC_OLD = """  ['msd','hsd'].forEach(function(t){ var s=R&&R[t+'Split']; if(s){ f[t+'_before_l']=s.bl; f[t+'_rate1']=s.r1; f[t+'_after_l']=s.al; f[t+'_rate2']=s.r2; } });
"""
DRAFTREC_NEW = """  ['msd','hsd'].forEach(function(t){ var s=R&&R[t+'Split']; if(s){ f[t+'_before_l']=s.bl; f[t+'_rate1']=s.r1; f[t+'_after_l']=s.al; f[t+'_rate2']=s.r2;
    if(s.at6){ [1,2].forEach(function(n){ if(s.at6[n]!=null)f[t+n+'_at6']=s.at6[n]; }); f[t+'_split_src']='at6'; } } });   // MF_PRICE_6AM_V1
"""

SLOT_OLD = """function _onSlotChanged(){
  if(_draftRestoring||_editingShiftId)return;
"""
SLOT_NEW = """function _onSlotChanged(){
  if(_draftRestoring||_editingShiftId)return;
  // MF_PRICE_6AM_V1: a revision lives on the Morning shift — never carry an open panel onto a Night shift
  try{ if(shift!=='morning'){ var _pcWas=false; ['msd','hsd'].forEach(function(t){ if(_splitOn(t)){ _pcClose(t); _pcWas=true; } }); if(_pcWas&&typeof calc==='function')calc(); } }catch(e){}
"""

RATEISS_OLD = """      out.push({level:'warn',machine:T+' price',msg:'₹'+p.rate.toFixed(2)+' last shift ('+p.rec.id+') → ₹'+cur.toFixed(2)+' now. Right? If it changed during the shift, use PRICE CHANGE to split the litres.'});
"""
RATEISS_NEW = """      out.push({level:'warn',machine:T+' price',msg:_splitOn(t)   // MF_PRICE_6AM_V1
        ? 'Old rate ₹'+v(t+'_rate1').toFixed(2)+' is not what the last shift ('+p.rec.id+') closed at (₹'+p.rate.toFixed(2)+'). Check it.'
        : '₹'+p.rate.toFixed(2)+' last shift ('+p.rec.id+') → ₹'+cur.toFixed(2)+' now. '+(shift==='morning'
            ? 'If it was revised at 6 AM, tap PRICE CHANGED AT 6 AM and enter the 6 AM readings — otherwise the litres sold before 6 AM are billed at the new rate.'
            : 'A revision takes effect at 6 AM, so it belongs on the MORNING shift. Check the rate.')});
"""
RATEISS2_OLD = """    if(ld&&Math.abs(+ld.sell-cur)>0.009)
      out.push({level:'warn',machine:T+' price',msg:'Tanker of '+ld.date+' lists selling price ₹'+(+ld.sell).toFixed(2)+'; this shift uses ₹'+cur.toFixed(2)+'. Was the price revised?'});
"""
RATEISS2_NEW = """    if(ld&&Math.abs(+ld.sell-cur)>0.009&&!(_splitOn(t)&&Math.abs(+ld.sell-v(t+'_rate1'))<0.01))   // MF_PRICE_6AM_V1: the revision explains it
      out.push({level:'warn',machine:T+' price',msg:'Tanker of '+ld.date+' lists selling price ₹'+(+ld.sell).toFixed(2)+'; this shift uses ₹'+cur.toFixed(2)+'. Was the price revised?'});
    // MF_PRICE_6AM_V1: a revision changes the pump rate everywhere — it is confirmed, never saved in passing
    if(_splitOn(t)&&v(t+'_rate1')>0&&Math.abs(cur-v(t+'_rate1'))>0.005)
      out.push({level:'warn',machine:T+' price',msg:'Revised at 6 AM: ₹'+v(t+'_rate1').toFixed(2)+' → ₹'+cur.toFixed(2)+'. '+
        v(t+'_before_l').toFixed(3)+' L at the old rate, '+v(t+'_after_l').toFixed(3)+' L at the new.'+
        (_pcIsLatest((document.getElementById('shiftDate')||{}).value||'',shift,_curSlotId())?' Saving makes ₹'+cur.toFixed(2)+' the '+T+' pump rate on every phone.':'')});
"""

# Each half is rounded to paise, so the panel, the tally and a hand calculation agree.
ROUND = [
 ("    msdSplitV1 = Math.max(0,v('msd_before_l')) * Math.max(0,v('msd_rate1'));\n", "    msdSplitV1 = _r2(Math.max(0,v('msd_before_l')) * Math.max(0,v('msd_rate1')));   // MF_PRICE_6AM_V1: paise, like a hand calculation\n"),
 ("    msdSplitV2 = Math.max(0,v('msd_after_l'))  * Math.max(0,v('msd_rate2'));\n", "    msdSplitV2 = _r2(Math.max(0,v('msd_after_l'))  * Math.max(0,v('msd_rate2')));\n"),
 ("    hsdSplitV1 = Math.max(0,v('hsd_before_l')) * Math.max(0,v('hsd_rate1'));\n", "    hsdSplitV1 = _r2(Math.max(0,v('hsd_before_l')) * Math.max(0,v('hsd_rate1')));\n"),
 ("    hsdSplitV2 = Math.max(0,v('hsd_after_l'))  * Math.max(0,v('hsd_rate2'));\n", "    hsdSplitV2 = _r2(Math.max(0,v('hsd_after_l'))  * Math.max(0,v('hsd_rate2')));\n"),
]

VALSPLIT_START = "function validateSplit(type,label){\n"
VALSPLIT_END = "    (diff>0?'+':'')+diff.toFixed(3)+' L)'};\n}\n"
VALSPLIT_NEW = r"""function validateSplit(type,label){
  const wrap=document.getElementById(type+'_price_split');
  if(!wrap||wrap.style.display==='none')return null;
  // MF_PRICE_6AM_V1: the litres come from the 6 AM readings, not from typing.
  const st=(typeof _pcSyncType==='function')?_pcSyncType(type):{missing:[],bad:[],legacy:false};
  const meter = type==='msd'
    ? Math.max(0,v('msd1_cur')-v('msd1_prev'))+Math.max(0,v('msd2_cur')-v('msd2_prev'))
    : Math.max(0,v('hsd1_cur')-v('hsd1_prev'))+Math.max(0,v('hsd2_cur')-v('hsd2_prev'));
  const split=Math.max(0,v(type+'_before_l'))+Math.max(0,v(type+'_after_l'));
  const diff=split-meter;
  const el=document.getElementById(type+'_split_check');
  const say=function(txt,kind){
    if(el){
      el.textContent=txt;
      if(!txt){ el.style.cssText='display:none'; }
      else if(kind==='ok'){ el.className=''; el.style.cssText="margin-top:6px;font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--green)"; }
      else { el.className='field-warn-msg'+(kind==='error'?' error':''); el.style.cssText='margin-top:6px'; }
    }
    return (kind==='error'||kind==='warn')?{level:kind,machine:label,msg:txt}:null;
  };
  const r1=v(type+'_rate1'), r2=v(type+'_rate2');
  if(st.bad.length)return say('6 AM reading of Machine '+st.bad.join(' and ')+' must lie between its opening and closing reading','error');
  if(st.missing.length)return say('Enter the 6 AM reading for Machine '+st.missing.join(' and '),'error');
  if(!meter&&!split)return say('',null);
  if(!split)return say('Enter the meter readings taken at 6 AM','error');
  if(!meter)return say('Enter the closing readings above','error');
  if(Math.abs(diff)>0.5)return say((st.legacy
      ? 'Litres typed earlier ('+split.toFixed(3)+' L) do not match the meters ('+meter.toFixed(3)+' L) — enter the 6 AM readings'
      : 'Split is '+split.toFixed(3)+' L but meters show '+meter.toFixed(3)+' L ('+(diff>0?'+':'')+diff.toFixed(3)+' L)')+'. Fix before saving.','error');
  if(!(r1>0)||!(r2>0))return say('Enter the '+(!(r1>0)?'old':'new')+' rate','error');
  if(Math.abs(r1-r2)<0.005)return say('Old and new rate are the same — tap PRICE CHANGED AT 6 AM again if the rate did not change','warn');
  return say('✓ Split matches meters ('+meter.toFixed(3)+' L)','ok');
}
"""

CALC_OLD = """function calc(){
  setShiftId();
  if(typeof validateAllMeters==='function')validateAllMeters();
"""
CALC_NEW = """function calc(){
  setShiftId();
  try{ _pcGate(); _pcSync(); _pcRender(); }catch(e){}   // MF_PRICE_6AM_V1
  if(typeof validateAllMeters==='function')validateAllMeters();
"""

GCV_OLD = """function getCalcVals(){
  const m1=Math.max(0,v('msd1_cur')-v('msd1_prev'));
"""
GCV_NEW = """function getCalcVals(){
  try{ _pcSync(); }catch(e){}   // MF_PRICE_6AM_V1: litres at each rate come from the 6 AM readings
  const m1=Math.max(0,v('msd1_cur')-v('msd1_prev'));
"""

SAVE_A_OLD = """  if(_currentUser)sbSaveRecord(rec).catch(console.error);
  const _att=(typeof _saCommit==='function')?_saCommit(rec.date,rec.shift):null;
"""
SAVE_A_NEW = """  if(_currentUser)sbSaveRecord(rec).catch(console.error);
  // MF_PRICE_6AM_V1: a 6 AM revision becomes the pump rate everywhere
  const _pcMsg=(function(){ try{ return _pcCommit(rec,_prevRec)||''; }catch(e){ console.warn('price change commit:',e); return ''; } })();
  const _att=(typeof _saCommit==='function')?_saCommit(rec.date,rec.shift):null;
"""
SAVE_B_OLD = """  'msd_before_l','msd_rate1','msd_after_l','msd_rate2',
  'hsd_before_l','hsd_rate1','hsd_after_l','hsd_rate2',
"""
SAVE_B_NEW = """  'msd_before_l','msd_rate1','msd_after_l','msd_rate2',
  'hsd_before_l','hsd_rate1','hsd_after_l','hsd_rate2',
  'msd1_at6','msd2_at6','hsd1_at6','hsd2_at6','msd_split_src','hsd_split_src',   // MF_PRICE_6AM_V1
"""
SAVE_C_OLD = """  { const _cn=document.getElementById('cash_count_note'); if(_cn)_cn.textContent=''; const _cc=document.getElementById('cash_counter'); if(_cc)_cc.style.display='none'; }
  if(typeof shiftSales!=='undefined')shiftSales={};
"""
SAVE_C_NEW = """  { const _cn=document.getElementById('cash_count_note'); if(_cn)_cn.textContent=''; const _cc=document.getElementById('cash_counter'); if(_cc)_cc.style.display='none'; }
  // MF_PRICE_6AM_V1: the split belongs to the shift just saved — the next one starts clean
  try{ ['msd','hsd'].forEach(function(t){ if(_splitOn(t))_pcClose(t); }); }catch(e){}
  if(typeof shiftSales!=='undefined')shiftSales={};
"""
SAVE_D_OLD = """  showToast((rec.bal>=0?'✓ Shift saved — cash over '+fmt(rec.bal):'✓ Shift saved — cash short '+fmt(Math.abs(rec.bal)))+_attTxt);
"""
SAVE_D_NEW = """  showToast((rec.bal>=0?'✓ Shift saved — cash over '+fmt(rec.bal):'✓ Shift saved — cash short '+fmt(Math.abs(rec.bal)))+_attTxt+_pcMsg);
"""

TOGGLE_START = "function togglePriceChange(type){\n"
TOGGLE_END = "    if(rate2El && curRate) rate2El.value = curRate;\n  }\n  calc();\n}\n"
TOGGLE_NEW = """function togglePriceChange(type){   // MF_PRICE_6AM_V1
  var splitDiv = document.getElementById(type+'_price_split');
  var btn = document.getElementById(type+'_price_change_btn');
  if(!splitDiv)return;
  if(splitDiv.style.display !== 'none'){
    _pcClose(type);
  } else {
    splitDiv.style.display = 'block';
    if(btn){
      btn.style.background = 'rgba(255,176,32,.15)';
      btn.style.color = 'var(--diesel)';
      btn.style.borderColor = 'var(--diesel)';
    }
    // The old rate is what the shift before closed at. The rate box only holds
    // the NEW rate if somebody has already changed it; otherwise it is the old
    // one and the new rate is still to be typed.
    if(!_draftRestoring){
      var cur = v(type+'_rate'), p = null;
      try{ p = _prevShiftRate(type); }catch(e){}
      var r1 = document.getElementById(type+'_rate1'), r2 = document.getElementById(type+'_rate2');
      if(p && p.rate>0 && cur>0 && Math.abs(p.rate-cur)>0.009){ if(r1)r1.value = p.rate; if(r2)r2.value = cur; }
      else if(r1 && cur>0) r1.value = cur;
      var f = document.getElementById(type+'1_at6');
      if(f){ try{ f.focus(); }catch(e){} }
    }
  }
  calc();
}
"""

DETAIL_OLD = """  html2+='</div>';
  if(r.notes){
    html2+=`<div style="background:var(--s3);border:1px solid var(--border);border-radius:6px;padding:12px">
"""
DETAIL_NEW = """  html2+='</div>';
  try{ html2+=_pcDetailHtml(r); }catch(e){}   // MF_PRICE_6AM_V1
  if(r.notes){
    html2+=`<div style="background:var(--s3);border:1px solid var(--border);border-radius:6px;padding:12px">
"""

# ══════════════════════════════════════════════════════════════════════════
# 3. FUEL COST — moving average, and the revisions the records know about
# ══════════════════════════════════════════════════════════════════════════
WAC_START = "// ── Volume-weighted average cost per litre across all loads of a type up to a\n"
WAC_END = "  return vol>0?cost/vol:0;\n}\n"
WAC_NEW = r"""// ══════════════════════════════════════════════════════════════════
// FUEL COST — MF_PRICE_6AM_V1
// What a litre in the tank cost, at any point in time.
//
// This used to be ONE average over every load ever received. That is fine
// while the price stands still and wrong the moment it moves: after a ₹5
// revision the tankers cost ₹5 more, but an average diluted by months of old
// loads barely shifts, so every litre afterwards showed ₹5 of profit that was
// never earned (and the reverse after a cut).
//
// The tank now carries a MOVING average. A load is blended into whatever is
// actually in the tank when it arrives —
//     (litres in tank × average so far + the load's bill) ÷ litres after
// — and a shift is costed at the average in the tank when it sold. Fuel bought
// before a revision keeps its old cost until it is sold (that is the stock
// gain, or loss), and the cost catches up as the new tankers come in.
// ══════════════════════════════════════════════════════════════════
var _fuelMemo={sig:null};
// Cheap fingerprint of everything the cost depends on, so the timeline is
// rebuilt only when a shift, load, dip or the opening stock actually changes.
function _fuelSig(){
  var dn=function(d){ d=String(d||''); return (+d.slice(0,4)||0)*372+(+d.slice(5,7)||0)*31+(+d.slice(8,10)||0); };
  var n=0,a=0,b=0,c=0;
  records.forEach(function(r){ n++; a+=(r.msdT||0)+3*(r.testMSDL||0); b+=(r.hsdT||0)+3*(r.testHSDL||0); c+=(r.msdV||0)+1.7*(r.hsdV||0); });
  var L=fuelLoads||[], lv=0,lc=0,ld=0;
  L.forEach(function(l){ var k=l.type==='MSD'?1:2;
    lv+=k*_flStockL(l); lc+=k*(parseFloat(l.totalCost!=null?l.totalCost:l.total_cost)||parseFloat(l.buy)||0); ld+=k*dn(l.date); });
  var D=dipReadings||[], dv=0,dd=0;
  D.forEach(function(x){ var k=x.type==='MSD'?1:2; dv+=k*(parseFloat(x.observed)||0); dd+=k*(dn(x.date)+_slotRank(x.slot)); });
  var cf=tankCfg();
  return [n,a,b,c,L.length,lv,lc,ld,D.length,dv,dd,fuelOpeningMSD||0,fuelOpeningHSD||0,
          openingCost('MSD'),openingCost('HSD'),_openingAsOf(),_openingAsOfSlot(),cf.capMSD,cf.capHSD].join('|');
}
function _fuelMemoGet(){
  var s; try{ s=_fuelSig(); }catch(e){ return {}; }   // still booting — nothing to cache yet
  if(_fuelMemo.sig!==s)_fuelMemo={sig:s};
  return _fuelMemo;
}
// The tank's cost timeline: one step per day a load arrived (and one where the
// opening stock was measured), each carrying the average cost AFTER it.
// `memo` is optional everywhere below: a caller that asks several questions in
// a row (the P&L engine does) takes the fingerprint once and passes it along.
function _fuelCostSteps(type,memo){
  memo=memo||_fuelMemoGet(); var key='steps'+type;
  if(memo[key])return memo[key];
  var out={steps:[],base:0,openL:0};
  try{
    var loads=fuelLoads.filter(function(l){return l&&l.type===type;})
      .sort(function(a,b){return String(a.date||'').localeCompare(String(b.date||''));});
    var oc=openingCost(type), ov=(type==='MSD'?fuelOpeningMSD:fuelOpeningHSD)||0;
    var base=(oc>0&&ov>0)?oc:0;
    // With a dated opening the opening cost starts AT that point; without one
    // it is simply where the timeline begins.
    var asOf=_openingAsOf(), opRank=asOf?_slotRank(_openingAsOfSlot()):0;
    var cap=0; try{ var cf=tankCfg(); cap=(type==='MSD'?cf.capMSD:cf.capHSD)||0; }catch(e){}
    var avg=asOf?0:base, pending=!!(asOf&&base>0), i=0;
    out.base=asOf?0:base; out.openL=ov;
    var openStep=function(){ avg=base; pending=false;
      out.steps.push({kind:'opening',date:asOf,rank:opRank,avg:avg,litres:ov,cost:base}); };
    while(i<loads.length){
      var d=String(loads[i].date||''), grp=[];
      while(i<loads.length&&String(loads[i].date||'')===d){ grp.push(loads[i]); i++; }
      if(pending&&_posCmp(asOf,opRank,d,1.5)<0)openStep();
      var gv=grp.reduce(function(s,l){return s+Math.max(0,_flStockL(l));},0);
      // What the books say was in the tank just before the tanker — the same
      // figure the Dip and Fuel Load pages use. It cannot be more than the tank
      // can hold alongside the load, whatever a stale opening figure says.
      var before=0; try{ before=bookStock(type,d,'mid').book; }catch(e){ before=0; }
      if(!isFinite(before)||before<0)before=0;
      if(cap>0)before=Math.min(before,Math.max(0,cap-gv));
      var on=before, rows=[];
      grp.forEach(function(l){
        var v=_flStockL(l), c=parseFloat(l.totalCost!=null?l.totalCost:l.total_cost)||0;
        if(!c&&l.buy)c=(parseFloat(l.buy)||0)*v;   // never basicPrice: that is ₹/KL
        var costed=v>0&&c>0;
        if(costed)avg=(avg>0&&on>0)?(on*avg+c)/(on+v):c/v;
        if(v>0)on+=v;
        rows.push({l:l,v:v,c:c,costed:costed});
      });
      out.steps.push({kind:'load',date:d,rank:1.5,avg:avg,before:before,after:on,rows:rows});
    }
    if(pending)openStep();
  }catch(e){ return {steps:[],base:0,openL:0}; }
  memo[key]=out;
  return out;
}
// Cost per litre of the fuel a given shift sold. 0 = nothing is known yet.
function _fuelCostOf(S,date,sh){
  var r=_shiftRank(sh), a=S.steps;
  for(var i=a.length-1;i>=0;i--){ if(a[i].avg>0&&_posCmp(a[i].date,a[i].rank,date,r)<0)return a[i].avg; }
  return S.base;
}
function _fuelCostAt(type,date,sh,memo){ return _fuelCostOf(_fuelCostSteps(type,memo),date,sh); }
// ── Average cost per litre of the stock in the tank at the END of a date (or
// now). Every caller that values stock — a dip shortage, the tank, the margin
// check on the dashboard — reads it from here.
function _fuelWAC(type, upto, memo){
  var S=_fuelCostSteps(type,memo), a=S.steps;
  for(var i=a.length-1;i>=0;i--){ if(a[i].avg>0&&(!upto||String(a[i].date)<=upto))return a[i].avg; }
  return S.base;
}
// Litres a shift really sold, by fuel: metered, less testing and the
// hydrometer draw that went back in the tank. Same rule as _plCore.
function _recSoldL(r){
  var m=(r.msdT||0)-(r.testMSDL||0), h=(r.hsdT||0)-(r.testHSDL||0);
  var hv=_recHydro(r);
  if(hv>0){
    var mv=r.msdV||0, dv=r.hsdV||0, tot=mv+dv;
    if(tot>0){
      var mR=(r.msdT>0)?(mv/r.msdT):0, dR=(r.hsdT>0)?(dv/r.hsdT):0;
      if(mR>0)m-=(hv*(mv/tot))/mR;
      if(dR>0)h-=(hv*(dv/tot))/dR;
    }
  }
  return {msd:m,hsd:h};
}
// ── PRICE REVISIONS the records know about, oldest first, with the stock they
// caught. A revision entered with 6 AM readings sits inside its shift; one
// that only shows up as a different rate on the next shift sits at that
// shift's start. gain = stock in the tank at that moment × the change: bought
// at the old price, sold at the new one.
function _priceChanges(type,memo){
  memo=memo||_fuelMemoGet(); var key='pc'+type;
  if(memo[key])return memo[key];
  var t=type.toLowerCase(), out=[], prev=null;
  try{
    records.slice().sort(_wkSortAsc).forEach(function(r){
      var L=type==='MSD'?(r.msdT||0):(r.hsdT||0), V=type==='MSD'?(r.msdV||0):(r.hsdV||0);
      if(!(L>0&&V>0))return;
      var R=r.meters&&r.meters.rates, s=R&&R[t+'Split'], open, close;
      if(s&&s.r1>0&&s.r2>0){ open=+s.r1; close=+s.r2; }
      else open=close=Math.round(((R&&R[t]>0)?+R[t]:V/L)*100)/100;
      if(prev!=null&&Math.abs(open-prev)>0.005)
        out.push({type:type,id:r.id,date:r.date,shift:r.shift,at:'start',from:prev,to:open,before:0});
      if(Math.abs(close-open)>0.005)
        out.push({type:type,id:r.id,date:r.date,shift:r.shift,at:'6am',from:open,to:close,before:Math.max(0,+s.bl||0)});
      prev=close;
    });
    out.forEach(function(e){
      e.stock=_pcStockAt(type,e.date,e.shift,e.before);
      e.delta=e.to-e.from; e.gain=e.stock*e.delta;
    });
  }catch(e){ return []; }
  memo[key]=out;
  return out;
}
"""

PLCMT_OLD = """// `to` is the period END and it matters: costing litres at a weighted average
// that includes tankers bought after the period made last week's profit move
// every time a load was recorded.
"""
PLCMT_NEW = """// MF_PRICE_6AM_V1: every shift is costed at the average cost of the fuel that
// was in the tank when it sold (_fuelCostAt). A tanker therefore never changes
// the cost of fuel sold before it arrived, and a price revision shows up as a
// wider or thinner margin on the stock that was held through it — which is
// what actually happened — instead of as a permanent error in the average.
// `to` is the period END; it is only the fallback for shifts older than any
// cost on record.
"""

PLCOGS_OLD = """  // Litres sold × weighted-average landed cost per litre AS AT THE PERIOD END.
  const wacMSD = _fuelWAC('MSD', to), wacHSD = _fuelWAC('HSD', to);
  const soldMSDL = Math.max(0, totalMSDL - testMSDL - hydMSDL);
  const soldHSDL = Math.max(0, totalHSDL - testHSDL - hydHSDL);
  const cogsFuel = soldMSDL*wacMSD + soldHSDL*wacHSD;
"""
PLCOGS_NEW = """  // MF_PRICE_6AM_V1 — each shift's litres × the average landed cost of the fuel
  // in the tank when they were sold. wacMSD / wacHSD are what that works out
  // to per litre over the period, so litres × rate still equals the cost.
  const soldMSDL = Math.max(0, totalMSDL - testMSDL - hydMSDL);
  const soldHSDL = Math.max(0, totalHSDL - testHSDL - hydHSDL);
  const _fm=_fuelMemoGet();
  const _csM=_fuelCostSteps('MSD',_fm), _csH=_fuelCostSteps('HSD',_fm);
  const _endM=_fuelWAC('MSD', to, _fm), _endH=_fuelWAC('HSD', to, _fm);
  let _cgM=0, _cgH=0;
  recs.forEach(function(r){
    const q=_recSoldL(r);
    _cgM+=q.msd*(_fuelCostOf(_csM,r.date,r.shift)||_endM);
    _cgH+=q.hsd*(_fuelCostOf(_csH,r.date,r.shift)||_endH);
  });
  const wacMSD = soldMSDL>0 ? Math.max(0,_cgM)/soldMSDL : _endM;
  const wacHSD = soldHSDL>0 ? Math.max(0,_cgH)/soldHSDL : _endH;
  const cogsFuel = soldMSDL*wacMSD + soldHSDL*wacHSD;
"""

PLRET_A_OLD = """                             testHydro;   // MF_REPORTS_V1: its litres are already out of cost, so its rupees come out of sales

  return {
"""
PLRET_A_NEW = """                             testHydro;   // MF_REPORTS_V1: its litres are already out of cost, so its rupees come out of sales
  // MF_PRICE_6AM_V1: revisions in the window and the stock they caught. A memo,
  // not a line in the sum — the gain is already inside gross profit, because
  // that stock is costed at what it was bought for and sold at the new rate.
  const priceChanges = _priceChanges('MSD',_fm).concat(_priceChanges('HSD',_fm))
    .filter(e=>(!from||e.date>=from)&&(!to||e.date<=to))
    .sort((a,b)=>String(a.date).localeCompare(String(b.date)));
  const stockGain = priceChanges.reduce((s,e)=>s+e.gain,0);

  return {
"""
PLRET_B_OLD = """    realizedFuelProfit:realizedFuelProfit, shifts:recs.length
  };
"""
PLRET_B_NEW = """    realizedFuelProfit:realizedFuelProfit, shifts:recs.length,
    priceChanges:priceChanges, stockGain:stockGain
  };
"""

AUDIT_OLD = """  var below=[];
  recs.forEach(function(r){
    if(r.msdT>0&&P.wacMSD>0&&(r.msdV/r.msdT)<P.wacMSD-0.005)below.push(r.id+' MSD @ '+fmt(r.msdV/r.msdT));
    if(r.hsdT>0&&P.wacHSD>0&&(r.hsdV/r.hsdT)<P.wacHSD-0.005)below.push(r.id+' HSD @ '+fmt(r.hsdV/r.hsdT));
  });
  if(below.length)add('bad','Sold below cost on '+below.length+' shift-fuel'+(below.length!==1?'s':''),
    below.slice(0,6).join(', ')+'. Landed cost: MSD '+fmt(P.wacMSD)+'/L, HSD '+fmt(P.wacHSD)+'/L. Either the rate was entered wrong or a load\\'s cost is wrong.');
"""
AUDIT_NEW = """  var below=[];
  // MF_PRICE_6AM_V1: against the cost of the fuel that shift actually sold
  var _aM=_fuelCostSteps('MSD'), _aH=_fuelCostSteps('HSD');
  recs.forEach(function(r){
    var cM=_fuelCostOf(_aM,r.date,r.shift)||P.wacMSD, cH=_fuelCostOf(_aH,r.date,r.shift)||P.wacHSD;
    if(r.msdT>0&&cM>0&&(r.msdV/r.msdT)<cM-0.005)below.push(r.id+' MSD @ '+fmt(r.msdV/r.msdT)+' (cost '+fmt(cM)+')');
    if(r.hsdT>0&&cH>0&&(r.hsdV/r.hsdT)<cH-0.005)below.push(r.id+' HSD @ '+fmt(r.hsdV/r.hsdT)+' (cost '+fmt(cH)+')');
  });
  if(below.length)add('bad','Sold below cost on '+below.length+' shift-fuel'+(below.length!==1?'s':''),
    below.slice(0,6).join(', ')+'. Either the rate was entered wrong, a load\\'s cost is wrong, or the price was cut while dearer stock was still in the tank (see note 2A).');
"""

# ── CA workings, note 2A ──────────────────────────────────────────────────
WK_START = "  var wacTable=function(type){\n"
WK_END = "    tie(_wkTie(wM.wac,P.wacMSD)&&_wkTie(wH.wac,P.wacHSD),'Landed cost tables reproduce the engine\\'s rates (MSD '+fmt(wM.wac)+', HSD '+fmt(wH.wac)+')');\n"
WK_NEW = r"""  // MF_PRICE_6AM_V1: the tank's moving average, load by load
  var wacTable=function(type){
    var S=_fuelCostSteps(type), rows=[], nl=0;
    if(S.base>0)rows.push(tr(['—','Opening stock','—',_wkL(S.openL),fmt(S.base),'—','<b>'+fmt(S.base)+'</b>']));
    else if(S.openL>0&&!S.steps.some(function(s){return s.kind==='opening';}))
      rows.push(tr(['—','Opening stock','—',_wkL(S.openL),'<span style="color:var(--diesel)">no cost set — takes the cost of the loads that follow</span>','—','—']));
    S.steps.forEach(function(s){
      if(to&&String(s.date)>to)return;
      if(s.kind==='opening'){ rows.push(tr([s.date,'Opening stock (measured)','—',_wkL(s.litres),fmt(s.cost),'—','<b>'+fmt(s.avg)+'</b>'])); return; }
      s.rows.forEach(function(x,i){ nl++;
        rows.push(tr([s.date,_esc(x.l.inv||'—'),_esc(x.l.supplier||'—'),_wkL(x.v),
          x.costed?fmt(x.c/x.v):'<span style="color:var(--diesel)">no cost — average unchanged</span>',
          i===0?_wkL(s.before):'',
          i===s.rows.length-1?(s.avg>0?'<b>'+fmt(s.avg)+'</b>':'—'):'']));
      });
    });
    if(!rows.length)rows.push(tr(['—','No load or opening cost on record up to this date','','','','','—']));
    return {html:tbl(['DATE','INVOICE','SUPPLIER','LITRES IN','₹ / L (landed)','IN TANK BEFORE','TANK AVERAGE AFTER'],rows),loads:nl};
  };
  // Re-derived from the shifts: consecutive shifts sold at the same tank cost.
  var costBands=function(type){
    var k=type==='MSD'?'msd':'hsd', S=_fuelCostSteps(type), endC=_fuelWAC(type,to), out=[], cur=null, tot=0;
    recs.slice().sort(_wkSortAsc).forEach(function(r){
      var q=_recSoldL(r)[k]; if(Math.abs(q)<0.0005)return;
      var c=_fuelCostOf(S,r.date,r.shift)||endC;
      if(cur&&Math.abs(cur.c-c)<0.00005){ cur.to=r; cur.L+=q; cur.n++; }
      else { cur={from:r,to:r,c:c,L:q,n:1}; out.push(cur); }
      tot+=q*c;
    });
    var lb=function(r){ return r.date+' '+(r.shift==='night'?'N':'M'); };
    return {tot:tot,rows:out.map(function(b){
      return tr([type,lb(b.from)+(b.n>1?' → '+lb(b.to):''),_wkN(b.n),_wkL(b.L),fmt(b.c)+'/L',fmt(b.L*b.c)]); })};
  };
  var wM=wacTable('MSD'), wH=wacTable('HSD'), bM=costBands('MSD'), bH=costBands('HSD');
  var pcs=P.priceChanges||[];
  var pcRows=pcs.map(function(e){
    return tr([e.date+(e.at==='6am'?' · 6 AM':' · start of '+e.shift+' shift'),e.type,fmt(e.from),fmt(e.to),
      (e.delta>=0?'+':'−')+fmt(Math.abs(e.delta)),_wkL(e.stock),_wkM(e.gain)]);
  });
  if(pcs.length)pcRows.push(tr(['<b>Stock gain / (loss) in the period</b>','','','','','','<b>'+_wkM(P.stockGain)+'</b>'],'wk-tot'));
  var n2a=tbl(['','MSD','HSD'],[
      tr(['Metered out (Note 1)',_wkL(P.totalMSDL),_wkL(P.totalHSDL)]),
      tr(['less testing returned',_wkM(-P.testMSDL).replace('₹','')+' L',_wkM(-P.testHSDL).replace('₹','')+' L'],'wk-sub'),
      tr(['less hydrometer returned',_wkM(-P.hydMSDL).replace('₹','')+' L',_wkM(-P.hydHSDL).replace('₹','')+' L'],'wk-sub'),
      tr(['<b>Litres actually sold</b>','<b>'+_wkL(P.soldMSDL)+'</b>','<b>'+_wkL(P.soldHSDL)+'</b>'],'wk-tot'),
      tr(['× Average landed cost of those litres (2A-iii)',fmt(P.wacMSD)+'/L',fmt(P.wacHSD)+'/L']),
      tr(['<b>Cost of fuel sold</b>','<b>'+fmt(P.soldMSDL*P.wacMSD)+'</b>','<b>'+fmt(P.soldHSDL*P.wacHSD)+'</b>'],'wk-tot'),
      tr(['Average selling rate',fmt(rateM)+'/L',fmt(rateH)+'/L'],'wk-sub'),
      tr(['<b>Margin per litre</b>','<b>'+fmt(rateM-P.wacMSD)+'</b>','<b>'+fmt(rateH-P.wacHSD)+'</b>'],'wk-sub')
    ])+
    '<div class="wk-p"><b>Method:</b> weighted average cost on a perpetual (moving) basis, permitted under AS-2. The tank carries one average cost per litre. Each load is blended into it — (litres in the tank × the average so far + the load\'s bill incl. VAT and lorry hire) ÷ litres after the load — and every litre sold is costed at the average in the tank when it was sold. A load therefore changes the cost only of fuel sold after it arrived, and stock bought before a price revision keeps its old cost until it is sold.</div>'+
    '<details class="wk-sched"><summary>2A-i — MSD tank cost, load by load ('+wM.loads+' load'+(wM.loads!==1?'s':'')+')</summary>'+wM.html+'</details>'+
    '<details class="wk-sched"><summary>2A-ii — HSD tank cost, load by load ('+wH.loads+' load'+(wH.loads!==1?'s':'')+')</summary>'+wH.html+'</details>'+
    '<details class="wk-sched"><summary>2A-iii — cost of the litres sold, by tank cost</summary>'+
      tbl(['FUEL','SHIFTS','NO.','LITRES SOLD','TANK COST','₹'],bM.rows.concat(bH.rows))+'</details>'+
    (pcs.length?'<details class="wk-sched" open><summary>2A-iv — price revisions and the stock held ('+pcs.length+')</summary>'+
      tbl(['WHEN','FUEL','OLD RATE','NEW RATE','CHANGE','IN TANK','GAIN / (LOSS) ₹'],pcRows)+
      '<div class="wk-p">Stock in the tank when the rate changed × the change. This is <b>not</b> an extra line in the statement: it is already inside gross profit, because that stock is costed at what it was bought for and sold at the new rate. It is earned (or lost) as the stock sells, so part of it can fall in the days after this period.</div></details>':'')+
    tie(_wkTie(P.soldMSDL*P.wacMSD+P.soldHSDL*P.wacHSD,P.cogsFuel),'Fuel cost '+fmt(P.soldMSDL*P.wacMSD+P.soldHSDL*P.wacHSD)+' agrees with the statement')+
    tie(_wkTie(bM.tot+bH.tot,P.cogsFuel),'Schedule 2A-iii total '+fmt(bM.tot+bH.tot)+(_wkTie(bM.tot+bH.tot,P.cogsFuel)?' agrees with ':' does NOT agree with ')+'the fuel cost in the statement');
"""

WKBASIS_OLD = "Cost of fuel = litres sold × weighted average landed cost. Every figure below"
WKBASIS_NEW = "Cost of fuel = litres sold × the average landed cost of the fuel in the tank when it was sold. Every figure below"

STMT_OLD = """'<p class="st-note">Revenue is recognised when fuel leaves the pump. Fuel is costed at the weighted average landed cost of all stock received up to '+_sD(to)+'. The full working of every figure is on Reports → Show workings.</p>');"""
STMT_NEW = """'<p class="st-note">Revenue is recognised when fuel leaves the pump. Fuel is costed at the average landed cost of the stock in the tank when it was sold (moving average).'+
      ((P.priceChanges&&P.priceChanges.length)?' '+P.priceChanges.length+' price revision'+(P.priceChanges.length!==1?'s':'')+' in the period changed the value of the stock in the tank by ₹'+_sN(Math.abs(P.stockGain))+' ('+(P.stockGain>=0?'gain':'loss')+'); it comes into gross profit as that stock is sold.':'')+   // MF_PRICE_6AM_V1
      ' The full working of every figure is on Reports → Show workings.</p>');"""

CARD_OLD = """       : `${soldMSDL.toFixed(0)}L MSD @ ${fmt(wacMSD)}/L + ${soldHSDL.toFixed(0)}L HSD @ ${fmt(wacHSD)}/L landed cost`},
  ];
"""
CARD_NEW = """       : `${soldMSDL.toFixed(0)}L MSD @ ${fmt(wacMSD)}/L + ${soldHSDL.toFixed(0)}L HSD @ ${fmt(wacHSD)}/L landed cost`},
    // MF_PRICE_6AM_V1: what a revision did to the stock in the tank
    ...((_pl.priceChanges&&_pl.priceChanges.length)?[
      {cls:_pl.stockGain>=0?'margin':'opex', lbl:_pl.stockGain>=0?'Stock Gain — Price Rise':'Stock Loss — Price Cut',
       val:(_pl.stockGain>=0?'+':'−')+fmt(Math.abs(_pl.stockGain)),
       sub:_pl.priceChanges.slice(-3).map(e=>`${e.type} ₹${e.from.toFixed(2)} → ₹${e.to.toFixed(2)} on ${e.date.slice(8)}/${e.date.slice(5,7)} × ${Math.round(e.stock).toLocaleString('en-IN')} L in tank`).join(' • ')+
           (_pl.priceChanges.length>3?` • +${_pl.priceChanges.length-3} more in the workings`:'')+
           ' — not added on top: it reaches gross profit as that stock is sold over the following days'},
    ]:[]),
  ];
"""

RVROW_OLD = "Each row costs its fuel at the purchase cost on its own last day; the total is costed at the period end, so the rows can add up a few rupees differently.',"
RVROW_NEW = "Each shift is costed at the average cost of the fuel in the tank when it was sold.',"

RVFUEL_A_OLD = """Landed cost is the weighted purchase cost as at '+(to?_rvDmy(to):'today')+'.'+"""
RVFUEL_A_NEW = """Landed cost is the average cost of the fuel in the tank when each litre was sold.'+"""
RVFUEL_B_OLD = """         wac[s.k]>0?s.rate-wac[s.k]:null,s.L,s.n]; }), empty:'No fuel sold in this period.'}}]};
"""
RVFUEL_B_NEW = """         wac[s.k]>0?s.rate-wac[s.k]:null,s.L,s.n]; }), empty:'No fuel sold in this period.'}},
    // MF_PRICE_6AM_V1
    {key:'fuel_revisions', h:'PRICE REVISIONS — STOCK GAIN / LOSS',
     note:'Stock in the tank when the rate changed × the change. That fuel was bought at the old price and sells at the new one, so a rise is a gain and a cut is a loss. It is already inside the margin above, earned as the stock sells.',
     tbl:{cols:[{h:'Fuel',t:'t'},{h:'Date',t:'t'},{h:'When',t:'t'},{h:'Old rate',t:'m2'},{h:'New rate',t:'m2'},{h:'Change',t:'m2'},{h:'In tank',t:'L'},{h:'Gain / loss',t:'m'}],
       rows:(P.priceChanges||[]).slice().reverse().map(function(e){ return [e.type==='MSD'?'Petrol':'Diesel',{v:e.date,s:_rvDmy(e.date)},
         e.at==='6am'?'6 AM':'start of '+e.shift+' shift',e.from,e.to,e.delta,e.stock,{v:e.gain,c:e.gain>=0?'var(--green)':'var(--red)'}]; }),
       foot:(P.priceChanges&&P.priceChanges.length)?['Total','','','','','','',P.stockGain]:null,
       empty:'No price revision in this period.'}}]};
"""

STMTSALE = [
 ("      sub:_sL(r.msdT,3)+' L @ ₹'+_sN(r.msdT>0?r.msdV/r.msdT:0)+'/L'+([mc('msd1')", "      sub:_pcSaleTxt(r,'msd')+([mc('msd1')"),
 ("      sub:_sL(r.hsdT,3)+' L @ ₹'+_sN(r.hsdT>0?r.hsdV/r.hsdT:0)+'/L'+([mc('hsd1')", "      sub:_pcSaleTxt(r,'hsd')+([mc('hsd1')"),
]

RVSEG_OLD = """      var rate=Math.round(V/T*100)/100;
      if(seg&&Math.abs(seg.rate-rate)<0.005){ seg.to=r.date; seg.L+=T; seg.n++; }
      else { seg={k:k,from:r.date,to:r.date,rate:rate,L:T,n:1}; segs.push(seg); }
"""
RVSEG_NEW = """      // MF_PRICE_6AM_V1: a revised shift counts at each of its two rates, not at a blend
      var sp=r.meters&&r.meters.rates&&r.meters.rates[k.toLowerCase()+'Split'];
      var parts=(sp&&sp.r1>0&&sp.r2>0&&Math.abs(sp.r2-sp.r1)>0.005)?[[+sp.r1,+sp.bl||0],[+sp.r2,+sp.al||0]]:[[Math.round(V/T*100)/100,T]];
      parts.forEach(function(p,i){
        if(!(p[1]>0))return;
        if(seg&&Math.abs(seg.rate-p[0])<0.005){ seg.to=r.date; seg.L+=p[1]; if(i===0)seg.n++; }
        else { seg={k:k,from:r.date,to:r.date,rate:p[0],L:p[1],n:1}; segs.push(seg); }
      });
"""
RVSEGNOTE_OLD = "note:'Shifts in a row at the same average rate. A shift with a price change in the middle shows its own blended rate. Margin / L uses the period’s landed cost.',"
RVSEGNOTE_NEW = "note:'Shifts in a row at the same pump rate. A shift revised at 6 AM is counted at each of its two rates. Margin / L uses the period’s landed cost.',"

# ── dashboard ─────────────────────────────────────────────────────────────
DASH_A_OLD = """            (miss.length?'<br><span style="color:'+AMBER+'">'+miss.length+' shift not saved — incomplete</span>':'')+
            '<br><span style="color:var(--muted)">tap to open in Reports</span>')+'</div>';
"""
DASH_A_NEW = """            (miss.length?'<br><span style="color:'+AMBER+'">'+miss.length+' shift not saved — incomplete</span>':'')+
            ((Pd.priceChanges||[]).length?'<br><span style="color:'+(Pd.stockGain>=0?GREEN:RED)+'">⚡ '+   // MF_PRICE_6AM_V1
              Pd.priceChanges.map(e=>e.type+' '+(e.delta>=0?'▲':'▼')+' ₹'+Math.abs(e.delta).toFixed(2)).join(' · ')+
              ' — stock '+(Pd.stockGain>=0?'gain ':'loss ')+k(Math.abs(Pd.stockGain))+', '+(Pd.stockGain>=0?'earned':'taken')+' as it sells</span>':'')+
            '<br><span style="color:var(--muted)">tap to open in Reports</span>')+'</div>';
"""
DASH_B_OLD = """      const w=_fuelWAC(f[0],todayIso); if(!(w>0)||!(f[1]>0))return; const m=f[1]-w;
      if(m<1||m>8)issues.push({"""
DASH_B_NEW = """      // MF_PRICE_6AM_V1: a price cut costs money on the stock held through it,
      // and a recent revision explains a margin that is suddenly wide or thin.
      const rv=_priceChanges(f[0]).filter(e=>e.date>=addD(todayIso,-10)), lastRv=rv[rv.length-1];
      const rvNet=rv.reduce((s,e)=>s+e.gain,0);
      if(rvNet<-1)issues.push({lvl:'amber',icon:'⚡',title:f[0]+' price cut — stock loss ≈ '+R0(-rvNet),
        detail:rv.filter(e=>e.gain<0).map(e=>Lfmt(e.stock)+' in the tank on '+dm(e.date)+' bought at the old price, rate ▼ ₹'+Math.abs(e.delta).toFixed(2)).join(' · ')+
          '. Run the tank low before an expected cut.',page:'report'});
      const w=_fuelWAC(f[0],todayIso); if(!(w>0)||!(f[1]>0))return; const m=f[1]-w;
      if(lastRv&&((m>8&&lastRv.delta>0)||(m<1&&lastRv.delta<0)))return;
      if(m<1||m>8)issues.push({"""


def between(src, start, end, name):
    a = src.find(start)
    if a < 0 or src.count(start) != 1:
        sys.exit(f"✗ {name}: start anchor not found exactly once — nothing written")
    b = src.find(end, a)
    if b < 0:
        sys.exit(f"✗ {name}: end anchor not found — nothing written")
    return a, b + len(end)


def main():
    src = open(PATH, encoding="utf-8").read()
    if SENTINEL in src:
        print(f"Nothing to do — {SENTINEL} already applied."); return
    out = src

    # block replacements (start … end)
    blocks = [
        ("entry form: MSD rate row + 6 AM panel", *entry_anchors("msd", ""), entry_html("msd", "")),
        ("entry form: HSD rate row + 6 AM panel", *entry_anchors("hsd", ' class="d"'), entry_html("hsd", ' class="d"')),
        ("validateSplit: checks the 6 AM readings", VALSPLIT_START, VALSPLIT_END, VALSPLIT_NEW),
        ("togglePriceChange: old rate from the last shift", TOGGLE_START, TOGGLE_END, TOGGLE_NEW),
        ("fuel cost: moving average + price revisions", WAC_START, WAC_END, WAC_NEW),
        ("CA workings note 2A: tank cost, cost bands, revisions", WK_START, WK_END, WK_NEW),
    ]
    for name, start, end, new in blocks:
        a, b = between(out, start, end, name)
        out = out[:a] + new + out[b:]
        print("  ✓", name)

    # exact-string replacements
    hunks = [
        ("_shiftRates + 6 AM helpers", SHIFTRATES_OLD, SHIFTRATES_NEW),
        ("edit a saved shift: 6 AM readings come back", DRAFTREC_OLD, DRAFTREC_NEW),
        ("slot change: no open panel on a Night shift", SLOT_OLD, SLOT_NEW),
        ("rate check on save: 6 AM wording", RATEISS_OLD, RATEISS_NEW),
        ("rate check on save: revision is confirmed", RATEISS2_OLD, RATEISS2_NEW),
        ("calc(): split from the 6 AM readings", CALC_OLD, CALC_NEW),
        ("getCalcVals(): split from the 6 AM readings", GCV_OLD, GCV_NEW),
        ("save: new rate becomes the pump rate", SAVE_A_OLD, SAVE_A_NEW),
        ("save: clear the 6 AM fields", SAVE_B_OLD, SAVE_B_NEW),
        ("save: close the panel", SAVE_C_OLD, SAVE_C_NEW),
        ("save: toast names the new rate", SAVE_D_OLD, SAVE_D_NEW),
        ("shift detail: both rates and the stock gain", DETAIL_OLD, DETAIL_NEW),
        ("P&L engine: comment", PLCMT_OLD, PLCMT_NEW),
        ("P&L engine: cost each shift at its own tank cost", PLCOGS_OLD, PLCOGS_NEW),
        ("P&L engine: price revisions in the period", PLRET_A_OLD, PLRET_A_NEW),
        ("P&L engine: return them", PLRET_B_OLD, PLRET_B_NEW),
        ("audit check: sold below cost, per shift", AUDIT_OLD, AUDIT_NEW),
        ("CA workings: basis line", WKBASIS_OLD, WKBASIS_NEW),
        ("statement: costing note", STMT_OLD, STMT_NEW),
        ("P&L cards: stock gain / loss", CARD_OLD, CARD_NEW),
        ("report rows: costing note", RVROW_OLD, RVROW_NEW),
        ("Petrol vs Diesel: costing note", RVFUEL_A_OLD, RVFUEL_A_NEW),
        ("Petrol vs Diesel: price revisions table", RVFUEL_B_OLD, RVFUEL_B_NEW),
        ("Petrol vs Diesel: rate periods split a revised shift", RVSEG_OLD, RVSEG_NEW),
        ("Petrol vs Diesel: rate periods note", RVSEGNOTE_OLD, RVSEGNOTE_NEW),
        ("dashboard: day tile shows a revision", DASH_A_OLD, DASH_A_NEW),
        ("dashboard: margin check understands a revision", DASH_B_OLD, DASH_B_NEW),
    ]
    for name, old, new in hunks:
        if out.count(old) != 1:
            sys.exit(f"✗ {name}: anchor found {out.count(old)}× (need exactly 1) — nothing written")
        out = out.replace(old, new)
        print("  ✓", name)

    for old, new in STMTSALE:
        if out.count(old) != 1:
            sys.exit(f"✗ statement sale line: anchor found {out.count(old)}× (need exactly 1) — nothing written")
        out = out.replace(old, new)
    print("  ✓ statement: a revised shift shows both rates")

    # the same line lives in calc() and getCalcVals()
    for old, new in ROUND:
        if out.count(old) != 2:
            sys.exit(f"✗ paise rounding: anchor found {out.count(old)}× (need exactly 2) — nothing written")
        out = out.replace(old, new)
    print("  ✓ split halves rounded to paise (calc + getCalcVals)")

    # post-state: nothing that must survive was lost
    for must in ("initMultiDeviceSync", "stopAllSync", "function _plCore(", "function bookStock(",
                 'id="msd_before_l"', 'id="hsd_after_l"', 'id="msd1_at6"', 'id="hsd2_at6"',
                 "function _fuelWAC(", "function _priceChanges(", "function _pcCommit("):
        if must not in out:
            sys.exit(f"✗ post-check: '{must}' missing after patch — nothing written")

    scripts = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", out, flags=re.S | re.I)
    with tempfile.TemporaryDirectory() as td:
        for i, js in enumerate(scripts):
            p = os.path.join(td, f"s{i}.js"); open(p, "w", encoding="utf-8").write(js)
            r = subprocess.run(["node", "--check", p], capture_output=True, text=True)
            if r.returncode:
                sys.exit(f"✗ node --check failed on script #{i}:\n{r.stderr}\nNothing written.")
    shutil.copyfile(PATH, PATH + ".bak")
    open(PATH, "w", encoding="utf-8").write(out)
    print(f"✓ {SENTINEL} applied; node --check passed on {len(scripts)} script(s); backup {PATH}.bak")


if __name__ == "__main__":
    main()
