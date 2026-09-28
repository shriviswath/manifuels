#!/usr/bin/env python3
"""
MF_DIPORDER_V1 — Dip variation and Order Advisor upgrade.

FIXES
  1 DELETE DIP  Anyone could delete a dip, no reason, no log — and each dip
                anchors every variation after it. Owner / manager, reason, log.
  2 ORDERS      The advisor ignored tankers already ordered (see 12).
  3 FIT         The fit check used today's room; a tanker ordered now arrives
                after the lead time, when the tank has drained further. It now
                uses the room on the arrival day.
  4 TESTING     The sales rate counted testing fuel as sold; it goes back in
                the tank. Taken out.
  5 STALE       The advisor now says when the tank level rests on a reading
                two or more days old.

DIP VARIATION
  6 TOLERANCE   max(fixed litres, % of litres moved since the last dip).
  7 CAUSE       Tanker unloading / calibration / typing error / temperature
                (explained — no alert) or leak / theft / unrecorded sale /
                other (recorded, still alerts). Synced in app_settings.config.
  8 MONTHLY     Loss per fuel per month: litres, % of sales, ₹ at cost,
                unexplained short, worst day; chart of the last 60 days.
  9 TANK CHART  Calibration table (cm → litres); a dip in cm fills the litres.
 10 EDIT        Correct a reading (logged, with the reason) instead of
                delete-and-re-enter.
 11 GROSS       Optional GROSS VOLUME on the ATG entry. When filled, it is the
                figure compared with the meters (both at tank temperature);
                NET stays in the note.

ORDER ADVISOR
 12 ORDERS      ORDER PLACED → fuel, KL, expected date. Forecast and chart
                count it; a fuel load entered later closes it (any phone);
                overdue orders are flagged; the actual lead time is learned.
 13 SIZE/SPLIT  Largest load that fits on arrival (by compartment sizes if
                set); optional split load (e.g. 8 KL MSD + 4 KL HSD) when both
                tanks are due together and "split loads" is switched on.

No SQL. Usage:  python3 patch_dip_order.py [path/to/index.html]   (idempotent)
Requires MF_ATG_REVERSE_V1, MF_FIVE_V1 and MF_FUELLOAD_V1.
"""
import shutil, subprocess, sys, re, os, tempfile

PATH = sys.argv[1] if len(sys.argv) > 1 else "index.html"
SENTINEL = "MF_DIPORDER_V1"

MODULE = r"""// ══════════════════════════════════════════════════════════════════
// DIP VARIATION + ORDER ADVISOR — MF_DIPORDER_V1
//   dip meta      cause / explained per dip, synced in app_settings.config
//                 (dip_readings has no column for it), merged entry by entry
//   tolerance     max(fixed litres, % of litres moved since the last dip)
//   tank chart    calibration table, dip cm → litres
//   monthly       loss per fuel per month, % of sales, ₹ at cost
//   orders        placed / expected / received; the forecast counts them
//   fit           room in the tank on the day the tanker arrives
// ══════════════════════════════════════════════════════════════════

// ── synced maps in app_settings.config: {m:{id:{…, at}}, updatedAt} ──
function _cfgMap(key){
  var c=null; try{ c=JSON.parse(localStorage.getItem(key)||'null'); }catch(e){}
  c=(c&&typeof c==='object')?c:{}; c.m=(c.m&&typeof c.m==='object')?c.m:{}; return c;
}
function _cfgMapPut(key,id,obj){
  var c=_cfgMap(key); obj.at=new Date().toISOString(); c.m[String(id)]=obj; c.updatedAt=obj.at;
  localStorage.setItem(key,JSON.stringify(c));
  localStorage.setItem('mf_cfg_savedAt',obj.at);
  if(typeof queueSettingsSave==='function')queueSettingsSave();
}
// Entry by entry, newest wins — two phones editing different dips or orders
// must not wipe each other the way a whole-section overwrite would.
function _cfgMapMerge(key,inc){
  if(!inc||typeof inc!=='object'||!inc.m)return;
  var c=_cfgMap(key), mine=false;
  Object.keys(inc.m).forEach(function(k){ var a=c.m[k], b=inc.m[k]; if(b&&(!a||String(b.at||'')>String(a.at||'')))c.m[k]=b; });
  Object.keys(c.m).forEach(function(k){ var a=c.m[k], b=inc.m[k]; if(!b||String(a.at||'')>String(b.at||''))mine=true; });
  c.updatedAt=[String(c.updatedAt||''),String(inc.updatedAt||'')].sort().pop();
  localStorage.setItem(key,JSON.stringify(c));
  if(mine&&typeof queueSettingsSave==='function')queueSettingsSave();
}

// ── 7. cause of a variation ─────────────────────────────────────────────
var DIP_CAUSES=[['tanker','Tanker unloading',true],['calib','Calibration / meter test',true],['typo','Reading or typing error',true],
                ['temp','Temperature',true],['leak','Leak suspected',false],['theft','Theft suspected',false],
                ['sale','Unrecorded sale',false],['other','Other',false]];
function _dipCause(k){ return DIP_CAUSES.find(function(c){ return c[0]===k; })||null; }
function _dipMetaGet(id){ var e=_cfgMap('dipMeta').m[String(id)]; return (e&&!e.del)?e:null; }
function _dipMetaMove(a,b){
  var c=_cfgMap('dipMeta'), e=c.m[String(a)]; if(!e||e.del)return;
  _cfgMapPut('dipMeta',b,Object.assign({},e)); _cfgMapPut('dipMeta',a,{del:true});
}
// ── 6. tolerance scales with what moved through the tank ────────────────
function _dipTolBook(b){
  var c=tankCfg(), flow=Math.abs(b&&b.sold||0)-Math.abs(b&&b.tested||0)+Math.abs(b&&b.loaded||0);
  return _r2(Math.max(c.tol||0,((c.tolPct||0)/100)*Math.max(0,flow)));
}
function _dipCan(){ return !_currentUser||_isOwner||(_currentUser&&_currentUser.role==='manager'); }

// ── 1 / 10. edit or delete a dip — owner / manager, with a reason ───────
function openDipEdit(id){
  var r=dipReadings.find(function(x){ return String(x.id)===String(id); }); if(!r)return;
  if(!_dipCan()){ showToast('🔒 Only an owner or manager can change a dip'); return; }
  var m=_dipMetaGet(id)||{}, lv=_dipLive(r);
  var o=document.getElementById('dipEditOv'); if(o)o.remove();
  o=document.createElement('div'); o.id='dipEditOv';
  o.style.cssText='position:fixed;inset:0;background:rgba(0,0,0,.75);z-index:950;display:flex;align-items:center;justify-content:center;padding:16px';
  var sel='width:100%;padding:6px 9px;background:var(--bg);border:1px solid var(--border);border-radius:4px;color:var(--text);font-family:\'JetBrains Mono\',monospace;font-size:12px';
  o.innerHTML='<div style="background:var(--s2);border:1px solid var(--border2);border-radius:10px;padding:18px;max-width:440px;width:100%">'+
    '<div style="font-family:\'Syne\',sans-serif;font-weight:800;font-size:14px;margin-bottom:4px">'+_esc(r.type)+' · '+_esc(r.date)+' · '+_esc(_DIP_SLOT_LBL[r.slot]||r.slot)+'</div>'+
    '<div style="font-family:\'JetBrains Mono\',monospace;font-size:11px;color:var(--muted);margin-bottom:12px">Book '+lv.book.toFixed(1)+' L · variation '+(lv.variation>=0?'+':'')+lv.variation.toFixed(1)+' L · tolerance ±'+lv.tol+' L</div>'+
    '<div class="rg" style="grid-template-columns:1fr 1fr;margin-bottom:8px">'+
      '<div><label>OBSERVED (LITRES)</label><input type="number" step="0.001" id="de_obs" value="'+_esc(String(r.observed))+'"></div>'+
      '<div><label>DIP (CM)</label><input type="number" step="0.1" id="de_cm" value="'+(r.dipCm!=null?_esc(String(r.dipCm)):'')+'"></div></div>'+
    '<div style="margin-bottom:8px"><label>CAUSE OF THE VARIATION</label><select id="de_cause" style="'+sel+'"><option value="">— not explained —</option>'+
      DIP_CAUSES.map(function(c){ return '<option value="'+c[0]+'"'+(m.cause===c[0]?' selected':'')+'>'+c[1]+(c[2]?' (explained)':'')+'</option>'; }).join('')+'</select></div>'+
    '<div style="margin-bottom:8px"><label>CAUSE NOTE</label><input type="text" id="de_cnote" value="'+_esc(m.note||'')+'" placeholder="e.g. 8 KL unloaded 11 AM, dip taken 30 min after"></div>'+
    '<div style="margin-bottom:12px"><label>WHY THE CHANGE (for the log)</label><input type="text" id="de_why" placeholder="e.g. typed 5914 as 5194"></div>'+
    '<div style="font-family:\'JetBrains Mono\',monospace;font-size:10px;color:var(--muted);margin-bottom:12px;line-height:1.5">An explained variation still counts in the totals — it just stops raising alerts. Leak, theft and unrecorded sale are recorded but stay as alerts.</div>'+
    '<div style="display:flex;gap:8px;flex-wrap:wrap">'+
      '<button class="save-btn" style="margin:0;padding:8px 18px" onclick="saveDipEdit('+r.id+')">✓ SAVE</button>'+
      '<button class="btn btn-g" onclick="document.getElementById(\'dipEditOv\').remove()">CANCEL</button>'+
      '<button class="btn btn-d" style="margin-left:auto" onclick="document.getElementById(\'dipEditOv\').remove();delDip('+r.id+')">✕ DELETE</button></div></div>';
  document.body.appendChild(o);
}
function saveDipEdit(id){
  var r=dipReadings.find(function(x){ return String(x.id)===String(id); }); if(!r)return;
  var obs=parseFloat(document.getElementById('de_obs').value), cm=parseFloat(document.getElementById('de_cm').value);
  var cause=document.getElementById('de_cause').value, cnote=_clean(document.getElementById('de_cnote').value.trim());
  var why=_clean(document.getElementById('de_why').value.trim());
  if(!isFinite(obs)||obs<0){ showToast('Enter the observed litres'); return; }
  var cap=r.type==='MSD'?tankCfg().capMSD:tankCfg().capHSD;
  if(obs>cap){ showToast(obs+' L is more than the '+cap+' L tank'); return; }
  var changed=Math.abs(obs-(+r.observed||0))>0.0005||String(isFinite(cm)?cm:'')!==String(r.dipCm!=null?r.dipCm:'');
  if(changed&&!why){ showToast('Say why the reading is being changed — it goes in the log'); return; }
  var m=_dipMetaGet(id)||{}, log=[];
  if(changed){
    var b=bookStock(r.type,r.date,r.slot), was=+r.observed||0;
    r.observed=_r2(obs); r.dipCm=isFinite(cm)?cm:null; r.book=_r2(b.book); r.variation=_r2(obs-b.book);
    r.savedAt=new Date().toISOString(); r.editedBy=_currentUser?_currentUser.username:'';
    saveDipsLS();
    if(_currentUser&&typeof sbSaveDip==='function')sbSaveDip(r).catch(console.error);
    log.push('observed '+was+' → '+r.observed+' L'+(why?' ('+why+')':''));
  }
  if((m.cause||'')!==cause||(m.note||'')!==cnote){
    if(cause||cnote)_cfgMapPut('dipMeta',id,{cause:cause,note:cnote,by:_currentUser?_currentUser.username:''});
    else if(m.cause||m.note)_cfgMapPut('dipMeta',id,{del:true});
    var cc=_dipCause(cause); log.push('cause: '+(cc?cc[1]:'none')+(cnote?' — '+cnote:''));
  }
  var o=document.getElementById('dipEditOv'); if(o)o.remove();
  if(!log.length){ showToast('Nothing changed'); return; }
  if(typeof logActivity==='function')logActivity('dip_edit','dip_reading',r.id,r.type+' '+r.date+' '+r.slot+' • '+log.join(' • '));
  renderDip(); showToast('✓ Dip updated');
}

// ── 9. tank calibration chart: dip cm → litres ───────────────────────────
function _tankChart(){ var c=null; try{ c=JSON.parse(localStorage.getItem('tankChart')||'null'); }catch(e){} return (c&&typeof c==='object')?c:{MSD:[],HSD:[]}; }
function _chartParse(txt){
  var pts=[], bad=[];
  String(txt||'').split(/\r?\n/).forEach(function(line,i){
    var s=line.trim(); if(!s)return;
    var m=/^([\d.]+)\s*[,;\t ]\s*([\d.,]+)$/.exec(s);
    if(!m){ bad.push(i+1); return; }
    pts.push([parseFloat(m[1]),parseFloat(m[2].replace(/,/g,''))]);
  });
  pts.sort(function(a,b){ return a[0]-b[0]; });
  for(var i=1;i<pts.length;i++) if(!(pts[i][1]>=pts[i-1][1])||pts[i][0]===pts[i-1][0]) bad.push('order near '+pts[i][0]+' cm');
  return {pts:pts,bad:bad};
}
function saveTankChart(){
  var out={MSD:[],HSD:[]}, errs=[];
  [['MSD','cfg_chart_msd'],['HSD','cfg_chart_hsd']].forEach(function(t){
    var p=_chartParse((document.getElementById(t[1])||{}).value);
    if(p.bad.length)errs.push(t[0]+': line '+p.bad.slice(0,3).join(', '));
    out[t[0]]=p.pts;
  });
  if(errs.length){ showToast('Check the chart — '+errs.join(' · ')+' (each line: cm, litres; litres must rise with cm)'); return; }
  out.updatedAt=new Date().toISOString();
  localStorage.setItem('tankChart',JSON.stringify(out));
  localStorage.setItem('mf_cfg_savedAt',out.updatedAt);
  if(typeof queueSettingsSave==='function')queueSettingsSave();
  if(typeof logActivity==='function')logActivity('tank_chart','settings',null,'MSD '+out.MSD.length+' points · HSD '+out.HSD.length+' points');
  showToast('✓ Tank chart saved — MSD '+out.MSD.length+' / HSD '+out.HSD.length+' points');
  dipFromChart(true);
}
function _chartLitres(type,cm){
  var p=(_tankChart()[type]||[]); if(p.length<2||!isFinite(cm))return null;
  if(cm<p[0][0]||cm>p[p.length-1][0])return null;
  for(var i=1;i<p.length;i++) if(cm<=p[i][0]){
    var a=p[i-1], b=p[i]; return _r2(a[1]+(b[1]-a[1])*(cm-a[0])/(b[0]-a[0]));
  }
  return null;
}
function dipFromChart(quiet){
  var t=(document.getElementById('dip_tank')||{}).value, cmEl=document.getElementById('dip_cm'), lEl=document.getElementById('dip_litres');
  if(!cmEl||!lEl)return;
  var cm=parseFloat(cmEl.value), note=document.getElementById('dip_chart_note');
  var has=(_tankChart()[t]||[]).length>=2;
  if(!isFinite(cm)||!has){ if(note)note.textContent=has?'':'No tank chart for '+t+' — type the litres, or add the chart under Tank settings.'; return; }
  var L=_chartLitres(t,cm);
  if(L==null){ if(note)note.textContent=cm+' cm is outside the '+t+' chart'; return; }
  if(lEl.value===''||lEl.dataset.auto==='1'){ lEl.value=L; lEl.dataset.auto='1'; }
  if(note)note.textContent='Chart: '+cm+' cm = '+L.toLocaleString('en-IN')+' L'+(lEl.dataset.auto==='1'?'':' (litres typed by hand kept)');
  if(!quiet)dipPreview();
}

// ── 8. monthly loss report + daily chart ────────────────────────────────
var _dipMonthChart=null;
function _dipRenderMonthly(){
  var box=document.getElementById('dip_month_card'); if(!box)return;
  var rows=_dipSortedLive().filter(function(r){ return !r.unused; });
  if(!rows.length){ box.style.display='none'; return; }
  box.style.display='';
  var M={};
  rows.forEach(function(r){
    var k=String(r.date).slice(0,7)+'|'+r.type;
    var x=M[k]||(M[k]={ym:String(r.date).slice(0,7),t:r.type,n:0,v:0,shortL:0,overL:0,expl:0,worst:null});
    x.n++; x.v+=r.variation||0;
    if(r.explained)x.expl+=r.variation||0;
    else if(r.variation<-r.tol)x.shortL+=r.variation; else if(r.variation>r.tol)x.overL+=r.variation;
    if(!x.worst||r.variation<x.worst.variation)x.worst=r;
  });
  var keys=Object.keys(M).sort().reverse().slice(0,24);
  var sold=function(t,ym){ return records.filter(function(r){ return String(r.date).slice(0,7)===ym; })
    .reduce(function(s,r){ return s+(t==='MSD'?(r.msdT||0)-(r.testMSDL||0):(r.hsdT||0)-(r.testHSDL||0)); },0); };
  var mn=function(ym){ var p=ym.split('-'); return new Date(+p[0],+p[1]-1,1).toLocaleDateString('en-IN',{month:'short',year:'numeric'}); };
  var td=function(v,c){ return '<td style="text-align:right;white-space:nowrap'+(c?';color:'+c:'')+'">'+v+'</td>'; };
  var body=keys.map(function(k){
    var x=M[k], s=sold(x.t,x.ym), pct=s>0?x.v/s*100:null;
    var me=x.ym+'-31', wac=(typeof _fuelWAC==='function')?_fuelWAC(x.t,me):0;
    var col=x.v<0?'var(--red)':'var(--diesel)';
    return '<tr><td style="white-space:nowrap">'+mn(x.ym)+'</td><td style="color:'+(x.t==='MSD'?'var(--petrol)':'var(--diesel)')+'">'+x.t+'</td>'+td(x.n)+
      td((x.v>=0?'+':'')+x.v.toFixed(1)+' L',Math.abs(x.v)<1?null:col)+td(pct!=null?(pct>=0?'+':'')+pct.toFixed(2)+'%':'—')+
      td(wac>0?(x.v<0?'−':'+')+fmt(Math.abs(x.v)*wac):'—')+td(x.shortL?x.shortL.toFixed(1)+' L':'—',x.shortL?'var(--red)':null)+
      td(x.expl?(x.expl>=0?'+':'')+x.expl.toFixed(1)+' L':'—','var(--muted)')+
      '<td style="white-space:nowrap;color:var(--muted)">'+(x.worst&&x.worst.variation<0?_esc(x.worst.date.slice(8,10)+'/'+x.worst.date.slice(5,7))+' '+x.worst.variation.toFixed(1)+' L':'—')+'</td></tr>';
  }).join('');
  box.innerHTML='<div class="dash-card-head"><div class="dash-card-title">📅 MONTHLY LOSS — BY FUEL</div></div>'+
    '<div style="overflow-x:auto"><table class="data-tbl" style="font-size:11px"><thead><tr><th>Month</th><th>Tank</th><th style="text-align:right">Dips</th>'+
    '<th style="text-align:right">Variation</th><th style="text-align:right">% of sales</th><th style="text-align:right">At cost</th>'+
    '<th style="text-align:right">Unexplained short</th><th style="text-align:right">Explained</th><th>Worst</th></tr></thead><tbody>'+body+'</tbody></table></div>'+
    '<div style="font-family:\'JetBrains Mono\',monospace;font-size:10px;color:var(--muted);margin:8px 0 10px;line-height:1.6">Variation is the sum of every dip’s gap to book in the month (explained ones included). % of sales is against litres metered that month, testing taken out. Unexplained short = dips short beyond their tolerance with no cause, or a cause that stays an alert.</div>'+
    '<div style="font-family:\'Syne\',sans-serif;font-weight:700;font-size:10px;letter-spacing:1.5px;color:var(--muted);margin-bottom:6px">VARIATION PER DIP — LAST 60 DAYS</div>'+
    '<div style="height:200px;position:relative"><canvas id="dipMonthChart"></canvas></div>';
  if(typeof Chart==='undefined')return;
  var from=(function(){ var d=new Date(); d.setDate(d.getDate()-60); return _isoLocal(d); })();
  var rec=rows.filter(function(r){ return r.date>=from; });
  var dates=[...new Set(rec.map(function(r){ return r.date; }))].sort();
  var ser=function(t){ return dates.map(function(d){ var v=rec.filter(function(r){ return r.type===t&&r.date===d; }); return v.length?_r2(v.reduce(function(s,r){ return s+r.variation; },0)):null; }); };
  if(_dipMonthChart){ try{ _dipMonthChart.destroy(); }catch(e){} }
  _dipMonthChart=new Chart(document.getElementById('dipMonthChart').getContext('2d'),{type:'bar',
    data:{labels:dates.map(function(d){ return d.slice(8,10)+'/'+d.slice(5,7); }),datasets:[
      {label:'MSD',data:ser('MSD'),backgroundColor:'rgba(0,212,160,.6)',borderColor:'#00d4a0',borderWidth:1},
      {label:'HSD',data:ser('HSD'),backgroundColor:'rgba(255,176,32,.6)',borderColor:'#ffb020',borderWidth:1}]},
    options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{labels:{color:'#AAAAAA',font:{size:10}}},
      tooltip:{callbacks:{label:function(c){ return ' '+c.dataset.label+': '+(c.raw==null?'—':(c.raw>=0?'+':'')+c.raw+' L'); }}}},
      scales:{x:{ticks:{color:'#AAAAAA',font:{size:9}},grid:{color:'rgba(47,47,47,.9)'}},
              y:{ticks:{color:'#AAAAAA',font:{size:9},callback:function(v){ return v+' L'; }},grid:{color:'rgba(47,47,47,.9)'}}}}});
}

// ── 12. orders on the way ───────────────────────────────────────────────
function _orders(){ var m=_cfgMap('fuelOrders').m; return Object.keys(m).map(function(k){ return m[k]; }).filter(function(o){ return o&&!o.del&&o.id; }); }
function _orderEffDate(o){ var t=new Date(); t.setDate(t.getDate()+1); var tm=_isoLocal(t); return String(o.expected||tm)<tm?tm:String(o.expected); }
// Open orders, closing any that a fuel load (entered on any phone) has met.
function _openOrders(type){
  var open=_orders().filter(function(o){ return o.status==='open'; }).sort(function(a,b){ return String(a.orderedOn).localeCompare(String(b.orderedOn)); });
  var used={}; _orders().forEach(function(o){ if(o.loadId)used[String(o.loadId)]=1; });
  open.forEach(function(o){
    var l=(typeof fuelLoads!=='undefined'?fuelLoads:[]).filter(function(x){ return x.type===o.type&&String(x.date)>=String(o.orderedOn)&&!used[String(x.id)]; })
      .sort(function(a,b){ return String(a.date).localeCompare(String(b.date)); })[0];
    if(l){ used[String(l.id)]=1; _cfgMapPut('fuelOrders',o.id,Object.assign({},o,{status:'received',loadId:l.id,receivedOn:l.date,receivedKL:_r2((+l.vol||0)/1000)})); o.status='received'; }
  });
  return open.filter(function(o){ return o.status==='open'&&(!type||o.type===type); });
}
function _incomingOn(type,iso){
  return _openOrders(type).filter(function(o){ return _orderEffDate(o)===iso; }).reduce(function(s,o){ return s+(+o.kl||0)*1000; },0);
}
function _leadHistory(){
  var r=_orders().filter(function(o){ return o.status==='received'&&o.orderedOn&&o.receivedOn; })
    .sort(function(a,b){ return String(b.receivedOn).localeCompare(String(a.receivedOn)); }).slice(0,6);
  if(!r.length)return null;
  var d=r.map(function(o){ return Math.max(0,Math.round((Date.parse(o.receivedOn+'T00:00:00')-Date.parse(o.orderedOn+'T00:00:00'))/86400000)); });
  return {n:d.length,avg:d.reduce(function(a,b){ return a+b; },0)/d.length,max:Math.max.apply(null,d)};
}
function saveFuelOrder(){
  var g=function(id){ var e=document.getElementById(id); return e?String(e.value||'').trim():''; };
  var type=g('ord_type'), kl=parseFloat(g('ord_kl')), exp=g('ord_exp'), sup=_clean(g('ord_sup'));
  if(!(kl>0)){ showToast('Enter the KL ordered'); return; }
  var cap=type==='MSD'?tankCfg().capMSD:tankCfg().capHSD;
  if(kl*1000>cap){ showToast(kl+' KL is more than the '+cap+' L tank'); return; }
  var id=_newId();
  _cfgMapPut('fuelOrders',id,{id:id,type:type,kl:kl,orderedOn:_isoLocal(),expected:exp||_isoLocal(),supplier:sup,status:'open',by:_currentUser?_currentUser.username:''});
  if(typeof logActivity==='function')logActivity('fuel_order','order',id,type+' '+kl+' KL ordered • expected '+(exp||'—')+(sup?' • '+sup:''));
  renderAdvisor(); showToast('✓ Order recorded — the forecast now counts it');
}
function closeFuelOrder(id,how){
  var o=_orders().find(function(x){ return String(x.id)===String(id); }); if(!o)return;
  if(how==='cancel'&&!confirm('Cancel the '+o.type+' '+o.kl+' KL order of '+o.orderedOn+'?'))return;
  _cfgMapPut('fuelOrders',o.id,Object.assign({},o,{status:how==='cancel'?'cancelled':'received',receivedOn:how==='cancel'?null:_isoLocal()}));
  if(typeof logActivity==='function')logActivity('fuel_order_'+how,'order',o.id,o.type+' '+o.kl+' KL');
  renderAdvisor();
  showToast(how==='cancel'?'Order cancelled':'Marked received — enter the tanker bill under Fuel Loads so the tank counts it');
}
function toggleOrderForm(){ var f=document.getElementById('ord_form'); if(f)f.style.display=f.style.display==='none'?'flex':'none'; }
function _renderOrders(a){
  var box=document.getElementById('adv_orders'); if(!box)return;
  var cfg=orderCfg(), open=_openOrders(), exp=new Date(); exp.setDate(exp.getDate()+Math.ceil(cfg.leadDays||0));
  var sel='padding:5px 8px;background:var(--bg);border:1px solid var(--border);border-radius:4px;color:var(--text);font-family:\'JetBrains Mono\',monospace;font-size:12px';
  var today=_isoLocal();
  var list=open.map(function(o){
    var late=String(o.expected)<today;
    return '<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;background:var(--s3);border-left:3px solid '+(late?'var(--red)':'var(--blue)')+';border-radius:4px;padding:8px 10px;font-family:\'JetBrains Mono\',monospace;font-size:11px">'+
      '<b style="color:'+(o.type==='MSD'?'var(--petrol)':'var(--diesel)')+'">'+_esc(o.type)+' '+o.kl+' KL</b>'+
      '<span>ordered '+_esc(String(o.orderedOn).slice(8,10)+'/'+String(o.orderedOn).slice(5,7))+'</span>'+
      '<span style="color:'+(late?'var(--red)':'var(--text)')+'">'+(late?'⚠ was due ':'expected ')+_esc(String(o.expected).slice(8,10)+'/'+String(o.expected).slice(5,7))+'</span>'+
      (o.supplier?'<span style="color:var(--muted)">'+_esc(o.supplier)+'</span>':'')+
      '<span style="margin-left:auto;display:flex;gap:6px"><button class="btn btn-g" style="padding:2px 8px;font-size:10px" onclick="closeFuelOrder('+o.id+',\'received\')">✓ RECEIVED</button>'+
      '<button class="btn btn-g" style="padding:2px 8px;font-size:10px" onclick="closeFuelOrder('+o.id+',\'cancel\')">✕ CANCEL</button></span></div>';
  }).join('');
  var pick=(a&&a.pick)||'MSD';
  box.innerHTML='<div style="display:flex;align-items:center;gap:8px;margin-bottom:6px"><b style="font-family:\'Syne\',sans-serif;font-size:10px;letter-spacing:1.5px;color:var(--muted)">ORDERS ON THE WAY</b>'+
    '<button class="btn btn-g" style="padding:3px 10px;font-size:10px;margin-left:auto" onclick="toggleOrderForm()">📝 ORDER PLACED</button></div>'+
    '<div id="ord_form" style="display:none;gap:8px;flex-wrap:wrap;align-items:flex-end;margin-bottom:8px">'+
      '<div><div class="flabel" style="margin-bottom:3px">FUEL</div><select id="ord_type" style="'+sel+'"><option value="MSD"'+(pick==='MSD'?' selected':'')+'>MSD — Petrol</option><option value="HSD"'+(pick==='HSD'?' selected':'')+'>HSD — Diesel</option></select></div>'+
      '<div><div class="flabel" style="margin-bottom:3px">KL</div><input type="number" id="ord_kl" step="0.5" value="'+(cfg.normalKL||'')+'" style="width:80px"></div>'+
      '<div><div class="flabel" style="margin-bottom:3px">EXPECTED</div><input type="date" id="ord_exp" value="'+_isoLocal(exp)+'" style="width:150px"></div>'+
      '<div><div class="flabel" style="margin-bottom:3px">SUPPLIER</div><input type="text" id="ord_sup" placeholder="IOCL" style="width:120px"></div>'+
      '<button class="save-btn" style="margin:0;padding:6px 14px;max-width:120px" onclick="saveFuelOrder()">✓ SAVE</button></div>'+
    (list||'<div style="font-family:\'JetBrains Mono\',monospace;font-size:11px;color:var(--muted)">None. Press ORDER PLACED when you book a tanker — the forecast then counts it and stops asking you to order.</div>');
}

// ── 3 / 13. load sizes: what fits on arrival, split loads ───────────────
function _compList(cfg){ return String(cfg.compKL||'').split(/[,+ ]+/).map(function(x){ return parseFloat(x); }).filter(function(x){ return x>0; }); }
function _subsetSums(c){ var s={0:1}; c.forEach(function(k){ Object.keys(s).map(Number).forEach(function(v){ s[_r2(v+k)]=1; }); }); return Object.keys(s).map(Number).filter(function(x){ return x>0; }).sort(function(a,b){ return a-b; }); }
function _bestFitKL(roomL,cfg){
  var c=_compList(cfg), opts=c.length?_subsetSums(c):null;
  var room=roomL/1000;
  if(opts){ var f=opts.filter(function(k){ return k<=room+1e-9; }); return f.length?f[f.length-1]:0; }
  return Math.max(0,Math.floor(room*2)/2);
}
function _splitPlan(a,cfg){
  if(!cfg.splitLoads)return null;
  var comps=_compList(cfg).sort(function(x,y){ return y-x; }); if(comps.length<2)return null;
  var M=a.msd, H=a.hsd; if(M.daysLeft==null||H.daysLeft==null)return null;
  // both need fuel within a lead time of each other
  if(Math.abs((M.orderInDays||0)-(H.orderInDays||0))>(cfg.leadDays||0)+2)return null;
  var room={MSD:M.arrivalUllage!=null?M.arrivalUllage:M.ullage,HSD:H.arrivalUllage!=null?H.arrivalUllage:H.ullage};
  var per={MSD:M.perDay||1,HSD:H.perDay||1}, have={MSD:Math.max(0,M.usableL),HSD:Math.max(0,H.usableL)}, got={MSD:0,HSD:0};
  comps.forEach(function(k){
    var L=k*1000;
    var cand=['MSD','HSD'].filter(function(t){ return room[t]-got[t]*1000>=L; })
      .sort(function(x,y){ return (have[x]+got[x]*1000)/per[x]-(have[y]+got[y]*1000)/per[y]; });
    if(cand.length)got[cand[0]]=_r2(got[cand[0]]+k);
  });
  if(!got.MSD||!got.HSD)return null;
  return {MSD:got.MSD,HSD:got.HSD,total:_r2(got.MSD+got.HSD)};
}

// ── 5. how old is the tank level ────────────────────────────────────────
function _levelAgeDays(type){
  var b=tankLevel(type), d=b.anchor?b.anchor.date:((typeof _openingAsOf==='function')?_openingAsOf():'');
  if(!d)return null;
  return {date:d,days:Math.max(0,Math.round((Date.parse(_isoLocal()+'T00:00:00')-Date.parse(d+'T00:00:00'))/86400000)),dip:!!b.anchor};
}"""

HUNKS = [
# ── HTML: ATG gross ─────────────────────────────────────────────────────
("H1 ATG gross — petrol",
r"""            <div><label>NET VOLUME (L)</label><input type="number" step="0.01" inputmode="decimal" id="atg_ms_vol" placeholder="5914.72"></div>""",
r"""            <div><label>NET VOLUME (L)</label><input type="number" step="0.01" inputmode="decimal" id="atg_ms_vol" placeholder="5914.72"></div>
            <div><label title="If the gauge shows both: GROSS is at tank temperature, like the meters. When filled, it is what the book is compared with.">GROSS VOL (L) — IF SHOWN</label><input type="number" step="0.01" inputmode="decimal" id="atg_ms_gross" placeholder="optional"></div><!-- MF_DIPORDER_V1 -->"""),

("H2 ATG gross — diesel",
r"""            <div><label>NET VOLUME (L)</label><input type="number" step="0.01" inputmode="decimal" id="atg_hsd_vol" placeholder="8023.83"></div>""",
r"""            <div><label>NET VOLUME (L)</label><input type="number" step="0.01" inputmode="decimal" id="atg_hsd_vol" placeholder="8023.83"></div>
            <div><label title="If the gauge shows both: GROSS is at tank temperature, like the meters. When filled, it is what the book is compared with.">GROSS VOL (L) — IF SHOWN</label><input type="number" step="0.01" inputmode="decimal" id="atg_hsd_gross" placeholder="optional"></div>"""),

# ── HTML: dip form ──────────────────────────────────────────────────────
("H3 tank change re-reads the chart",
r"""          <select id="dip_tank" onchange="dipPreview()" """,
r"""          <select id="dip_tank" onchange="dipFromChart()" """),

("H4 dip cm → litres from the chart",
r"""        <div><label>DIP (CM) — OPTIONAL</label><input type="number" id="dip_cm" step="0.1" inputmode="decimal" placeholder="e.g. 84.5"></div>
        <div><label>OBSERVED (LITRES)</label><input type="number" id="dip_litres" step="0.001" inputmode="decimal" placeholder="0.000" oninput="dipPreview()"></div>
      </div>""",
r"""        <div><label>DIP (CM) — OPTIONAL</label><input type="number" id="dip_cm" step="0.1" inputmode="decimal" placeholder="e.g. 84.5" oninput="dipFromChart()"></div>
        <div><label>OBSERVED (LITRES)</label><input type="number" id="dip_litres" step="0.001" inputmode="decimal" placeholder="0.000" oninput="this.dataset.auto='';dipPreview()"></div>
      </div>
      <div id="dip_chart_note" style="font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--muted);margin-top:4px"></div><!-- MF_DIPORDER_V1 -->"""),

("H5 history: cause column",
r"""            <th>BOOK L</th><th>SINCE LAST DIP</th><th>CUMULATIVE</th><th>NOTES</th><th></th></tr></thead>""",
r"""            <th>BOOK L</th><th>SINCE LAST DIP</th><th>CUMULATIVE</th><th>CAUSE</th><th>NOTES</th><th></th></tr></thead>"""),

("H6 monthly loss card",
r"""        Record one at day open and one at day close to start tracking loss.
      </div>
    </div>""",
r"""        Record one at day open and one at day close to start tracking loss.
      </div>
    </div>

    <div class="dash-card" style="margin-top:12px;display:none" id="dip_month_card"></div><!-- MF_DIPORDER_V1 -->"""),

("H7 tank settings: % tolerance and tank chart",
r"""        <div><label>ACCEPTABLE VARIATION (L)</label><input type="number" id="cfg_tol" step="0.1" oninput="saveTankCfg()"></div>
      </div>
      <div style="font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--muted);margin-top:8px;line-height:1.5">
        Tolerance is the swing you accept as normal measurement error and evaporation.
        Anything past it is flagged. Typical starting point: 0.3% of a full tanker, so 20–30 L.
      </div>""",
r"""        <div><label>ACCEPTABLE VARIATION (L)</label><input type="number" id="cfg_tol" step="0.1" oninput="saveTankCfg()"></div>
        <div><label>…OR % OF LITRES MOVED</label><input type="number" id="cfg_tol_pct" step="0.05" inputmode="decimal" oninput="saveTankCfg()"></div><!-- MF_DIPORDER_V1 -->
      </div>
      <div style="font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--muted);margin-top:8px;line-height:1.5">
        Tolerance is the swing you accept as normal measurement error and evaporation.
        Each dip gets the larger of the two: the fixed litres, or the % of litres sold and unloaded
        since the dip before it — so a 3,000 L day and a quiet day are not held to the same 25 L.
      </div>
      <div style="margin-top:14px;font-family:'Syne',sans-serif;font-weight:700;font-size:10px;letter-spacing:1.5px;color:var(--muted)">TANK CHART — DIP (CM) → LITRES</div>
      <div style="font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--muted);margin:4px 0 8px;line-height:1.5">
        From the tank’s calibration chart. One point per line: <b>cm, litres</b> (e.g. <b>84.5, 6120</b>). Once saved, a dip typed in cm fills the litres.
      </div>
      <div class="rg" style="grid-template-columns:repeat(auto-fit,minmax(220px,1fr))">
        <div><label style="color:var(--petrol)">MSD CHART</label><textarea id="cfg_chart_msd" rows="6" style="width:100%;background:var(--bg);border:1px solid var(--border);border-radius:4px;color:var(--text);font-family:'JetBrains Mono',monospace;font-size:11px;padding:6px" placeholder="10, 180&#10;20, 620&#10;…"></textarea></div>
        <div><label style="color:var(--diesel)">HSD CHART</label><textarea id="cfg_chart_hsd" rows="6" style="width:100%;background:var(--bg);border:1px solid var(--border);border-radius:4px;color:var(--text);font-family:'JetBrains Mono',monospace;font-size:11px;padding:6px" placeholder="10, 210&#10;20, 760&#10;…"></textarea></div>
      </div>
      <button class="btn btn-g" style="margin-top:8px" onclick="saveTankChart()">✓ SAVE TANK CHART</button>"""),

# ── HTML: order advisor ─────────────────────────────────────────────────
("H8 orders on the way",
r"""      <div id="adv_notes" style="display:flex;flex-direction:column;gap:6px;margin-top:12px"></div>""",
r"""      <div id="adv_notes" style="display:flex;flex-direction:column;gap:6px;margin-top:12px"></div>
      <div id="adv_orders" style="margin-top:14px"></div><!-- MF_DIPORDER_V1 -->"""),

("H9 ordering rules: compartments, split loads",
r"""        <div><label>DEAD STOCK / RESERVE (L)</label><input type="number" id="cfg_reserve_l" step="10" oninput="saveOrderCfg()"></div>
      </div>""",
r"""        <div><label>DEAD STOCK / RESERVE (L)</label><input type="number" id="cfg_reserve_l" step="10" oninput="saveOrderCfg()"></div>
        <div><label>TANKER COMPARTMENTS (KL)</label><input type="text" id="cfg_comp_kl" placeholder="e.g. 4,4,4" onchange="saveOrderCfg()"></div><!-- MF_DIPORDER_V1 -->
        <div><label>SPLIT LOADS (MS + HSD)</label>
          <select id="cfg_split" onchange="saveOrderCfg()" style="width:100%;padding:5px 9px;background:var(--bg);border:1px solid var(--border);border-radius:4px;color:var(--text);font-family:'JetBrains Mono',monospace;font-size:12px">
            <option value="0">No — one fuel per tanker</option><option value="1">Yes — supplier sends split loads</option></select></div>
      </div>"""),

("H10 ordering rules note",
r"""        send a normal one. It only matters if it still fits in the tank.
      </div>""",
r"""        send a normal one. It only matters if it still fits in the tank.<br>
        <b>Compartments</b> are the tanker’s chambers; the advisor then suggests loads that can actually
        be filled (e.g. 4, 8 or 12 KL). With <b>split loads</b> on, it suggests one tanker for both fuels
        when both tanks are due within a lead time of each other.
      </div>"""),

# ── JS: settings ────────────────────────────────────────────────────────
("J1 tank settings carry % tolerance",
r"""function tankCfg(){
  var d={capMSD:15000,capHSD:20000,tol:25};
  try{var c=JSON.parse(localStorage.getItem('tankCfg')||'null');
    if(c)return {capMSD:parseFloat(c.capMSD)||d.capMSD,
                 capHSD:parseFloat(c.capHSD)||d.capHSD,
                 tol:(c.tol!=null?parseFloat(c.tol):d.tol)};
  }catch(e){}
  return d;
}
function saveTankCfg(){
  localStorage.setItem('tankCfg',JSON.stringify({
    capMSD:parseFloat(document.getElementById('cfg_cap_msd').value)||15000,
    capHSD:parseFloat(document.getElementById('cfg_cap_hsd').value)||20000,
    tol:parseFloat(document.getElementById('cfg_tol').value)||0
  }));""",
r"""function tankCfg(){
  var d={capMSD:15000,capHSD:20000,tol:25,tolPct:0.5};   // MF_DIPORDER_V1: tolPct
  try{var c=JSON.parse(localStorage.getItem('tankCfg')||'null');
    if(c)return {capMSD:parseFloat(c.capMSD)||d.capMSD,
                 capHSD:parseFloat(c.capHSD)||d.capHSD,
                 tol:(c.tol!=null?parseFloat(c.tol):d.tol),
                 tolPct:(c.tolPct!=null?(parseFloat(c.tolPct)||0):d.tolPct)};
  }catch(e){}
  return d;
}
function saveTankCfg(){
  var _tp=document.getElementById('cfg_tol_pct');
  localStorage.setItem('tankCfg',JSON.stringify({
    capMSD:parseFloat(document.getElementById('cfg_cap_msd').value)||15000,
    capHSD:parseFloat(document.getElementById('cfg_cap_hsd').value)||20000,
    tol:parseFloat(document.getElementById('cfg_tol').value)||0,
    tolPct:(_tp&&_tp.value!=='')?(parseFloat(_tp.value)||0):tankCfg().tolPct
  }));"""),

("J2 ordering rules carry compartments and split",
r"""function orderCfg(){
  var d={leadDays:2, normalKL:4, minKL:10, safetyDays:1, reserveL:500};
  try{
    var c=JSON.parse(localStorage.getItem('orderCfg')||'null');
    if(c)return {
      leadDays:  c.leadDays  !=null?parseFloat(c.leadDays):d.leadDays,
      normalKL:  c.normalKL  !=null?parseFloat(c.normalKL):d.normalKL,
      minKL:     c.minKL     !=null?parseFloat(c.minKL):d.minKL,
      safetyDays:c.safetyDays!=null?parseFloat(c.safetyDays):d.safetyDays,
      reserveL:  c.reserveL  !=null?parseFloat(c.reserveL):d.reserveL
    };
  }catch(e){}
  return d;
}
function saveOrderCfg(){
  var g=function(id,dflt){var e=document.getElementById(id);
    var v=e?parseFloat(e.value):NaN; return isFinite(v)?v:dflt;};
  var d=orderCfg();
  localStorage.setItem('orderCfg',JSON.stringify({
    leadDays:g('cfg_lead_days',d.leadDays), normalKL:g('cfg_normal_kl',d.normalKL),
    minKL:g('cfg_min_kl',d.minKL), safetyDays:g('cfg_safety_days',d.safetyDays),
    reserveL:g('cfg_reserve_l',d.reserveL)}));""",
r"""function orderCfg(){
  var d={leadDays:2, normalKL:4, minKL:10, safetyDays:1, reserveL:500, compKL:'', splitLoads:false};
  try{
    var c=JSON.parse(localStorage.getItem('orderCfg')||'null');
    if(c)return {
      leadDays:  c.leadDays  !=null?parseFloat(c.leadDays):d.leadDays,
      normalKL:  c.normalKL  !=null?parseFloat(c.normalKL):d.normalKL,
      minKL:     c.minKL     !=null?parseFloat(c.minKL):d.minKL,
      safetyDays:c.safetyDays!=null?parseFloat(c.safetyDays):d.safetyDays,
      reserveL:  c.reserveL  !=null?parseFloat(c.reserveL):d.reserveL,
      compKL:    c.compKL!=null?String(c.compKL):d.compKL,          // MF_DIPORDER_V1
      splitLoads:!!c.splitLoads
    };
  }catch(e){}
  return d;
}
function saveOrderCfg(){
  var g=function(id,dflt){var e=document.getElementById(id);
    var v=e?parseFloat(e.value):NaN; return isFinite(v)?v:dflt;};
  var d=orderCfg(), _ck=document.getElementById('cfg_comp_kl'), _sp=document.getElementById('cfg_split');
  localStorage.setItem('orderCfg',JSON.stringify({
    leadDays:g('cfg_lead_days',d.leadDays), normalKL:g('cfg_normal_kl',d.normalKL),
    minKL:g('cfg_min_kl',d.minKL), safetyDays:g('cfg_safety_days',d.safetyDays),
    reserveL:g('cfg_reserve_l',d.reserveL),
    compKL:_ck?String(_ck.value||'').replace(/[^\d.,+ ]/g,'').trim():d.compKL,
    splitLoads:_sp?_sp.value==='1':d.splitLoads}));"""),

("J3 synced config: dip causes, orders, tank chart",
r"""    supplierCfg: g('supplierCfg'),   // MF_OIL_V1: credit days per supplier""",
r"""    supplierCfg: g('supplierCfg'),   // MF_OIL_V1: credit days per supplier
    dipMeta:     g('dipMeta'),       // MF_DIPORDER_V1: cause of each variation
    fuelOrders:  g('fuelOrders'),    // MF_DIPORDER_V1: tankers ordered
    tankChart:   g('tankChart'),     // MF_DIPORDER_V1: dip cm → litres"""),

("J4 apply them",
r"""  _cfgApplyIfNewer('supplierCfg', cfg.supplierCfg);   // MF_OIL_V1""",
r"""  _cfgApplyIfNewer('supplierCfg', cfg.supplierCfg);   // MF_OIL_V1
  if(typeof _cfgMapMerge==='function'){ _cfgMapMerge('dipMeta', cfg.dipMeta); _cfgMapMerge('fuelOrders', cfg.fuelOrders); }   // MF_DIPORDER_V1
  _cfgApplyIfNewer('tankChart', cfg.tankChart);"""),

# ── JS: dips ────────────────────────────────────────────────────────────
("J5 preview uses the scaled tolerance",
r"""  var vr=obs-b.book, tol=tankCfg().tol;""",
r"""  var vr=obs-b.book, tol=(typeof _dipTolBook==='function')?_dipTolBook(b):tankCfg().tol;   // MF_DIPORDER_V1"""),

("J6 reset clears the chart fill",
r"""  var s=document.getElementById('dip_slot'); if(s)s.value=_dipDefaultSlot();   // MF_DIP_SYNC_V1""",
r"""  var s=document.getElementById('dip_slot'); if(s)s.value=_dipDefaultSlot();   // MF_DIP_SYNC_V1
  var _dl=document.getElementById('dip_litres'); if(_dl)_dl.dataset.auto='';
  var _dn=document.getElementById('dip_chart_note'); if(_dn)_dn.textContent='';"""),

("J7 delete a dip: owner/manager, reason, log",
r"""function delDip(id){
  if(!confirm('Delete this dip reading?'))return;
  dipReadings=dipReadings.filter(function(d){return d.id!==id;});
  saveDipsLS();
  if(_currentUser&&typeof sbDelete==='function')sbDelete('dip_readings',id).catch(console.error);
  renderDip();showToast('Dip deleted');
}""",
r"""function delDip(id){
  // MF_DIPORDER_V1: a dip anchors every variation after it
  var r=dipReadings.find(function(d){return String(d.id)===String(id);}); if(!r)return;
  if(typeof _dipCan==='function'&&!_dipCan()){showToast('🔒 Only an owner or manager can delete a dip');return;}
  var why=prompt('Delete the '+r.type+' reading of '+r.date+' ('+(_DIP_SLOT_LBL[r.slot]||r.slot)+', '+r.observed+' L)?\n\n'+
    'Every variation after it will be measured from the reading before it. Reason:','Entered by mistake');
  if(why===null)return;
  dipReadings=dipReadings.filter(function(d){return String(d.id)!==String(id);});
  saveDipsLS();
  if(_currentUser&&typeof sbDelete==='function')sbDelete('dip_readings',r.id).catch(console.error);
  if(typeof logActivity==='function')logActivity('del_dip','dip_reading',r.id,
    r.type+' '+r.date+' '+r.slot+' • '+r.observed+' L (var '+(r.variation>=0?'+':'')+(+r.variation||0).toFixed(1)+') • '+_clean(String(why)));
  renderDip();showToast('Dip deleted');
}"""),

("J8 live variation carries tolerance and cause",
r"""  o.unused=(typeof _dipBeforeOpening==='function')&&_dipBeforeOpening(r);
  return o;""",
r"""  o.unused=(typeof _dipBeforeOpening==='function')&&_dipBeforeOpening(r);
  // MF_DIPORDER_V1
  o.tol=(typeof _dipTolBook==='function')?_dipTolBook(b):tankCfg().tol;
  var _m=(typeof _dipMetaGet==='function')?_dipMetaGet(r.id):null;
  if(_m){ var _c=_dipCause(_m.cause); o.cause=_m.cause||''; o.causeNote=_m.note||''; o.explained=!!(_c&&_c[2]); }
  return o;"""),

("J9 daily list colours by each dip's tolerance",
r"""    var a=r.atg||_atgFromNotes(r.notes), vc=r.unused?'var(--muted)':(Math.abs(r.variation)<=tol?'var(--green)':(r.variation<0?'var(--red)':'var(--diesel)'));""",
r"""    var a=r.atg||_atgFromNotes(r.notes), vc=r.unused?'var(--muted)':((r.explained||Math.abs(r.variation)<=(r.tol!=null?r.tol:tol))?'var(--green)':(r.variation<0?'var(--red)':'var(--diesel)'));"""),

("J10 history row: tolerance, cause, edit",
r"""    var vc=r.unused?'var(--muted)':(Math.abs(r.variation)<=cfg.tol?'var(--green)':(r.variation<0?'var(--red)':'var(--diesel)'));""",
r"""    var vc=r.unused?'var(--muted)':((r.explained||Math.abs(r.variation)<=(r.tol!=null?r.tol:cfg.tol))?'var(--green)':(r.variation<0?'var(--red)':'var(--diesel)'));   // MF_DIPORDER_V1"""),

("J11 history row cells",
r"""      '<td style="color:var(--muted);font-size:11px">'+_esc(r.notes||'')+
        (_dipBeforeOpening(r)?' <span style="color:var(--diesel)">· before opening — not used</span>':'')+'</td>'+   // MF_DIP_SYNC_V1
      '<td><button class="rm-btn" onclick="delDip('+r.id+')">&#10005;</button></td>';""",
r"""      '<td style="font-size:11px;white-space:nowrap">'+(r.cause?'<span style="color:'+(r.explained?'var(--green)':'var(--red)')+'">'+(r.explained?'✓ ':'⚠ ')+_esc((_dipCause(r.cause)||[0,r.cause])[1])+'</span>'+
        (r.causeNote?'<div style="color:var(--muted);white-space:normal">'+_esc(r.causeNote)+'</div>':''):
        (!r.unused&&Math.abs(r.variation)>r.tol?'<span style="color:var(--muted)">±'+r.tol+' L</span>':''))+'</td>'+   // MF_DIPORDER_V1
      '<td style="color:var(--muted);font-size:11px">'+_esc(r.notes||'')+
        (_dipBeforeOpening(r)?' <span style="color:var(--diesel)">· before opening — not used</span>':'')+'</td>'+   // MF_DIP_SYNC_V1
      '<td style="white-space:nowrap"><button class="btn btn-g" style="padding:2px 8px;font-size:10px" onclick="openDipEdit('+r.id+')" title="Correct the reading or record the cause">✎</button> '+
        '<button class="rm-btn" onclick="delDip('+r.id+')">&#10005;</button></td>';"""),

("J12 settings fields + monthly card",
r"""  se('cfg_cap_msd',cfg.capMSD);se('cfg_cap_hsd',cfg.capHSD);se('cfg_tol',cfg.tol);""",
r"""  se('cfg_cap_msd',cfg.capMSD);se('cfg_cap_hsd',cfg.capHSD);se('cfg_tol',cfg.tol);
  se('cfg_tol_pct',cfg.tolPct);   // MF_DIPORDER_V1
  try{ var _tc=_tankChart(); [['MSD','cfg_chart_msd'],['HSD','cfg_chart_hsd']].forEach(function(t){
    var e=document.getElementById(t[1]); if(e&&!e.value&&document.activeElement!==e&&(_tc[t[0]]||[]).length)
      e.value=_tc[t[0]].map(function(p){return p[0]+', '+p[1];}).join('\n'); }); }catch(e){}"""),

("J13 monthly report after the table",
r"""  }).join('');
  dipPreview();
}

function dipExportCsv(){""",
r"""  }).join('');
  try{ if(typeof _dipRenderMonthly==='function')_dipRenderMonthly(); }catch(e){ console.error('dip monthly:',e); }   // MF_DIPORDER_V1
  dipPreview();
}

function dipExportCsv(){"""),

("J14 CSV: cause",
r"""            'opening_l','loaded_l','sold_l','tested_l','notes','recorded_by'];""",
r"""            'opening_l','loaded_l','sold_l','tested_l','notes','recorded_by','tolerance_l','cause','cause_note'];"""),

("J15 CSV row",
r"""      '"'+String(r.notes||'').replace(/"/g,'""')+'"',r.recordedBy||''].join(','));""",
r"""      '"'+String(r.notes||'').replace(/"/g,'""')+'"',r.recordedBy||'',r.tol!=null?r.tol:'',
      ((typeof _dipCause==='function'&&_dipCause(r.cause))||[0,''])[1],'"'+String(r.causeNote||'').replace(/"/g,'""')+'"'].join(','));"""),

("J16 alerts: explained variations stop alerting",
r"""    var total=mine.reduce(function(s,r){return s+(r.variation||0);},0);
    if(Math.abs(total)<=cfg.tol)return;""",
r"""    // MF_DIPORDER_V1: a variation with an explaining cause no longer alerts
    var total=mine.filter(function(r){return !r.explained;}).reduce(function(s,r){return s+(r.variation||0);},0);
    if(Math.abs(total)<=cfg.tol)return;"""),

("J17 re-keyed dip keeps its cause",
r"""      mine.id=newId; saveDipsLS();""",
r"""      mine.id=newId; saveDipsLS();
      if(typeof _dipMetaMove==='function')_dipMetaMove(oldId,newId);   // MF_DIPORDER_V1"""),

# ── JS: ATG gross ───────────────────────────────────────────────────────
("A1 read gross",
r"""           mtd:_atgVal('atg_'+t[1]+'_mtd')};   // MF_FIVE_V1
    if(a.mm==null)a.mm=0; if(a.temp==null)a.temp=0;""",
r"""           mtd:_atgVal('atg_'+t[1]+'_mtd'),   // MF_FIVE_V1
           gross:_atgVal('atg_'+t[1]+'_gross'), net:vol};   // MF_DIPORDER_V1
    if(a.mm==null)a.mm=0; if(a.temp==null)a.temp=0;
    if(a.gross!=null&&!(a.gross>0))a.gross=null;
    if(a.gross!=null&&a.gross>t[2]){errs.push(t[0]+' gross '+a.gross+' L is more than the '+t[2]+' L tank');return;}"""),

("A2 gross is what the book is compared with",
r"""    made.push({type:t[0],vol:vol,a:a});""",
r"""    made.push({type:t[0],vol:(a.gross!=null?a.gross:vol),a:a});   // MF_DIPORDER_V1: gross = tank temperature, like the meters"""),

("A3 note keeps net and gross",
r"""    (a.mtd!=null?' · MTD '+a.mtd+' L':'');   // MF_FIVE_V1""",
r"""    (a.mtd!=null?' · MTD '+a.mtd+' L':'')+   // MF_FIVE_V1
    (a.gross!=null?' · net '+a.net+' L · gross '+a.gross+' L':'');   // MF_DIPORDER_V1"""),

("A4 parse net and gross back",
r"""  return m?{mm:+m[1],temp:+m[2],water:+m[3],sale:m[4]!=null?+m[4]:null,mtd:m[5]!=null?+m[5]:null}:null;   // MF_FIVE_V1""",
r"""  var g=/ · net ([\d.]+) L · gross ([\d.]+) L/.exec(String(n||''));   // MF_DIPORDER_V1
  return m?{mm:+m[1],temp:+m[2],water:+m[3],sale:m[4]!=null?+m[4]:null,mtd:m[5]!=null?+m[5]:null,
            net:g?+g[1]:null,gross:g?+g[2]:null}:null;   // MF_FIVE_V1"""),

("A5 clear gross after saving",
r"""  ['ms','hsd'].forEach(function(k){['vol','mm','water','temp','sale','mtd'].forEach(function(f){""",
r"""  ['ms','hsd'].forEach(function(k){['vol','mm','water','temp','sale','mtd','gross'].forEach(function(f){"""),

# ── JS: order advisor ───────────────────────────────────────────────────
("O1 sales rate without testing fuel",
r"""    var v=(type==='MSD'?(r.msdT||0):(r.hsdT||0));""",
r"""    var v=(type==='MSD'?(r.msdT||0)-(r.testMSDL||0):(r.hsdT||0)-(r.testHSDL||0));   // MF_DIPORDER_V1: testing goes back in the tank"""),

("O2 forecast: age of the level",
r"""           usableL:Math.max(0,lvl.book-cfg.reserveL)};
  if(br.perDay<=0){out.daysLeft=null;out.runoutDate=null;out.orderBy=null;return out;}""",
r"""           usableL:Math.max(0,lvl.book-cfg.reserveL)};
  out.levelAge=(typeof _levelAgeDays==='function')?_levelAgeDays(type):null;   // MF_DIPORDER_V1
  if(br.perDay<=0){out.daysLeft=null;out.runoutDate=null;out.orderBy=null;return out;}"""),

("O3 forecast: orders on the way, room on arrival",
r"""  var left=out.usableL-todayRemaining, days=0, d=new Date();
  if(left<=0){out.daysLeft=0;out.runoutDate=today;out.orderBy=today;out.orderInDays=0;return out;}
  while(left>0 && days<400){
    d.setDate(d.getDate()+1); days++;
    var rate=_dowRate(type,d.getDay());
    left-=(rate!=null?rate:br.perDay);
  }""",
r"""  // MF_DIPORDER_V1: tankers already ordered arrive on their expected day, and
  // the room that matters is the room on the day a tanker ordered now arrives.
  var inc={};
  (typeof _openOrders==='function'?_openOrders(type):[]).forEach(function(o){ var k=_orderEffDate(o); inc[k]=(inc[k]||0)+(+o.kl||0)*1000; });
  out.incoming=Object.keys(inc).sort().map(function(k){ return {date:k,L:inc[k]}; });
  var _la=lvl.book-todayRemaining, _da=new Date(), _ld=Math.max(0,Math.ceil(cfg.leadDays||0));
  for(var _i=0;_i<_ld;_i++){ _da.setDate(_da.getDate()+1); var _ra=_dowRate(type,_da.getDay()); _la-=(_ra!=null?_ra:br.perDay); _la+=(inc[_isoLocal(_da)]||0); }
  out.arrivalDate=_isoLocal(_da); out.arrivalUllage=Math.max(0,cap-Math.max(0,_la));
  var left=out.usableL-todayRemaining, days=0, d=new Date();
  if(left<=0){out.daysLeft=0;out.runoutDate=today;out.orderBy=today;out.orderInDays=0;return out;}
  while(left>0 && days<400){
    d.setDate(d.getDate()+1); days++;
    left+=(inc[_isoLocal(d)]||0);
    var rate=_dowRate(type,d.getDay());
    left-=(rate!=null?rate:br.perDay);
  }"""),

("O4 fit on arrival",
r"""function _fitCheck(f,kl){
  var need=kl*1000;
  if(f.ullage>=need)return {fits:true,waitDays:0};
  if(!f.perDay||f.perDay<=0)return {fits:false,waitDays:null};
  return {fits:false,waitDays:Math.ceil((need-f.ullage)/f.perDay)};
}""",
r"""function _fitCheck(f,kl){
  var need=kl*1000, room=(f.arrivalUllage!=null?f.arrivalUllage:f.ullage);   // MF_DIPORDER_V1: room when it arrives
  if(room>=need)return {fits:true,waitDays:0};
  if(!f.perDay||f.perDay<=0)return {fits:false,waitDays:null};
  return {fits:false,waitDays:Math.ceil((need-room)/f.perDay)};
}"""),

("O5 capacity note: room on arrival",
r"""      text:'Only '+Math.round(f.ullage)+' L of headroom in the '+f.type+' tank — a '+""",
r"""      text:'Only '+Math.round(f.arrivalUllage!=null?f.arrivalUllage:f.ullage)+' L of room in the '+f.type+' tank when a tanker ordered now arrives ('+(f.arrivalDate||'—')+') — a '+"""),

("O6 minimum note: room on arrival",
r"""        (cfg.minKL*1000)+' L of headroom and you have '+Math.round(f.ullage)+' L'+""",
r"""        (cfg.minKL*1000)+' L of room and on arrival there will be '+Math.round(f.arrivalUllage!=null?f.arrivalUllage:f.ullage)+' L'+"""),

("O7 minimum-fits note",
r"""      text:'The '+cfg.minKL+' KL minimum would fit right now ('+Math.round(f.ullage)+
        ' L headroom), so a forced-minimum order is possible if it comes to that.'});""",
r"""      text:'The '+cfg.minKL+' KL minimum would fit on arrival ('+Math.round(f.arrivalUllage!=null?f.arrivalUllage:f.ullage)+
        ' L room), so a forced-minimum order is possible if it comes to that.'});"""),

("O8 orders, stale level, lead time, best size, split",
r"""  // Money — a recommendation to spend lakhs should say what is already owed.""",
r"""  // MF_DIPORDER_V1 ── orders on the way, age of the level, lead time, size
  var _room=f.arrivalUllage!=null?f.arrivalUllage:f.ullage;
  out.room=_room; out.bestKL=_bestFitKL(_room,cfg);
  out.costBest=out.bestKL?_loadCost(f.type,out.bestKL):null;
  out.split=_splitPlan(out,cfg);
  _openOrders().filter(function(o){ return String(o.expected)<_isoLocal(); }).forEach(function(o){
    out.notes.unshift({level:'warn',text:o.type+' '+o.kl+' KL ordered '+o.orderedOn+' was due '+o.expected+
      ' and no load has been entered — chase the supplier, or enter the tanker bill if it came.'}); });
  [fM,fH].forEach(function(x){ (x.incoming||[]).forEach(function(i){
    out.notes.unshift({level:'info',text:'Counting '+_r2(i.L/1000)+' KL '+x.type+' already ordered, arriving '+i.date+' — the dates above include it.'}); }); });
  [fM,fH].forEach(function(x){ var ag=x.levelAge; if(ag&&ag.days>=2)
    out.notes.push({level:'warn',text:x.type+' level is worked out on paper from the '+(ag.dip?'tank reading':'opening stock')+' of '+ag.date+
      ' — '+ag.days+' days ago. Enter today’s ATG reading on the Dip page; every date here rests on it.'}); });
  var _lh=_leadHistory();
  if(_lh&&_lh.n>=2&&Math.abs(_lh.avg-cfg.leadDays)>=0.5)   // one tanker is not a pattern
    out.notes.push({level:_lh.avg>cfg.leadDays?'warn':'info',text:'Your last '+_lh.n+' tanker'+(_lh.n>1?'s':'')+' took '+_lh.avg.toFixed(1)+
      ' days from order to arrival (longest '+_lh.max+'). Lead time is set to '+cfg.leadDays+' — change it under Ordering rules if that is the new normal.'});
  if(out.split)out.notes.push({level:'info',text:'Both tanks are due close together — one split tanker of '+out.split.MSD+' KL MSD + '+out.split.HSD+' KL HSD fits on arrival.'});

  // Money — a recommendation to spend lakhs should say what is already owed."""),

("O9 advisor settings fields",
r"""  se('cfg_reserve_l',cfg.reserveL);""",
r"""  se('cfg_reserve_l',cfg.reserveL);
  var _ck=document.getElementById('cfg_comp_kl'); if(_ck&&!_ck.value&&document.activeElement!==_ck)_ck.value=cfg.compKL||'';   // MF_DIPORDER_V1
  var _sp=document.getElementById('cfg_split'); if(_sp)_sp.value=cfg.splitLoads?'1':'0';"""),

("O10 size cards: arrival room, best fit, split",
r"""      var opts=[{kl:cfg.normalKL,fit:a.fitNormal,cost:a.costNormal,lbl:'NORMAL ORDER'}];
      if(cfg.minKL>cfg.normalKL)
        opts.push({kl:cfg.minKL,fit:a.fitMin,cost:a.costMin,lbl:'SUPPLIER MINIMUM'});
      sz.innerHTML=opts.map(function(o){
        var col=o.fit.fits?'var(--green)':'var(--red)';
        var msg=o.fit.fits?'✓ fits — '+Math.round(f.ullage)+' L headroom'
          :(o.fit.waitDays!=null?'✕ needs '+(o.kl*1000-f.ullage>0?Math.round(o.kl*1000-f.ullage):0)+
              ' L more room (~'+o.fit.waitDays+'d)':'✕ will not fit');""",
r"""      var opts=[{kl:cfg.normalKL,fit:a.fitNormal,cost:a.costNormal,lbl:'NORMAL ORDER'}];
      if(cfg.minKL>cfg.normalKL)
        opts.push({kl:cfg.minKL,fit:a.fitMin,cost:a.costMin,lbl:'SUPPLIER MINIMUM'});
      // MF_DIPORDER_V1: the largest load that fits when it arrives; a split load
      var _rm=(a.room!=null?a.room:f.ullage), _ad=f.arrivalDate?f.arrivalDate.slice(8,10)+'/'+f.arrivalDate.slice(5,7):'arrival';
      if(a.bestKL&&a.bestKL!==cfg.normalKL&&a.bestKL!==cfg.minKL)
        opts.push({kl:a.bestKL,fit:{fits:true},cost:a.costBest,lbl:'MOST THAT FITS ON '+_ad});
      if(a.split)opts.push({kl:a.split.total,title:a.split.MSD+' KL MSD + '+a.split.HSD+' KL HSD',fit:{fits:true},
        cost:(_loadCost('MSD',a.split.MSD)||0)+(_loadCost('HSD',a.split.HSD)||0)||null,lbl:'ONE SPLIT TANKER'});
      sz.innerHTML=opts.map(function(o){
        var col=o.fit.fits?'var(--green)':'var(--red)';
        var msg=o.fit.fits?'✓ fits on '+_ad+' — '+Math.round(_rm)+' L room'
          :(o.fit.waitDays!=null?'✕ needs '+(o.kl*1000-_rm>0?Math.round(o.kl*1000-_rm):0)+
              ' L more room on '+_ad+' (~'+o.fit.waitDays+'d later)':'✕ will not fit');"""),

("O11 size card title",
r"""          '<div style="font-family:\'JetBrains Mono\',monospace;font-size:18px;font-weight:700;color:var(--text)">'+o.kl+' KL '+_esc(f.type)+'</div>'+""",
r"""          '<div style="font-family:\'JetBrains Mono\',monospace;font-size:18px;font-weight:700;color:var(--text)">'+(o.title?_esc(o.title):o.kl+' KL '+_esc(f.type))+'</div>'+"""),

("O12 KPI: age of the level",
r"""      (x.todayComplete===false?' • today not fully entered':'')+'</div></div>';""",
r"""      (x.todayComplete===false?' • today not fully entered':'')+
      (x.levelAge&&x.levelAge.days>=2?' • <span style="color:var(--diesel)">level from '+x.levelAge.date.slice(8,10)+'/'+x.levelAge.date.slice(5,7)+' reading</span>':'')+'</div></div>';"""),

("O13 orders panel",
r"""  renderAdvChart(a);
}

function renderAdvChart(a){""",
r"""  renderAdvChart(a);
  try{ if(typeof _renderOrders==='function')_renderOrders(a); }catch(e){ console.error('orders:',e); }   // MF_DIPORDER_V1
}

function renderAdvChart(a){"""),

("O14 chart counts orders on the way",
r"""    d.setDate(d.getDate()+1);
    var rm=_dowRate('MSD',d.getDay()); var rh=_dowRate('HSD',d.getDay());""",
r"""    d.setDate(d.getDate()+1);
    if(typeof _incomingOn==='function'){ var _k=_isoLocal(d); lvl.MSD+=_incomingOn('MSD',_k); lvl.HSD+=_incomingOn('HSD',_k); }   // MF_DIPORDER_V1
    var rm=_dowRate('MSD',d.getDay()); var rh=_dowRate('HSD',d.getDay());"""),

# ── module ──────────────────────────────────────────────────────────────
("V1 dip + order module",
r"""// ══════════════════════════════════════════════════════════════════
// ORDER ADVISOR
//
// Deliberately arithmetic, not a model.""",
MODULE + r"""

// ══════════════════════════════════════════════════════════════════
// ORDER ADVISOR
//
// Deliberately arithmetic, not a model."""),
]


def main():
    if not os.path.exists(PATH):
        sys.exit(f"✗ {PATH} not found")
    src = open(PATH, encoding="utf-8").read()
    for need in ("MF_ATG_REVERSE_V1", "MF_FIVE_V1", "MF_FUELLOAD_V1"):
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
