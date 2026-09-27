#!/usr/bin/env python3
"""
MF_DASH_PULSE_V4 — dashboard "Business Pulse", as asked for:

  1. PROFIT OF THE DAY   yesterday (complete) and today so far, split by shift
  2. MONTHLY TARGET      litres and/or profit target, progress, needed per day
                         (target syncs across phones via app_settings.config)
  3. LAST WEEK vs WEEK BEFORE   two COMPLETE Mon–Sun weeks, never a partial one
  4. MONEY LEAKS & PROBLEMS     checks run over the last 7 days:
       cash short · fuel between shifts not recorded (meter gaps) ·
       fuel cost per litre out of range · tank stock loss (dip) ·
       loss-making days · expenses above normal · shifts not saved ·
       credit growing faster than it is collected

Replaces MF_DASH_PULSE_V3 (or the original card). Same engine as Reports.
Usage:  python3 patch_dash_pulse_v4.py [path/to/index.html]   (idempotent)
"""
import re, os, sys, shutil, subprocess, tempfile

PATH = sys.argv[1] if len(sys.argv) > 1 else "index.html"
SENTINEL = "MF_DASH_PULSE_V4"
START = "function renderWeeklyPL(){"
END = "// ── DATE: always work in LOCAL time."

TITLES = ['<span class="dot dpu"></span>PROFIT vs LOSS — THIS WEEK vs LAST WEEK</div>',
          '<span class="dot dpu"></span>BUSINESS PULSE — THIS MONTH · LAST 7 DAYS · MONEY</div>']
TITLE_NEW = '<span class="dot dpu"></span>BUSINESS PULSE — DAY · TARGET · WEEKS · LEAKS</div>'

CFG_HUNKS = [
 ("    payrollCfg:  g('payrollCfg'),\n",
  "    payrollCfg:  g('payrollCfg'),\n    monthTarget: g('monthTarget'),   // MF_DASH_PULSE_V4\n"),
 ("  _cfgApplyIfNewer('packStockCfg', cfg.packStockCfg);\n",
  "  _cfgApplyIfNewer('packStockCfg', cfg.packStockCfg);\n  _cfgApplyIfNewer('monthTarget', cfg.monthTarget);   // MF_DASH_PULSE_V4\n"),
]

NEW = r"""function renderWeeklyPL(){
  // MF_DASH_PULSE_V4 — profit of the day, monthly target, last complete week
  // vs the week before, and a money-leak check list. Same engine as Reports.
  const el=document.getElementById('dashWeeklyPL');
  if(!el)return;
  const now=new Date();
  const iso=d=>_isoLocal(d);
  const addD=(s,n)=>{const p=s.split('-');const d=new Date(+p[0],+p[1]-1,+p[2]);d.setDate(d.getDate()+n);return iso(d);};
  const GREEN='var(--green)', RED='var(--red)', AMBER='var(--diesel)', MUTED='var(--muted)', TEXT='var(--text)';
  const dm=s=>{const p=s.split('-');return new Date(+p[0],+p[1]-1,+p[2]).toLocaleDateString('en-IN',{day:'numeric',month:'short'});};
  const wd=s=>{const p=s.split('-');return new Date(+p[0],+p[1]-1,+p[2]).toLocaleDateString('en-IN',{weekday:'short'});};
  const k=n=>{const a=Math.abs(n),sg=n<0?'−':'';
    return a>=100000?sg+'₹'+(a/100000).toFixed(2)+'L':(a>=1000?sg+'₹'+(a/1000).toFixed(1)+'k':sg+'₹'+Math.round(a));};
  const R0=n=>(n<0?'−':'')+'₹'+Math.round(Math.abs(n)).toLocaleString('en-IN');
  const perL=n=>(n<0?'−':'')+'₹'+Math.abs(n).toFixed(2)+'/L';
  const Lfmt=n=>Math.round(n).toLocaleString('en-IN')+' L';
  const litres=P=>(P.soldMSDL||0)+(P.soldHSDL||0);
  const slotTxt=s=>{const p=s.date.split('-');return p[2]+'/'+p[1]+' '+(s.shift==='morning'?'MOR':'NIGHT');};
  const recsIn=(a,b)=>records.filter(r=>r.date>=a&&r.date<=b);
  const slots=(a,b)=>{const out=[];for(let d=a;d<=b;d=addD(d,1)){['morning','night'].forEach(sh=>{const s={date:d,shift:sh};if(mfSlotEnd(s)<=now)out.push(s);});}return out;};
  const missing=(a,b)=>slots(a,b).filter(s=>!mfSlotSaved(s));
  const P=(a,b)=>_plCore(recsIn(a,b),a,b);
  const box='padding:12px 14px;background:var(--s3);border:1px solid var(--border2);border-radius:8px';
  const lbl=t=>'<div style="font-family:\'Syne\',sans-serif;font-size:10px;letter-spacing:1.5px;color:var(--muted);margin-bottom:6px">'+t+'</div>';
  const big=(v,c)=>'<div style="font-family:\'JetBrains Mono\',monospace;font-size:20px;font-weight:800;color:'+c+'">'+v+'</div>';
  const small=(t,c)=>'<div style="font-size:10px;color:'+(c||MUTED)+';margin-top:4px;line-height:1.55">'+t+'</div>';
  const band=t=>'<div style="font-family:\'Syne\',sans-serif;font-size:10px;font-weight:700;letter-spacing:1.5px;color:var(--muted);margin:14px 0 8px">'+t+'</div>';
  const grid='display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px';
  const todayIso=iso(now), yIso=addD(todayIso,-1);

  // ── 1. PROFIT OF THE DAY ─────────────────────────────────────────────
  const dayTile=(d,title)=>{
    const R=recsIn(d,d), Pd=_plCore(R,d,d), L=litres(Pd);
    const known=!Pd.fuelUncosted&&R.length>0;
    const miss=missing(d,d);
    const per=['morning','night'].map(sh=>{
      const r=R.find(x=>x.shift===sh), s={date:d,shift:sh};
      if(!r)return (sh==='morning'?'Morning':'Night')+': '+(mfSlotEnd(s)<=now?'<span style="color:'+AMBER+'">not saved</span>':'running');
      const p=_plCore([r],d,d).netProfit;
      return (sh==='morning'?'Morning':'Night')+': <span style="color:'+(p>=0?GREEN:RED)+'">'+k(p)+'</span>';
    }).join(' · ');
    return '<div style="'+box+';cursor:pointer" onclick="_dashOpenDay(\''+d+'\')">'+lbl(title+' — '+wd(d).toUpperCase()+' '+dm(d).toUpperCase())+
      big(known?R0(Pd.netProfit):'—', known?(Pd.netProfit>=0?GREEN:RED):MUTED)+
      small(per+'<br>'+(known?(Lfmt(L)+' sold · '+perL(L>0?Pd.netProfit/L:0)):(R.length?'fuel cost not recorded yet':'no shift saved yet'))+
            (miss.length?'<br><span style="color:'+AMBER+'">'+miss.length+' shift not saved — incomplete</span>':'')+
            '<br><span style="color:var(--muted)">tap to open in Reports</span>')+'</div>';
  };
  let html=band('PROFIT OF THE DAY');
  html+='<div style="'+grid+'">'+dayTile(yIso,'YESTERDAY')+dayTile(todayIso,'TODAY SO FAR')+'</div>';

  // ── 2. MONTHLY TARGET ────────────────────────────────────────────────
  const T=_mfTarget();
  const mStart=todayIso.slice(0,8)+'01';
  const dim=new Date(now.getFullYear(),now.getMonth()+1,0).getDate();
  const dayNo=now.getDate();
  const Pm=P(mStart,todayIso), mL=litres(Pm);
  const mKnown=!Pm.fuelUncosted;
  const daysLeft=dim-dayNo+1;   // today still counts
  const bar=(done,target,col)=>{const pct=target>0?Math.min(100,done/target*100):0;
    const exp=target>0?Math.min(100,(dayNo-0.5)/dim*100):0;
    return '<div style="position:relative;height:10px;background:var(--bg);border:1px solid var(--border2);border-radius:5px;margin:6px 0 4px;overflow:hidden">'+
      '<div style="height:100%;width:'+pct.toFixed(1)+'%;background:'+col+';opacity:.85"></div>'+
      '<div title="where you should be today" style="position:absolute;top:-1px;bottom:-1px;left:'+exp.toFixed(1)+'%;width:2px;background:var(--text)"></div></div>';};
  const tgtRow=(name,done,target,fmtFn,avg)=>{
    const pace=target*(dayNo-0.5)/dim, ahead=done-pace, need=Math.max(0,target-done)/Math.max(1,daysLeft);
    const col=done>=target?GREEN:(ahead>=0?GREEN:AMBER);
    return '<div style="margin-bottom:8px"><div style="display:flex;justify-content:space-between;font-size:11px"><b>'+name+'</b>'+
      '<span style="font-family:\'JetBrains Mono\',monospace">'+fmtFn(done)+' / '+fmtFn(target)+' ('+(target>0?Math.round(done/target*100):0)+'%)</span></div>'+
      bar(done,target,col)+
      '<div style="font-size:10px;color:'+col+'">'+(done>=target?'✓ Target reached':
        ((ahead>=0?'On track — ahead by ':'Behind by ')+fmtFn(Math.abs(ahead))+' · need '+fmtFn(need)+' per day for '+daysLeft+' day'+(daysLeft!==1?'s':'')+
         (avg!=null?' (your average so far: '+fmtFn(avg)+'/day)':'')))+'</div></div>';
  };
  const lastMonthL=(function(){const f=new Date(now.getFullYear(),now.getMonth()-1,1);const e=new Date(now.getFullYear(),now.getMonth(),0);
    return litres(P(iso(f),iso(e)));})();
  html+=band('MONTHLY TARGET — '+now.toLocaleDateString('en-IN',{month:'long',year:'numeric'}).toUpperCase()+
    ' &nbsp;<span onclick="_mfEditTarget()" style="cursor:pointer;color:var(--petrol);letter-spacing:1px">✎ '+((T.litres||T.profit)?'CHANGE':'SET')+' TARGET</span>');
  html+='<div style="'+box+'">';
  html+='<div id="mfTargetEdit" style="display:none;margin-bottom:10px;font-size:11px">'+
    'Litres per month <input id="mfTgtL" type="number" min="0" step="100" style="width:110px" value="'+(T.litres||'')+'" placeholder="'+(lastMonthL>0?Math.round(lastMonthL*1.05/100)*100:'')+'"> &nbsp; '+
    'Profit per month ₹ <input id="mfTgtP" type="number" min="0" step="1000" style="width:120px" value="'+(T.profit||'')+'"> &nbsp; '+
    '<button class="btn btn-g" style="padding:3px 10px;font-size:10px" onclick="_mfSaveTarget()">SAVE</button>'+
    (lastMonthL>0?'<div style="color:var(--muted);font-size:10px;margin-top:4px">Last month you sold '+Lfmt(lastMonthL)+'. Leave a box empty to not track it. Same target every month until you change it; syncs to every phone.</div>':'')+
    '</div>';
  if(!T.litres&&!T.profit){
    html+='<div style="font-size:11px;color:var(--muted)">No target set yet. Tap <b style="color:var(--petrol)">✎ SET TARGET</b> above'+
      (lastMonthL>0?' — last month you sold '+Lfmt(lastMonthL)+'.':'.')+' So far this month: '+Lfmt(mL)+(mKnown?' · profit '+R0(Pm.netProfit):'')+'</div>';
  } else {
    if(T.litres)html+=tgtRow('Litres sold',mL,T.litres,Lfmt,Pm.shifts?mL/Math.max(1,dayNo-(mfSlotEnd({date:todayIso,shift:'night'})>now?1:0)):null);
    if(T.profit)html+=mKnown?tgtRow('Profit',Pm.netProfit,T.profit,k,null)
                            :'<div style="font-size:10px;color:var(--muted)">Profit target: needs fuel cost on record.</div>';
    html+='<div style="font-size:9px;color:var(--muted)">White line = where you should be today.</div>';
  }
  html+='</div>';

  // ── 3. LAST WEEK vs THE WEEK BEFORE (complete Mon–Sun weeks) ────────
  const dow=s=>{const p=s.split('-');return new Date(+p[0],+p[1]-1,+p[2]).getDay();};
  let sun=todayIso; while(dow(sun)!==0)sun=addD(sun,-1);
  if(mfSlotEnd({date:sun,shift:'night'})>now)sun=addD(sun,-7);   // this week not finished yet
  const wA={from:addD(sun,-6),to:sun}, wB={from:addD(sun,-13),to:addD(sun,-7)};
  [wA,wB].forEach(w=>{w.P=P(w.from,w.to);w.L=litres(w.P);w.miss=missing(w.from,w.to);w.known=!w.P.fuelUncosted&&w.P.shifts>0;
    w.perL=w.L>0?w.P.netProfit/w.L:0;});
  const both=wA.known&&wB.known, fair=!wA.miss.length&&!wB.miss.length;
  const cmp=(a,b,f,higherGood)=>{if(!both)return '<td style="text-align:right;color:var(--muted)">—</td>';
    const d=a-b, c=!fair?AMBER:((d>=0)===(higherGood!==false)?GREEN:RED);
    return '<td style="text-align:right;padding:2px 0 2px 8px;white-space:nowrap;color:'+c+';font-family:\'JetBrains Mono\',monospace">'+(d>=0?'▲ ':'▼ ')+f(Math.abs(d))+'</td>';};
  const td=(v,c)=>'<td style="text-align:right;padding:2px 0 2px 8px;white-space:nowrap;font-family:\'JetBrains Mono\',monospace;color:'+(c||TEXT)+'">'+v+'</td>';
  const wkName=w=>dm(w.from)+' – '+dm(w.to);
  html+=band('LAST WEEK vs THE WEEK BEFORE (MON–SUN, COMPLETE WEEKS ONLY)');
  html+='<div style="'+box+';overflow-x:auto"><table style="width:100%;border-collapse:collapse;font-size:11px">'+
    '<tr style="color:var(--muted);font-size:10px"><td></td><td style="text-align:right;padding-left:8px">'+wkName(wA)+'</td><td style="text-align:right;padding-left:8px">'+wkName(wB)+'</td><td style="text-align:right;padding-left:8px">CHANGE</td></tr>'+
    '<tr><td>Profit</td>'+td(wA.known?R0(wA.P.netProfit):'—',wA.P.netProfit<0?RED:null)+td(wB.known?R0(wB.P.netProfit):'—',wB.P.netProfit<0?RED:null)+cmp(wA.P.netProfit,wB.P.netProfit,R0)+'</tr>'+
    '<tr><td>Profit per litre</td>'+td(wA.known?perL(wA.perL):'—')+td(wB.known?perL(wB.perL):'—')+cmp(wA.perL,wB.perL,perL)+'</tr>'+
    '<tr><td>Litres sold</td>'+td(Lfmt(wA.L))+td(Lfmt(wB.L))+cmp(wA.L,wB.L,Lfmt)+'</tr>'+
    '<tr><td>Revenue</td>'+td(k(wA.P.revenue))+td(k(wB.P.revenue))+cmp(wA.P.revenue,wB.P.revenue,k)+'</tr>'+
    '<tr><td>Running expenses</td>'+td(R0(wA.P.opex))+td(R0(wB.P.opex))+cmp(wA.P.opex,wB.P.opex,R0,false)+'</tr>'+
    '<tr><td>Shifts saved</td>'+td(wA.P.shifts+' / 14',wA.miss.length?AMBER:null)+td(wB.P.shifts+' / 14',wB.miss.length?AMBER:null)+'<td></td></tr>'+
    '</table>'+(fair?'':small('⚠ Shifts missing ('+wA.miss.concat(wB.miss).slice(0,4).map(slotTxt).join(', ')+(wA.miss.length+wB.miss.length>4?' …':'')+') — totals are not a fair comparison; profit per litre still is.',AMBER))+'</div>';

  // ── 4. MONEY LEAKS & PROBLEMS (last 7 days) ─────────────────────────
  let lastDay=todayIso; if(mfSlotEnd({date:todayIso,shift:'night'})>now)lastDay=yIso;
  const w0=addD(lastDay,-6);
  const R7=recsIn(w0,lastDay);
  const issues=[];   // {lvl:'red'|'amber', icon, title, detail, rs, page}
  // a. cash short
  const shorts=R7.filter(r=>(r.bal||0)<-50).sort((a,b)=>a.bal-b.bal);
  if(shorts.length){const tot=shorts.reduce((s,r)=>s+r.bal,0);
    issues.push({lvl:tot<-500?'red':'amber',icon:'💸',title:'Cash short '+R0(Math.abs(tot))+' on '+shorts.length+' shift'+(shorts.length>1?'s':''),
      detail:shorts.slice(0,3).map(r=>slotTxt(r)+' −'+k(Math.abs(r.bal))).join(' · ')+' — not counted in profit',page:'history'});}
  // b. meter gaps between consecutive shifts (fuel dispensed between shifts, never billed)
  const byId={}; records.forEach(r=>{byId[r.id]=r;});
  let gapL=0, gapRs=0, gapTxt=[], gapBad=0;
  R7.forEach(function(r){
    const pv=byId[mfSlotId(mfPrevSlot({date:r.date,shift:r.shift}))]; if(!pv||!r.meters||!pv.meters)return;
    [['msd1','MSD M1'],['msd2','MSD M2'],['hsd1','HSD M1'],['hsd2','HSD M2']].forEach(function(n){
      const a=parseFloat(pv.meters[n[0]+'_cur']), b=parseFloat(r.meters[n[0]+'_prev']);
      if(!(a>0)||!(b>0))return;
      const g=b-a; if(Math.abs(g)<0.5)return;
      if(g>0){const fuelMSD=n[0].indexOf('msd')===0; const rate=fuelMSD?(r.msdT>0?r.msdV/r.msdT:0):(r.hsdT>0?r.hsdV/r.hsdT:0);
        gapL+=g; gapRs+=g*rate; gapTxt.push(n[1]+' '+slotTxt(r)+' +'+g.toFixed(1)+' L');}
      else gapBad++;
    });
  });
  if(gapL>0)issues.push({lvl:'red',icon:'⛽',title:gapL.toFixed(1)+' L sold between shifts, never recorded (≈'+R0(gapRs)+')',
    detail:'Opening reading higher than the previous closing: '+gapTxt.slice(0,3).join(' · ')+(gapTxt.length>3?' …':''),page:'history'});
  if(gapBad)issues.push({lvl:'amber',icon:'🔢',title:gapBad+' meter reading'+(gapBad>1?'s':'')+' lower than the previous closing',
    detail:'Opening below the last closing usually means a typing mistake in a reading',page:'history'});
  // c. fuel cost per litre vs pump rate — a wrong tanker entry makes every litre look like a loss
  try{const rates=JSON.parse(localStorage.getItem('fuelRates')||'{}');
    [['MSD',parseFloat(rates.msd)],['HSD',parseFloat(rates.hsd)]].forEach(function(f){
      const w=_fuelWAC(f[0],todayIso); if(!(w>0)||!(f[1]>0))return; const m=f[1]-w;
      if(m<1||m>8)issues.push({lvl:'red',icon:'🧾',title:f[0]+' cost ₹'+w.toFixed(2)+'/L vs pump ₹'+f[1].toFixed(2)+'/L — margin '+perL(m),
        detail:(m<1?'Too low — profit will show as a loss. ':'Too high — profit will be overstated. ')+'Check the tanker entries and opening stock cost under Fuel Loads.',page:'fuelload'});
    });}catch(e){}
  // d. tank stock loss from dip readings in the window
  try{if(typeof dipReadings!=='undefined'&&dipReadings.length){const tol=(typeof tankCfg==='function'?tankCfg().tol:20)||20;
    ['MSD','HSD'].forEach(function(t){const v=dipReadings.filter(x=>x.type===t&&x.date>=w0&&x.date<=lastDay).reduce((s,x)=>s+(x.variation||0),0);
      if(v<-tol){const w=_fuelWAC(t,lastDay);
        issues.push({lvl:'red',icon:'📏',title:t+' tank short '+Math.abs(v).toFixed(1)+' L by dip'+(w>0?' (≈'+R0(Math.abs(v)*w)+')':''),
          detail:'Physical stock below book stock — leak, theft or meter drift. Not charged to profit.',page:'dip'});}});}}catch(e){}
  // e. loss-making days
  const lossDays=[]; for(let d=w0;d<=lastDay;d=addD(d,1)){const R=recsIn(d,d); if(!R.length)continue; const Pd=_plCore(R,d,d); if(!Pd.fuelUncosted&&Pd.netProfit<0)lossDays.push({d:d,p:Pd.netProfit});}
  if(lossDays.length)issues.push({lvl:'red',icon:'📉',title:lossDays.length+' day'+(lossDays.length>1?'s':'')+' made a loss',
    detail:lossDays.slice(0,4).map(x=>wd(x.d)+' '+dm(x.d)+' '+k(x.p)).join(' · ')+' — tap a day above or open Reports',page:'report'});
  // f. expenses above normal (vs the 3 weeks before)
  const heads=R=>R.reduce((h,r)=>{const e=(r.meters&&r.meters.exp)||{};['items','tea','chit','other'].forEach(x=>h[x]+=parseFloat(e[x])||0);return h;},{items:0,tea:0,chit:0,other:0});
  const hA=heads(R7), hB=heads(recsIn(addD(w0,-21),addD(w0,-1)));
  const sum=h=>h.items+h.tea+h.chit+h.other, normal=sum(hB)/3;
  if(normal>0&&sum(hA)>normal*1.5&&sum(hA)-normal>1000){const top=Object.keys(hA).sort((a,b)=>hA[b]-hA[a])[0];
    issues.push({lvl:'amber',icon:'🧮',title:'Expenses '+R0(sum(hA))+' this week — normally about '+R0(normal),
      detail:'Biggest: '+({items:'Items',tea:'Tea / Food',chit:'Chit Fund',other:'Other'}[top])+' '+R0(hA[top])+'. Check nothing was typed under the wrong head (e.g. cash handed over under Other).',page:'history'});}
  // g. shifts not saved (14 days)
  const miss14=missing(addD(lastDay,-13),todayIso);
  if(miss14.length)issues.push({lvl:'amber',icon:'📋',title:miss14.length+' closed shift'+(miss14.length>1?'s':'')+' not saved',
    detail:miss14.slice(0,4).map(slotTxt).join(' · ')+(miss14.length>4?' …':'')+' — every report is incomplete until they are entered',page:'entry'});
  // h. credit growing faster than collected
  const cGiven=R7.reduce((s,r)=>s+(r.credit||0),0), cBack=R7.reduce((s,r)=>s+(r.credBack||0),0);
  if(cGiven-cBack>20000)issues.push({lvl:'amber',icon:'📒',title:'Credit grew by '+R0(cGiven-cBack)+' this week',
    detail:'Given '+R0(cGiven)+' · collected '+R0(cBack)+'. Cash is going out as fuel faster than it comes back.',page:'ledger'});

  issues.sort((a,b)=>(a.lvl==='red'?0:1)-(b.lvl==='red'?0:1));
  html+=band('MONEY LEAKS & PROBLEMS — '+dm(w0).toUpperCase()+' – '+dm(lastDay).toUpperCase());
  html+='<div style="'+box+'">'+(issues.length?issues.map(function(x){
    const c=x.lvl==='red'?RED:AMBER;
    return '<div onclick="showPage(\''+x.page+'\')" style="display:flex;gap:10px;align-items:flex-start;padding:8px 4px;border-bottom:1px dotted var(--border2);cursor:pointer">'+
      '<div style="font-size:16px;line-height:1">'+x.icon+'</div><div style="flex:1;min-width:0">'+
      '<div style="font-size:12px;font-weight:700;color:'+c+'">'+_esc(x.title)+'</div>'+
      '<div style="font-size:10px;color:var(--muted);margin-top:2px;line-height:1.5">'+_esc(x.detail)+'</div></div>'+
      '<div style="font-size:10px;color:var(--muted);white-space:nowrap">OPEN →</div></div>';
  }).join(''):'<div style="font-size:12px;color:'+GREEN+'">✓ No leaks or problems found in the last 7 days.</div>')+
  '<div style="font-size:9px;color:var(--muted);margin-top:6px">Checks: cash short · fuel between shifts · fuel cost per litre · tank dip · loss days · expenses · missing shifts · credit growth</div></div>';

  el.innerHTML=html;
}
// Monthly target — one standing target, synced through app_settings.config.
function _mfTarget(){
  var t=null; try{ t=JSON.parse(localStorage.getItem('monthTarget')||'null'); }catch(e){}
  t=(t&&typeof t==='object')?t:{};
  return {litres:parseFloat(t.litres)||0, profit:parseFloat(t.profit)||0, updatedAt:t.updatedAt||''};
}
function _mfEditTarget(){
  var e=document.getElementById('mfTargetEdit'); if(!e)return;
  e.style.display=e.style.display==='none'?'block':'none';
}
function _mfSaveTarget(){
  var L=parseFloat((document.getElementById('mfTgtL')||{}).value)||0;
  var Pr=parseFloat((document.getElementById('mfTgtP')||{}).value)||0;
  localStorage.setItem('monthTarget',JSON.stringify({litres:L,profit:Pr,updatedAt:new Date().toISOString()}));
  if(typeof queueSettingsSave==='function')queueSettingsSave();
  if(typeof logActivity==='function')logActivity('set_target','settings',null,'Monthly target: '+(L?L+' L':'—')+' / '+(Pr?'₹'+Pr:'—'));
  if(typeof showToast==='function')showToast('✓ Monthly target saved');
  renderWeeklyPL();
}
// Open one day in Reports (profit & loss with workings).
function _dashOpenDay(d){
  const f=document.getElementById('rep_from'), t=document.getElementById('rep_to');
  if(f)f.value=d; if(t)t.value=d;
  showPage('report');
  if(typeof genReport==='function'&&document.getElementById('page-report')&&
     document.getElementById('page-report').classList.contains('active'))genReport();
}

"""


def main():
    src = open(PATH, encoding="utf-8").read()
    if SENTINEL in src and "function _mfTarget" in src:
        print("Nothing to do — MF_DASH_PULSE_V4 already applied."); return
    a = src.find(START); b = src.find(END)
    if a < 0 or b < 0 or b <= a or src.count(START) != 1:
        sys.exit("✗ renderWeeklyPL boundaries not found exactly once — nothing written.")
    out = src[:a] + NEW + src[b:]
    t = [x for x in TITLES if out.count(x) == 1]
    if t: out = out.replace(t[0], TITLE_NEW); print("  ✓ card title updated")
    elif TITLE_NEW not in out: sys.exit("✗ card title anchor not found — nothing written.")
    for old, new in CFG_HUNKS:
        if new in out: continue
        if out.count(old) != 1: sys.exit("✗ settings-sync anchor not found once: " + old.strip()[:50])
        out = out.replace(old, new); print("  ✓ target added to settings sync")
    scripts = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", out, flags=re.S | re.I)
    with tempfile.TemporaryDirectory() as td:
        for i, js in enumerate(scripts):
            p = os.path.join(td, f"s{i}.js"); open(p, "w", encoding="utf-8").write(js)
            r = subprocess.run(["node", "--check", p], capture_output=True, text=True)
            if r.returncode: sys.exit(f"✗ node --check failed on script #{i}:\n{r.stderr}\nNothing written.")
    shutil.copyfile(PATH, PATH + ".bak")
    open(PATH, "w", encoding="utf-8").write(out)
    print(f"✓ {SENTINEL} applied; node --check passed on {len(scripts)} script(s); backup {PATH}.bak")


if __name__ == "__main__":
    main()
